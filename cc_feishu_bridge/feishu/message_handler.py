"""Message handler orchestrator — routes messages to Claude and back."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from cc_feishu_bridge.feishu.client import FeishuClient, IncomingMessage
from cc_feishu_bridge.security.auth import Authenticator
from cc_feishu_bridge.security.validator import SecurityValidator
from cc_feishu_bridge.claude.integration import ClaudeIntegration
from cc_feishu_bridge.claude.session_manager import SessionManager
from cc_feishu_bridge.format.reply_formatter import ReplyFormatter

logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    success: bool
    response_text: str | None = None
    error: str | None = None


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

    async def handle(self, message: IncomingMessage) -> HandlerResult:
        """Main entry point for processing an incoming message."""
        # 1. Auth check
        auth_result = self.auth.authenticate(message.user_open_id)
        if not auth_result.authorized:
            logger.info(f"Ignoring message from unauthorized user: {message.user_open_id}")
            return HandlerResult(success=True, response_text=None)  # Silently ignore

        # 2. Handle commands
        if message.content.startswith("/"):
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

        # 5. Add typing reaction to user's message (Feishu has no dedicated typing API;
        # the official plugin uses a 'Typing' emoji reaction instead)
        reaction_id = await self.feishu.add_typing_reaction(message.message_id)

        # 6. Preprocess media (image/file) before querying Claude
        media_prompt_prefix = ""
        if message.message_type in ("image", "file"):
            try:
                media_prompt_prefix = await self._preprocess_media(message)
                if media_prompt_prefix:
                    logger.info(f"Inbound media saved: {media_prompt_prefix}")
            except Exception as e:
                logger.warning(f"Failed to process inbound media: {e}")
                media_prompt_prefix = ""

        # 7. Call Claude
        try:
            # During streaming, tool calls are sent immediately to Feishu so the user
            # sees what's happening. Text chunks are logged only (not sent) — the
            # final formatted response covers them all after streaming completes.
            async def stream_callback(claude_msg):
                if claude_msg.tool_name:
                    tool_text = self.formatter.format_tool_call(
                        claude_msg.tool_name,
                        claude_msg.tool_input,
                    )
                    logger.info(f"[stream] tool: {claude_msg.tool_name}")
                    await self._safe_send(message.chat_id, tool_text)
                elif claude_msg.content:
                    logger.info(f"[stream] text: {claude_msg.content[:100]}")

            # 8. Save session
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

            # 10. Format and send text response
            formatted = self.formatter.format_text(response)
            chunks = self.formatter.split_messages(formatted)
            for chunk in chunks:
                await self._safe_send(message.chat_id, chunk)

            logger.info(f"Replied to {message.user_open_id} in chat {message.chat_id} | reply: {response[:300]}")
            return HandlerResult(success=True)

        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            return HandlerResult(success=False, error=str(e))

        finally:
            # Always remove the typing reaction when done (success or error)
            if reaction_id:
                await self.feishu.remove_typing_reaction(message.message_id, reaction_id)

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

        else:
            return HandlerResult(
                success=True,
                response_text=f"未知命令: {cmd}",
            )

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
