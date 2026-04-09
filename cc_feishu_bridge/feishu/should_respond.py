"""Determines whether the bot should respond to an incoming message."""
from __future__ import annotations

import json
import logging
from cc_feishu_bridge.feishu.client import IncomingMessage
from cc_feishu_bridge.config import Config

logger = logging.getLogger(__name__)


def should_respond(message: IncomingMessage, config: Config, bot_open_id: str) -> bool:
    """Return True if the bot should respond to this message.

    Logic:
      - P2P: always respond (user explicitly started a conversation with the bot)
      - Group, chat_mode=open: always respond (bot sees all messages)
      - Group, chat_mode=mention: respond only if bot was @mentioned
      - Group, chat_mode=mention + not @mentioned: ignore silently
    """
    if message.chat_type == "p2p":
        return True

    # Group chat — check chat_mode from config
    chat_mode = config.get_chat_mode(message.chat_id)
    if chat_mode == "open":
        return True

    # mention mode: check if bot was @mentioned
    return _is_bot_mentioned(message.raw_content, bot_open_id)


def _is_bot_mentioned(raw_content: str, bot_open_id: str) -> bool:
    """Parse raw_content JSON and check if bot_open_id appears in mentions.

    If bot_open_id is unknown (empty), return True if any mention exists
    in the message — user is clearly trying to talk to the bot.
    """
    if not raw_content:
        return False
    # Guard against maliciously large payloads — Feishu mentions are a few bytes
    if len(raw_content) > 100_000:  # 100 KB hard limit
        logger.warning(f"raw_content exceeds safe size limit ({len(raw_content)} bytes)")
        return False
    try:
        content = json.loads(raw_content)
    except Exception:
        return False

    mentions = content.get("mentions", [])
    if not isinstance(mentions, list):
        return False

    # If bot_open_id is unknown, any mention means the bot was called
    if not bot_open_id:
        return len(mentions) > 0

    for mention in mentions:
        if isinstance(mention, dict) and mention.get("open_id") == bot_open_id:
            return True
    return False