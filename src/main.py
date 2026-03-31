"""CLI entry point — detects config and routes to install or start."""
from __future__ import annotations

import argparse
import asyncio
import logging
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

DEFAULT_CONFIG_PATH = "config.yaml"


async def webhook_handler(request: web.Request) -> web.Response:
    handler: MessageHandler = request.app["handler"]
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    message = handler.feishu.parse_incoming_message(body)
    if not message:
        return web.Response(status=200, text="OK")

    asyncio.create_task(handler.handle(message))
    return web.Response(status=200, text="OK")


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK")


def create_app(config):
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


async def run_server(config_path: str):
    config = load_config(config_path)
    app = create_app(config)
    logger.info(f"Starting server on {config.server.host}:{config.server.port}")
    web.run_app(
        app,
        host=config.server.host,
        port=config.server.port,
        print=None,
    )


def detect_config(config_path: str) -> bool:
    """Check if config file exists and is non-empty."""
    p = Path(config_path)
    return p.exists() and p.stat().st_size > 0


async def interactive_install(config_path: str):
    """Run the QR-code install flow, then start server."""
    from src.install.flow import run_install_flow
    result = await run_install_flow(config_path)
    # After install flow saves config, load and start server
    await run_server(config_path)


def main():
    parser = argparse.ArgumentParser(description="Claude Code Feishu Bridge")
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.yaml",
    )
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

    if detect_config(args.config):
        logger.info(f"Config found at {args.config}, starting server...")
        asyncio.run(run_server(args.config))
    else:
        logger.info(f"No config found at {args.config}, running install flow...")
        asyncio.run(interactive_install(args.config))


if __name__ == "__main__":
    main()
