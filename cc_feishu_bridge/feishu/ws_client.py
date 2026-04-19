"""Feishu WebSocket long-connection client using lark-oapi ws.Client."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable
from unittest.mock import MagicMock

import lark_oapi as lark

from cc_feishu_bridge.feishu.client import IncomingMessage

logger = logging.getLogger(__name__)


def _detect_media_type_from_content(parsed: dict) -> str | None:
    """Detect media type from parsed JSON content.

    Handles four Feishu content formats:
      1. Simple media: {"image_key": "..."} or {"file_key": "...", "duration": ...}
      2. Rich post (media+text): {"content": [[{"tag": "img/file/audio", ...}], [{"tag": "text", ...}]]}
      3. Standalone rich post file: {"content": [[{"tag": "file", "file_key": "..."}]]}
      4. Simple text: {"text": "..."}
    """
    # Format 1: simple {"image_key": ...} or {"file_key": ...}
    if "image_key" in parsed:
        return "image"
    if "file_key" in parsed:
        if "duration" in parsed:
            return "audio"
        return "file"

    # Format 2 & 3: rich post with [[{tag: "img", ...}], [{tag: "text", ...}]]
    content = parsed.get("content", [])
    if not isinstance(content, list):
        return None

    for block in content:
        if not isinstance(block, list):
            continue
        for item in block:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag", "")
            if tag == "img" and "image_key" in item:
                return "image"
            if tag == "audio" and "file_key" in item:
                return "audio"
            if tag == "file" and "file_key" in item:
                return "file"

    return None


def _extract_text_from_content(parsed: dict) -> str:
    """Extract user text from parsed JSON content.

    Handles three Feishu content formats:
      1. Simple text: {"text": "..."}
      2. Rich post: {"content": [[{"tag": "img", ...}], [{"tag": "text", "text": "..."}]]}
      3. Empty / media-only
    """
    # Format 1: simple {"text": "..."}
    if "text" in parsed:
        return parsed.get("text", "")

    # Format 2: rich post with tag="text" nodes
    content = parsed.get("content", [])
    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if not isinstance(block, list):
            continue
        for item in block:
            if not isinstance(item, dict):
                continue
            if item.get("tag") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)

    return " ".join(parts)

MessageCallback = Callable[[IncomingMessage], Awaitable[None]]


class FeishuWSClient:
    """Manages WebSocket connection to Feishu via lark-oapi ws.Client."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "Claude",
        bot_open_id: str = "",
        domain: str = "feishu",
        on_message: MessageCallback | None = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self.bot_open_id = bot_open_id
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
                        parsed = json.loads(content_str)
                        # Determine effective message type from rich post or simple media JSON
                        effective_type = _detect_media_type_from_content(parsed)
                        if effective_type:
                            msg_type = effective_type
                        # Extract text content
                        content = _extract_text_from_content(parsed)
                    except Exception:
                        pass

                logger.debug(
                    f"Raw message — type={msg_type!r}, message_id={getattr(message, 'message_id', '')!r}, "
                    f"parent_id={getattr(message, 'parent_id', '')!r}, root_id={getattr(message, 'root_id', '')!r}, "
                    f"content={content_str!r}"
                )

                sender_id = getattr(sender, "sender_id", None)
                user_open_id = ""
                if sender_id is not None:
                    user_open_id = getattr(sender_id, "open_id", "")

                # Extract chat_type: 'p2p' or 'group' (from official plugin)
                chat_type = str(getattr(message, "chat_type", "p2p") or "p2p")
                is_group_chat = chat_type == "group"

                # Extract mentions[] to determine if bot was @mentioned
                # Each mention: { key: "@_user_1", id: { open_id: "ou_xxx", ... }, name: "Alice" }
                mention_ids: list[str] = []
                mention_bot = False
                mentions = getattr(message, "mentions", None)
                if mentions:
                    for m in mentions:
                        mid = getattr(m, "id", None)
                        if mid is not None:
                            open_id = getattr(mid, "open_id", "") or ""
                            if open_id:
                                mention_ids.append(open_id)
                                if open_id == self.bot_open_id:
                                    mention_bot = True

                incoming = IncomingMessage(
                    message_id=getattr(message, "message_id", ""),
                    chat_id=getattr(message, "chat_id", ""),
                    user_open_id=user_open_id,
                    content=content,
                    message_type=msg_type,
                    create_time=getattr(message, "create_time", ""),
                    parent_id=getattr(message, "parent_id", ""),
                    thread_id=getattr(message, "thread_id", ""),
                    raw_content=content_str,
                    is_group_chat=is_group_chat,
                    chat_type=chat_type,
                    mention_bot=mention_bot,
                    mention_ids=mention_ids,
                    group_name=str(getattr(message, "chat_name", "") or ""),
                )
                logger.info(f"Received message from {user_open_id}: type={msg_type!r} parent_id={getattr(message, 'parent_id', '')!r} raw_content={content_str!r}")
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
