"""Message handler orchestrator — routes messages to Claude and back."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass

from cc_feishu_bridge.feishu.client import FeishuClient, IncomingMessage
from cc_feishu_bridge.security.auth import Authenticator
from cc_feishu_bridge.security.validator import SecurityValidator
from cc_feishu_bridge.claude.integration import ClaudeIntegration
from cc_feishu_bridge.claude.session_manager import SessionManager
from cc_feishu_bridge.format.reply_formatter import ReplyFormatter
from cc_feishu_bridge.format.edit_diff import _DiffMarker

logger = logging.getLogger(__name__)

# Match a slash-command like "/stop", "/new", "/feishu auth", "/status foo"
# Commands: / + letter + word-chars, optionally followed by space + args
# NOT a path: paths contain slashes later (e.g. /Users/x/...)
_COMMAND_RE = re.compile(r"^/[a-zA-Z][a-zA-Z0-9_-]*(?:\s.*)?$")


def _is_command(text: str) -> bool:
    """Return True if text looks like a slash command, not a Unix path."""
    return bool(_COMMAND_RE.match(text))


@dataclass
class HandlerResult:
    success: bool
    response_text: str | None = None
    error: str | None = None


class StreamAccumulator:
    """Accumulates streaming text chunks and flushes them to Feishu in batches.

    Feishu message updates are expensive (one message per API call), so we buffer
    chunks and flush when a tool call arrives or after a short idle period.
    Tracks `sent_something` so the caller knows whether to skip the final response.
    """

    def __init__(self, chat_id: str, message_id: str, send_fn, flush_timeout: float = 1.5):
        self.chat_id = chat_id
        self._message_id = message_id
        self._send = send_fn
        self._flush_timeout = flush_timeout
        self._buffer = ""
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task | None = None
        self.sent_something = False  # True once any text has been flushed

    async def add_text(self, text: str) -> None:
        """Append text chunk and (re)start the flush timer."""
        if not text:
            return
        async with self._lock:
            self._buffer += text
            if self._timer_task:
                self._timer_task.cancel()
            self._timer_task = asyncio.create_task(self._flush_after(self._flush_timeout))

    async def flush(self) -> None:
        """Send accumulated text to Feishu immediately."""
        async with self._lock:
            if self._timer_task:
                self._timer_task.cancel()
                self._timer_task = None
            if self._buffer:
                text = self._buffer
                self._buffer = ""
                if text.strip():
                    await self._send(self.chat_id, self._message_id, text)
                    self.sent_something = True

    async def _flush_after(self, delay: float) -> None:
        """Flush after a delay, but cancel if more text arrives."""
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                if self._buffer:
                    text = self._buffer
                    self._buffer = ""
                    if text.strip():
                        await self._send(self.chat_id, self._message_id, text)
                        self.sent_something = True
        except asyncio.CancelledError:
            pass


class MessageHandler:
    def __init__(
        self,
        feishu_client: FeishuClient,
        authenticator: Authenticator,
        validator: SecurityValidator,
        claude: ClaudeIntegration,
        session_manager: SessionManager,
        formatter: ReplyFormatter,
        approved_directory: str,
        data_dir: str = "",
    ):
        self.feishu = feishu_client
        self.auth = authenticator
        self.validator = validator
        self.claude = claude
        self.sessions = session_manager
        self.formatter = formatter
        self.approved_directory = approved_directory
        self.data_dir = data_dir
        self._queue: asyncio.Queue[IncomingMessage] | None = None
        self._queue_loop_id: int | None = None
        self._worker_task: asyncio.Task | None = None
        self._is_processing: bool = False  # True while worker is running or about to run
        self._current_message_id: str = ""

    def _get_queue(self) -> asyncio.Queue[IncomingMessage]:
        """Lazily create (or recreate) the queue in the current event loop.

        If the event loop has changed since the queue was created (e.g., after
        tests switch loops), discard the stale queue and create a fresh one.
        """
        try:
            current_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            current_loop_id = None
        if self._queue is None or self._queue_loop_id != current_loop_id:
            self._queue = asyncio.Queue()
            self._queue_loop_id = current_loop_id
        return self._queue

    async def handle(self, message: IncomingMessage) -> HandlerResult:
        """将消息入队，立即返回。由 Worker 串行处理。

        注意：所有命令（/开头）都不入队，直接处理以确保立即响应。
        """
        # Commands are handled immediately — do not queue
        if message.content.startswith("/") and _is_command(message.content):
            # Authenticate first
            auth_result = self.auth.authenticate(message.user_open_id)
            if not auth_result.authorized:
                logger.info(f"Ignoring command from unauthorized user: {message.user_open_id}")
                return HandlerResult(success=True)
            result = await self._handle_command(message)
            if result.response_text:
                await self._safe_send(message.chat_id, message.message_id, result.response_text)
            return HandlerResult(success=True)

        queue = self._get_queue()
        await queue.put(message)
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
            # Set _is_processing immediately (before the coroutine even runs) so that
            # a concurrent /stop command sees it as True and can interrupt correctly.
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon(lambda: setattr(self, "_is_processing", True))
            except RuntimeError:
                pass
        return HandlerResult(success=True)

    async def _worker_loop(self) -> None:
        """串行出队并处理消息。"""
        try:
            while True:
                try:
                    queue = self._get_queue()
                    message = await queue.get()
                    try:
                        self._current_message_id = message.message_id
                        await self._process_message(message)
                    finally:
                        self._current_message_id = ""
                        queue.task_done()
                except asyncio.CancelledError:
                    break
                except RuntimeError as e:
                    # Queue bound to a different event loop (e.g., after test teardown) — exit silently.
                    # Only swallow the specific queue/loop errors; re-raise everything else.
                    err_msg = str(e)
                    if "different event loop" in err_msg or "Event loop is closed" in err_msg:
                        break
                    raise  # re-raise unknown RuntimeError
                except Exception:
                    logger.exception("Worker loop error")
        finally:
            self._is_processing = False

    async def _process_message(self, message: IncomingMessage) -> None:
        """处理单条消息：鉴权 → 媒体预处理 → 引用检测 → 查询。"""
        auth_result = self.auth.authenticate(message.user_open_id)
        if not auth_result.authorized:
            logger.info(f"Ignoring message from unauthorized user: {message.user_open_id}")
            return

        if message.message_type not in ("text", "image", "file"):
            await self._safe_send(message.chat_id, message.message_id, "暂不支持该消息类型，请发送文字消息。")
            return

        # Only validate text content — media messages (image/file) have empty
        # content at this stage and will get their path-injected content in _run_query.
        # NOTE: SecurityValidator pattern checks are currently disabled.
        # To re-enable: uncomment the block below.
        # if message.message_type == "text":
        #     ok, err = self.validator.validate(message.content)
        #     if not ok:
        #         await self._safe_send(message.chat_id, message.message_id, f"⚠️ {err}")
        #         return

        session = self.sessions.get_active_session(message.user_open_id)
        sdk_session_id = session.sdk_session_id if session else None
        if session and session.chat_id != message.chat_id:
            self.sessions.update_chat_id(message.user_open_id, message.chat_id)

        await self._run_query(message, session, sdk_session_id)

    async def _handle_command(self, message: IncomingMessage) -> HandlerResult:
        """Handle slash commands like /new, /status."""
        parts = message.content.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/new":
            session = self.sessions.create_session(
                message.user_open_id,
                self.approved_directory,
            )
            return HandlerResult(
                success=True,
                response_text=f"✅ 新会话已创建\n会话ID: {session.session_id}\n工作目录: {session.project_path}",
            )

        elif cmd == "/status":
            session = self.sessions.get_active_session(message.user_open_id)
            if not session:
                return HandlerResult(
                    success=True,
                    response_text="暂无活跃会话",
                )
            return HandlerResult(
                success=True,
                response_text=(
                    f"📊 会话状态\n"
                    f"会话ID: {session.session_id}\n"
                    f"消息数: {session.message_count}\n"
                    f"累计费用: ${session.total_cost:.4f}\n"
                    f"工作目录: {session.project_path}"
                ),
            )

        elif cmd == "/stop":
            return await self._handle_stop(message)

        elif cmd == "/help":
            return HandlerResult(
                success=True,
                response_text=(
                    "cc-feishu-bridge 命令：\n"
                    "• /new — 新建会话\n"
                    "• /status — 会话状态\n"
                    "• /stop — 打断当前查询\n"
                    "• /git — 显示 Git 状态\n"
                    "• /help — 显示本帮助"
                ),
            )

        elif cmd == "/git":
            return await self._handle_git(message)

        else:
            return HandlerResult(
                success=True,
                response_text=f"未知命令: {cmd}",
            )

    async def _run_query(
        self,
        message: IncomingMessage,
        session,
        sdk_session_id: str | None,
    ) -> None:
        """Run Claude query in background, send results to Feishu on completion."""
        reaction_id = None
        try:
            # Add typing reaction
            reaction_id = await self.feishu.add_typing_reaction(message.message_id)
            logger.info(f"[typing] on — user={message.user_open_id}, reaction_id={reaction_id!r}")

            # Audio is not yet supported — tell the user and skip Claude
            if message.message_type == "audio":
                await self._safe_send(message.chat_id, message.message_id, "🎙️ 暂不支持语音消息，请发送文字消息。")
                return

            # Preprocess media (image/file) before querying Claude
            media_prompt_prefix = ""
            media_notify_text = ""
            logger.debug(f"[_run_query] message_type={message.message_type!r}")
            if message.message_type in ("image", "file"):
                logger.debug(f"[_run_query] entering media branch for {message.message_type}")
                try:
                    media_prompt_prefix = await self._preprocess_media(message)
                    if media_prompt_prefix:
                        logger.info(f"Inbound media saved: {media_prompt_prefix}")
                        # Notify user in Feishu that media was received
                        icon = {"image": "🖼️", "file": "📎"}.get(message.message_type, "📎")
                        media_notify_text = f"{icon} 收到 {message.message_type}，正在分析..."
                        await self._safe_send(message.chat_id, message.message_id, media_notify_text)
                except Exception as e:
                    logger.warning(f"Failed to process inbound media: {e}")
                    media_prompt_prefix = ""

            # Resolve quoted message content
            quoted_content = ""
            if message.parent_id:
                try:
                    quoted_msg = await self.feishu.get_message(message.parent_id)
                    if quoted_msg:
                        sender_id = quoted_msg.get("sender_id", "")
                        quoted_text = self._extract_quoted_content(quoted_msg)
                        # Skip only if the user is quoting their OWN message (to avoid
                        # a user quoting themselves → bot sees it → bot replies → user
                        # quoting bot → loop). We do want to pass along quoted bot
                        # messages so the user can get contextual responses.
                        if sender_id == message.user_open_id:
                            quoted_content = ""  # User quoting themselves — skip
                        else:
                            quoted_content = f"[引用消息: {message.parent_id}] {quoted_text}"
                        logger.info(f"Quoted message {message.parent_id}: {quoted_text[:100]!r}")
                    else:
                        # get_message returned None — message not found/deleted
                        quoted_content = f"[引用消息不可用: {message.parent_id}]"
                        logger.warning(f"Quoted message {message.parent_id} not found")
                except Exception:
                    # Network/auth error — tell the user so they're not confused
                    quoted_content = f"[引用消息不可用: {message.parent_id}]"
                    logger.warning(f"Failed to fetch quoted message {message.parent_id}")

            # Accumulator sends text chunks to Feishu in real-time (with buffering).
            # Tool calls flush text immediately, then are sent separately.
            # After streaming, if text was sent during stream, skip the final response
            # to avoid duplication — the streamed content is already there.
            accumulator = StreamAccumulator(message.chat_id, message.message_id, self._safe_send)

            async def stream_callback(claude_msg):
                if claude_msg.tool_name:
                    await accumulator.flush()
                    result = self.formatter.format_tool_call(
                        claude_msg.tool_name,
                        claude_msg.tool_input,
                    )
                    logger.info(f"[stream] tool: {claude_msg.tool_name} | input: {claude_msg.tool_input}")

                    # _DiffMarker / list[_DiffMarker] → 彩色卡片；其他 → backtick 格式
                    if isinstance(result, _DiffMarker):
                        for card in result.card if isinstance(result.card, list) else [result.card]:
                            try:
                                await self.feishu.send_edit_diff_card(
                                    message.chat_id, card, message.message_id, log_reply=False
                                )
                            except Exception:
                                # 卡片发送失败，降级为带图标的纯文本
                                import json
                                try:
                                    data = json.loads(result.tool_input)
                                    file_path = data.get("file_path", "unknown")
                                    icon = "✏️" if result.tool_name == "Edit" else "📝"
                                    fallback = f"{icon} **{result.tool_name}** — `{file_path}`"
                                except Exception:
                                    fallback = f"🤖 **{result.tool_name}**\n`{result.tool_input[:500]}`"
                                logger.warning(f"send_edit_diff_card failed, falling back to: {fallback}")
                                await self._safe_send(message.chat_id, message.message_id, fallback, log_reply=False)
                    elif isinstance(result, list):
                        for marker in result:
                            if isinstance(marker, _DiffMarker):
                                for card in marker.card if isinstance(marker.card, list) else [marker.card]:
                                    try:
                                        await self.feishu.send_edit_diff_card(
                                            message.chat_id, card, message.message_id, log_reply=False
                                        )
                                    except Exception:
                                        import json
                                        try:
                                            data = json.loads(marker.tool_input)
                                            file_path = data.get("file_path", "unknown")
                                            icon = "✏️" if marker.tool_name == "Edit" else "📝"
                                            fallback = f"{icon} **{marker.tool_name}** — `{file_path}`"
                                        except Exception:
                                            fallback = f"🤖 **{marker.tool_name}**\n`{marker.tool_input[:500]}`"
                                        logger.warning(f"send_edit_diff_card failed, falling back to: {fallback}")
                                        await self._safe_send(message.chat_id, marker.message_id, fallback, log_reply=False)
                    else:
                        await self._safe_send(message.chat_id, message.message_id, result, log_reply=False)
                elif claude_msg.content:
                    logger.info(f"[stream] text: {claude_msg.content[:100]}")
                    await accumulator.add_text(claude_msg.content)

            prefix_parts = [p for p in [media_prompt_prefix, quoted_content] if p]
            prefix = "\n".join(prefix_parts) + "\n" if prefix_parts else ""
            # For text messages: prepend prefix to actual text content.
            # For media messages (image/file): message.content may contain user text
            # (mixed image+text case). Use media prefix + user text.
            is_media = message.message_type in ("image", "file")
            if is_media and media_prompt_prefix:
                # Media messages: prepend prefix to any user text
                user_text = message.content.strip()
                if user_text:
                    full_prompt = (prefix + user_text).strip()
                else:
                    full_prompt = prefix.strip()
            else:
                # Text messages: prepend prefix to actual text content
                full_prompt = (prefix + message.content).strip()
            response, new_session_id, cost = await self.claude.query(
                prompt=full_prompt,
                session_id=sdk_session_id,
                cwd=session.project_path if session else self.approved_directory,
                on_stream=stream_callback,
            )

            # Flush any remaining buffered text
            await accumulator.flush()

            # Save session
            if not session:
                session = self.sessions.create_session(
                    message.user_open_id,
                    self.approved_directory,
                    sdk_session_id=new_session_id,
                )
            else:
                self.sessions.update_session(session.session_id, cost=cost, message_increment=1)
                # Update SDK session ID if Claude returned a new one
                if new_session_id:
                    self.sessions.update_sdk_session_id(session.session_id, new_session_id)

            # Send final text response only if no text was streamed.
            # If text was streamed in real-time, it is already visible in the chat.
            if not accumulator.sent_something:
                formatted = self.formatter.format_text(response)
                chunks = self.formatter.split_messages(formatted)
                for chunk in chunks:
                    await self._safe_send(message.chat_id, message.message_id, chunk)
                # NOTE: "Replied to" log moved inside _safe_send (only fires for non-stream sends).
                # Stream tool calls are already logged by their individual _safe_send calls.

        except asyncio.CancelledError:
            await self._safe_send(message.chat_id, message.message_id, "🛑 已打断 Claude。")
        except Exception as e:
            logger.exception(f"Error in _run_query: {e}")
            await self._safe_send(message.chat_id, message.message_id, f"⚠️ 内部错误：{e}")
        finally:
            if reaction_id:
                logger.info(f"[typing] off — user={message.user_open_id}, reaction_id={reaction_id!r}")
                await self.feishu.remove_typing_reaction(message.message_id, reaction_id)

    async def _handle_stop(self, message: IncomingMessage) -> HandlerResult:
        """Handle /stop — cancel the current worker task and interrupt Claude."""
        if not self._is_processing:
            await self._safe_send(message.chat_id, message.message_id, "当前没有正在运行的查询。")
            return HandlerResult(success=True)
        await self.claude.interrupt_current()
        self._worker_task.cancel()
        self._worker_task = None
        await self._safe_send(message.chat_id, message.message_id, "🛑 已发送停止信号，Claude 将中断当前任务。")
        return HandlerResult(success=True)

    async def _handle_git(self, message: IncomingMessage) -> HandlerResult:
        """执行 git status 和 log，返回精美卡片。"""
        import subprocess

        def run_git(args: list[str], cwd: str | None = None) -> str:
            try:
                result = subprocess.run(
                    ["git"] + args,
                    capture_output=True, text=True, timeout=10,
                    cwd=cwd or os.getcwd()
                )
                return result.stdout.strip()
            except Exception:
                return ""

        # 当前分支
        branch = run_git(["branch", "--show-current"])
        if not branch:
            branch = "(无分支)"

        # 变更文件
        status_output = run_git(["status", "--porcelain"])

        # 最近 5 次提交: ISO时间 + hash(7位) + 描述
        # %cI = ISO 8601，无空格，split 不易错位
        log_lines = run_git(["log", "--format=%cI %h %s", "-5"]).splitlines()

        # emoji 状态映射（font 标签在卡片内不稳定，改用 emoji）
        status_icon = {
            "M": "📝", "D": "🗑️", "A": "➕",
            "R": "📛", "U": "⚠️", "?": "❓",
        }

        # 构建单条 markdown 内容
        card_lines = [
            f"📊 **Git Status - {branch}**",
            "",
            "📝 **变更文件**",
        ]

        if status_output:
            for line in status_output.splitlines():
                idx_char = line[0]
                wt_char = line[1]
                if idx_char == "?":
                    char = "?"
                elif idx_char == " ":
                    char = wt_char if wt_char != " " else "?"
                else:
                    char = idx_char
                icon = status_icon.get(char, "•")
                card_lines.append(f"{icon}  {line[3:]}")

            card_lines.extend([
                "",
                "📋 **最近提交**",
                "",
                "| 时间 | Hash | 描述 |",
                "|------|------|------|",
            ])
            for log_line in log_lines:
                # %cI: "2026-04-04T12:00:00+08:00 hash desc"
                parts = log_line.split(" ", 2)
                if len(parts) >= 3:
                    dt_clean = parts[0].replace("T", " ")[:16]
                    h = parts[1]
                    msg = parts[2]
                    card_lines.append(f"| {dt_clean} | `{h}` | {msg} |")
        else:
            card_lines.append("✅ **工作区干净，无待提交变更**")

        card_body = "\n".join(card_lines)
        try:
            await self.feishu.send_interactive_reply(
                message.chat_id, card_body, message.message_id, log_reply=True
            )
        except Exception:
            await self._safe_send(message.chat_id, message.message_id, card_body)

        return HandlerResult(success=True)

    async def _safe_send(self, chat_id: str, reply_to_message_id: str, text: str, log_reply: bool = True):
        """Send a markdown message as a threaded Feishu post/card, ignoring errors.

        Uses Interactive Card for content with fenced code blocks or tables,
        falls back to rich text post for plain markdown.
        """
        try:
            # Optimize and decide format
            formatted = self.formatter.format_text(text)
            if not formatted.strip():
                return
            if self.formatter.should_use_card(formatted):
                await self.feishu.send_interactive_reply(chat_id, formatted, reply_to_message_id, log_reply=log_reply)
            else:
                await self.feishu.send_post_reply(chat_id, formatted, reply_to_message_id, log_reply=log_reply)
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")

    def _extract_quoted_content(self, message: dict) -> str:
        """Extract text content from a fetched message dict."""
        msg_type = message.get("msg_type", "")
        content_str = message.get("content", "{}")
        try:
            content = json.loads(content_str)
            if msg_type == "text":
                return content.get("text", "")
            elif msg_type == "post":
                return content.get("text", "")
        except Exception:
            pass
        return str(content_str)

    async def _preprocess_media(self, message: IncomingMessage) -> str:
        """Download and save inbound media, return the text to prepend to prompt.

        Returns:
            空字符串（无媒体），或形如 "![image](path)" / "[File: path]" 等格式的文本片段。
            图片用 markdown image 语法以便 SDK 的 detectAndLoadPromptImages 识别；
            文件/音频用 [File: /path] / [Audio: /path] 格式告知 AI 附件内容，
            AI 会通过 Read 工具读取本地文件。
        """
        from cc_feishu_bridge.feishu.media import (
            make_image_path,
            make_file_path,
            save_bytes,
        )

        if message.message_type not in ("image", "file"):
            return ""

        msg_id = message.message_id
        logger.info(f"[media] preprocessing {message.message_type} message {msg_id}")

        # Use get_message API to get reliable content (WS event content may be
        # missing image_key for image messages — API always returns it correctly).
        msg_data = await self.feishu.get_message(msg_id)
        if not msg_data:
            logger.warning(f"[media] failed to fetch message {msg_id}")
            return ""
        content_str = msg_data.get("content", "{}")
        logger.debug(f"[media] got content: {content_str[:200]!r}")

        try:
            content = json.loads(content_str)
        except Exception:
            logger.warning(f"[media] json.loads failed on {content_str!r}")
            return ""

        data_dir = self.data_dir or os.getcwd()

        def _find_first_image_key(parsed: dict) -> str | None:
            """Find first image_key in simple or rich post content format."""
            # Simple: {"image_key": "..."}
            if "image_key" in parsed:
                return parsed.get("image_key")
            # Rich post: {"content": [[{"tag": "img", "image_key": "..."}]]}
            for block in parsed.get("content", []):
                if not isinstance(block, list):
                    continue
                for item in block:
                    if isinstance(item, dict) and item.get("tag") == "img":
                        return item.get("image_key")
            return None

        if message.message_type == "image":
            file_key = _find_first_image_key(content)
            if not file_key:
                logger.warning(f"[media] no image_key in message {msg_id}")
                return ""
            logger.info(f"[media] downloading image, key={file_key}")
            base_path = make_image_path(data_dir, msg_id)
            data = await self.feishu.download_media(msg_id, file_key, msg_type="image")
            save_path = base_path + ".png"
            save_bytes(save_path, data)
            logger.info(f"[media] saved image to {save_path}")
            # Use standard markdown image syntax so Claude CLI's detectAndLoadPromptImages
            # recognizes the local path. The SDK scans for "![alt](path)" with an image extension.
            return f"![image]({save_path})"

        elif message.message_type == "file":
            file_key = content.get("file_key", "")
            orig_name = content.get("file_name", "file")
            file_type = content.get("file_type", "bin")
            if not file_key:
                logger.warning(f"[media] no file_key in message {msg_id}")
                return ""
            logger.info(f"[media] downloading file {orig_name}, key={file_key}")
            save_path = make_file_path(data_dir, msg_id, orig_name, file_type)
            data = await self.feishu.download_media(msg_id, file_key, msg_type="file")
            save_bytes(save_path, data)
            logger.info(f"[media] saved file to {save_path}")
            # [File: /path] 告知 AI 收到了文件，AI 会用 Read 工具读取。
            # 包含原始文件名方便 AI 判断文件类型和内容。
            return f"[File: {save_path}] ({orig_name})"

        return ""

