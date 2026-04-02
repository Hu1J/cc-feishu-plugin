"""Message handler orchestrator — routes messages to Claude and back."""
from __future__ import annotations

import asyncio
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

    def __init__(self, chat_id: str, send_fn, flush_timeout: float = 1.5):
        self.chat_id = chat_id
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
                    await self._send(self.chat_id, text)
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
                        await self._send(self.chat_id, text)
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
        self._active_task: asyncio.Task | None = None
        self._active_user_id: str | None = None

    async def handle(self, message: IncomingMessage) -> HandlerResult:
        """Main entry point for processing an incoming message."""
        # 1. Auth check
        auth_result = self.auth.authenticate(message.user_open_id)
        if not auth_result.authorized:
            logger.info(f"Ignoring message from unauthorized user: {message.user_open_id}")
            return HandlerResult(success=True, response_text=None)  # Silently ignore

        # 2. Handle commands — but not Unix paths that start with /
        # Commands look like "/stop", "/new", "/feishu auth" — NOT "/Users/..." or "/tmp/..."
        if message.content.startswith("/") and _is_command(message.content):
            return await self._handle_command(message)

        # Handle non-text, non-media message types (audio, etc.)
        if message.message_type not in ("text", "image", "file"):
            return HandlerResult(
                success=True,
                response_text="暂不支持该消息类型，请发送文字消息。",
            )

        # 3. Input validation
        ok, err = self.validator.validate(message.content)
        if not ok:
            return HandlerResult(
                success=False,
                response_text=f"⚠️ {err}",
            )

        # 4. Get or create session
        session = self.sessions.get_active_session(message.user_open_id)
        # Use SDK's session ID if available, so Claude can maintain context
        sdk_session_id = session.sdk_session_id if session else None

        # Update chat_id for this user (so send command knows where to reply)
        if session and session.chat_id != message.chat_id:
            self.sessions.update_chat_id(message.user_open_id, message.chat_id)

        # 5. Re-entrant check: if Claude is already running for this user, ignore
        if self._active_task is not None and self._active_user_id == message.user_open_id:
            await self._safe_send(message.chat_id, "⏳ Claude 正在回复中，请稍候...")
            return HandlerResult(success=True)

        # 6. Kick off query as background task and return immediately
        self._active_task = asyncio.create_task(self._run_query(message, session, sdk_session_id))
        self._active_user_id = message.user_open_id
        return HandlerResult(success=True)

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

        elif cmd == "/feishu" and arg.startswith("auth"):
            return await self._handle_feishu_auth(message)
        elif cmd == "/feishu":
            return HandlerResult(
                success=True,
                response_text=(
                    "cc-feishu-bridge 命令：\n"
                    "• /new — 新建会话\n"
                    "• /status — 会话状态\n"
                    "• /stop — 打断当前查询\n"
                    "• /feishu auth — 授权机器人权限（如文件上传）"
                ),
            )

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

            # Preprocess media (image/file) before querying Claude
            media_prompt_prefix = ""
            if message.message_type in ("image", "file"):
                try:
                    media_prompt_prefix = await self._preprocess_media(message)
                    if media_prompt_prefix:
                        logger.info(f"Inbound media saved: {media_prompt_prefix}")
                except Exception as e:
                    logger.warning(f"Failed to process inbound media: {e}")
                    media_prompt_prefix = ""

            # Accumulator sends text chunks to Feishu in real-time (with buffering).
            # Tool calls flush text immediately, then are sent separately.
            # After streaming, if text was sent during stream, skip the final response
            # to avoid duplication — the streamed content is already there.
            accumulator = StreamAccumulator(message.chat_id, self._safe_send)

            async def stream_callback(claude_msg):
                if claude_msg.tool_name:
                    await accumulator.flush()
                    tool_text = self.formatter.format_tool_call(
                        claude_msg.tool_name,
                        claude_msg.tool_input,
                    )
                    logger.info(f"[stream] tool: {claude_msg.tool_name}")
                    await self._safe_send(message.chat_id, tool_text)
                elif claude_msg.content:
                    logger.info(f"[stream] text: {claude_msg.content[:100]}")
                    await accumulator.add_text(claude_msg.content)

            full_prompt = (
                f"{media_prompt_prefix}\n{message.content}".strip()
                if media_prompt_prefix
                else message.content
            )
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
                    await self._safe_send(message.chat_id, chunk)

            logger.info(f"Replied to {message.user_open_id} in chat {message.chat_id} | reply: {response[:300]}")

        except asyncio.CancelledError:
            await self._safe_send(message.chat_id, "🛑 已打断 Claude。")
        except Exception as e:
            logger.exception(f"Error in _run_query: {e}")
        finally:
            self._active_task = None
            self._active_user_id = None
            if reaction_id:
                logger.info(f"[typing] off — user={message.user_open_id}, reaction_id={reaction_id!r}")
                await self.feishu.remove_typing_reaction(message.message_id, reaction_id)

    async def _handle_stop(self, message: IncomingMessage) -> HandlerResult:
        """Handle /stop — interrupt the running Claude query."""
        if self._active_task is None:
            return HandlerResult(success=True, response_text="当前没有正在运行的查询。")
        interrupted = await self.claude.interrupt_current()
        if self._active_task is not None:
            self._active_task.cancel()
            self._active_task = None
        self._active_user_id = None
        await self._safe_send(message.chat_id, "🛑 已发送停止信号，Claude 将中断当前任务。")
        return HandlerResult(success=True)

    async def _safe_send(self, chat_id: str, text: str):
        """Send message, ignoring errors (e.g., rate limits)."""
        try:
            await self.feishu.send_text(chat_id, text)
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")

    async def _preprocess_media(self, message: IncomingMessage) -> str:
        """Download and save inbound media, return the text to prepend to prompt.

        Returns:
            空字符串（无媒体），或形如 "[图片: /path/to/img.png]" 的文本片段。
        """
        from cc_feishu_bridge.feishu.media import (
            make_image_path,
            make_file_path,
            save_bytes,
        )

        if message.message_type not in ("image", "file"):
            return ""

        msg_id = message.message_id
        content_str = message.content

        try:
            import json
            content = json.loads(content_str)
        except Exception:
            return ""

        data_dir = self.data_dir or os.getcwd()

        if message.message_type == "image":
            file_key = content.get("image_key", "")
            if not file_key:
                return ""
            base_path = make_image_path(data_dir, msg_id)
            data = await self.feishu.download_media(msg_id, file_key, msg_type="image")
            # 飞书图片通常是 PNG，写入时直接加 .png
            save_path = base_path + ".png"
            save_bytes(save_path, data)
            return f"[图片: {save_path}]"

        elif message.message_type == "file":
            file_key = content.get("file_key", "")
            orig_name = content.get("file_name", "file")
            file_type = content.get("file_type", "bin")
            if not file_key:
                return ""
            save_path = make_file_path(data_dir, msg_id, orig_name, file_type)
            data = await self.feishu.download_media(msg_id, file_key, msg_type="file")
            save_bytes(save_path, data)
            return f"[文件: {save_path}]"

        return ""

    async def _handle_feishu_auth(self, message: IncomingMessage) -> HandlerResult:
        """Send auth card to user and start background polling."""
        from cc_feishu_bridge.feishu.auth_flow import run_auth_flow
        from cc_feishu_bridge.feishu.token_store import UserTokenStore

        # Check if already authorized
        token_store = UserTokenStore(
            os.path.join(self.data_dir, "user_tokens.yaml")
        )
        existing = token_store.load(message.user_open_id)
        if existing:
            return HandlerResult(
                success=True,
                response_text="✅ 已完成授权，机器人已有上传文件的权限。",
            )

        # Acknowledge immediately
        await self._safe_send(
            message.chat_id,
            "🔐 正在发起授权，请稍候...",
        )

        # Start auth flow in background
        asyncio.create_task(
            run_auth_flow(
                app_id=self.feishu.app_id,
                app_secret=self.feishu.app_secret,
                user_open_id=message.user_open_id,
                chat_id=message.chat_id,
                message_id=message.message_id,
                send_card_fn=self._send_interactive_card,
                update_card_fn=self._update_interactive_card,
                save_token_fn=self._save_user_token,
                scopes=["im:message", "im:file", "im:resource"],
            )
        )
        return HandlerResult(success=True)

    async def _send_interactive_card(self, chat_id: str, card_json: str, reply_to: str) -> None:
        """Send an interactive card replying to the user's auth command message."""
        try:
            await self.feishu.send_interactive(chat_id, card_json, reply_to_message_id=reply_to)
        except Exception as e:
            logger.warning(f"Failed to send auth card: {e}")

    async def _update_interactive_card(self, message_id: str, card_json: str) -> None:
        """Update an existing interactive message with new card content."""
        try:
            await self.feishu.update_message(message_id, card_json)
        except Exception as e:
            logger.warning(f"Failed to update card message {message_id}: {e}")

    async def _save_user_token(self, user_open_id: str, token_data: dict) -> None:
        """Persist user token to disk with expiry time."""
        import datetime
        from cc_feishu_bridge.feishu.token_store import UserTokenStore
        token_store = UserTokenStore(
            os.path.join(self.data_dir, "user_tokens.yaml")
        )
        expires_at = (
            datetime.datetime.utcnow()
            + datetime.timedelta(seconds=token_data.get("expires_in", 7200))
        ).isoformat() + "Z"
        token_store.save(user_open_id, {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": expires_at,
        })
