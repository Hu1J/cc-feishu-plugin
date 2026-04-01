"""Feishu WebSocket long-connection client using lark-oapi ws.Client."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable
from unittest.mock import MagicMock

import lark_oapi as lark

from src.feishu.client import IncomingMessage

logger = logging.getLogger(__name__)

MessageCallback = Callable[[IncomingMessage], Awaitable[None]]


class FeishuWSClient:
    """Manages WebSocket connection to Feishu via lark-oapi ws.Client."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "Claude",
        domain: str = "feishu",
        on_message: MessageCallback | None = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self.domain = domain
        self._on_message = on_message
        self._ws_client = None
        self._handler = None

    def _build_event_handler(self):
        """Build EventDispatcherHandler with p2p message callback registered."""
        builder = lark.EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token="",
        )

        def wrapped_handler(event):
            """Handle incoming p2p message event."""
            if self._on_message is None:
                return
            try:
                event_data = event.event
                message = event_data.message
                sender = event_data.sender
                msg_type = getattr(message, "msg_type", "text")
                content_str = getattr(message, "content", "{}")

                # Parse JSON content for text messages
                content = content_str
                if msg_type == "text":
                    try:
                        content = json.loads(content_str).get("text", "")
                    except Exception:
                        pass

                sender_id = getattr(sender, "sender_id", None)
                user_open_id = ""
                if sender_id is not None:
                    user_open_id = getattr(sender_id, "open_id", "")

                incoming = IncomingMessage(
                    message_id=getattr(message, "message_id", ""),
                    chat_id=getattr(message, "chat_id", ""),
                    user_open_id=user_open_id,
                    content=content,
                    message_type=msg_type,
                    create_time=getattr(message, "create_time", ""),
                )
                logger.info(f"Received message from {user_open_id}: {content!r}")
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No running loop (e.g., in tests) — run in a new loop
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self._on_message(incoming))
                    loop.close()
                    return
                asyncio.ensure_future(self._on_message(incoming))
            except Exception as e:
                logger.exception(f"Error handling Feishu message: {e}")

        builder.register_p2_im_message_receive_v1(wrapped_handler)

        # Register no-op handlers for reaction events (bot adding/removing emoji reactions).
        # These events come back from Feishu but we don't need to act on them.
        def noop_handler(event):
            pass

        builder.register_p2_im_message_reaction_created_v1(noop_handler)
        builder.register_p2_im_message_reaction_deleted_v1(noop_handler)

        self._handler = builder.build()
        return self._handler

    def start(self) -> None:
        """Start the WebSocket long connection (blocking)."""
        if self._ws_client is not None:
            return

        self._handler = self._build_event_handler()
        base_url = "https://open.feishu.cn" if self.domain == "feishu" else "https://open.larksuite.com"

        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            log_level=lark.LogLevel.INFO,
            event_handler=self._handler,
            domain=base_url,
            auto_reconnect=True,
        )
        logger.info(f"Starting Feishu WebSocket connection to {base_url}...")
        self._ws_client.start()

    # Expose handler for testing
    def _handle_p2p_message(self, event):
        """Internal handler for testing — calls the wrapped handler directly."""
        handler = self._build_event_handler()
        handler._processorMap.get("p2.im.message.receive_v1").f(event)
