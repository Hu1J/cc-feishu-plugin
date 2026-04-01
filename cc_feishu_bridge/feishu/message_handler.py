"""Message handler orchestrator — routes messages to Claude and back."""
from __future__ import annotations

import asyncio
import logging
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
    ):
        self.feishu = feishu_client
        self.auth = authenticator
        self.validator = validator
        self.claude = claude
        self.sessions = session_manager
        self.formatter = formatter
        self.approved_directory = approved_directory

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

        # 5. Add typing reaction to user's message (Feishu has no dedicated typing API;
        # the official plugin uses a 'Typing' emoji reaction instead)
        reaction_id = await self.feishu.add_typing_reaction(message.message_id)

        # 6. Call Claude
        try:
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

            response, new_session_id, cost = await self.claude.query(
                prompt=message.content,
                session_id=sdk_session_id,
                cwd=session.project_path if session else self.approved_directory,
                on_stream=stream_callback,
            )

            # 7. Save session
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

            # 8. Format and send response
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
