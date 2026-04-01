"""Feishu/Lark Open Platform client for receiving and sending messages."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    """Parsed incoming message from Feishu."""
    message_id: str
    chat_id: str
    user_open_id: str
    content: str          # text content
    message_type: str     # "text", "image", "file", etc.
    create_time: str


class FeishuClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "Claude",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import lark_oapi as lark
            self._client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.INFO)
                .build()
            )
        return self._client

    async def send_text(self, chat_id: str, text: str) -> str:
        """Send a text message to a chat. Returns message_id."""
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(lark.NewHexText({"text": text}).to_json())
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(
            client.im.v1.message.create,
            request,
        )
        if not response.success():
            raise RuntimeError(f"Failed to send message: {response.msg}")
        return response.data.message_id

    async def send_typing(self, chat_id: str) -> str:
        """Send a typing indicator to a chat. Returns message_id."""
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(lark.NewHexText({"text": "", "type": "typing"}).to_json())
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(
            client.im.v1.message.create,
            request,
        )
        if not response.success():
            raise RuntimeError(f"Failed to send typing: {response.msg}")
        return response.data.message_id

    def parse_incoming_message(self, body: dict) -> IncomingMessage | None:
        """Parse webhook payload into IncomingMessage."""
        try:
            event = body.get("event", {})
            if not event:
                return None

            message = event.get("message", {})
            sender = event.get("sender", {})

            return IncomingMessage(
                message_id=message.get("message_id", ""),
                chat_id=message.get("chat_id", ""),
                user_open_id=sender.get("sender_id", {}).get("open_id", ""),
                content=self._extract_content(message),
                message_type=message.get("msg_type", "text"),
                create_time=message.get("create_time", ""),
            )
        except Exception as e:
            logger.error(f"Failed to parse incoming message: {e}")
            return None

    def _extract_content(self, message: dict) -> str:
        """Extract text content from message."""
        msg_type = message.get("msg_type", "")
        content_str = message.get("content", "{}")
        try:
            import json
            content = json.loads(content_str)
            if msg_type == "text":
                return content.get("text", "")
            elif msg_type == "post":
                return content.get("text", "")
            return str(content)
        except Exception:
            return content_str
