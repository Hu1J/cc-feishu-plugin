"""CLI entry point and HTTP webhook server."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web

from src.config import load_config
from src.feishu.client import FeishuClient
from src.feishu.message_handler import MessageHandler
from src.security.auth import Authenticator
from src.security.validator import SecurityValidator
from src.claude.integration import ClaudeIntegration
from src.claude.session_manager import SessionManager
from src.format.reply_formatter import ReplyFormatter

logger = logging.getLogger(__name__)


async def webhook_handler(request: web.Request) -> web.Response:
    """Handle incoming Feishu webhook events."""
    handler: MessageHandler = request.app["handler"]

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    message = handler.feishu.parse_incoming_message(body)
    if not message:
        return web.Response(status=200, text="OK")

    # Run handler in background
    asyncio.create_task(handler.handle(message))

    return web.Response(status=200, text="OK")


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK")


def create_app(config) -> web.Application:
    """Build the aiohttp application."""
    feishu = FeishuClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
    )
    authenticator = Authenticator(allowed_users=config.auth.allowed_users)
    validator = SecurityValidator(approved_directory=config.claude.approved_directory)
    claude = ClaudeIntegration(
        cli_path=config.claude.cli_path,
        max_turns=config.claude.max_turns,
        approved_directory=config.claude.approved_directory,
    )
    session_manager = SessionManager(db_path=config.storage.db_path)
    formatter = ReplyFormatter()

    handler = MessageHandler(
        feishu_client=feishu,
        authenticator=authenticator,
        validator=validator,
        claude=claude,
        session_manager=session_manager,
        formatter=formatter,
        approved_directory=config.claude.approved_directory,
    )

    app = web.Application()
    app["handler"] = handler
    app.router.add_post(config.server.webhook_path, webhook_handler)
    app.router.add_get("/health", health_handler)
    return app


def main():
    parser = argparse.ArgumentParser(description="Claude Code Feishu Bridge")
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = load_config(args.config)
    logger.info("Config loaded, starting bridge service...")

    app = create_app(config)
    web.run_app(
        app,
        host=config.server.host,
        port=config.server.port,
        print=None,
    )


if __name__ == "__main__":
    main()
