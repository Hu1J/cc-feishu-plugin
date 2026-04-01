"""CLI entry point — starts WebSocket long connection to Feishu.

Data is stored in .cc-feishu-bridge/ subdirectory of the current working directory,
enabling natural multi-instance isolation.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

from cc_feishu_bridge.config import load_config, resolve_config_path
from cc_feishu_bridge.feishu.client import FeishuClient, IncomingMessage
from cc_feishu_bridge.feishu.ws_client import FeishuWSClient
from cc_feishu_bridge.feishu.message_handler import MessageHandler
from cc_feishu_bridge.security.auth import Authenticator
from cc_feishu_bridge.security.validator import SecurityValidator
from cc_feishu_bridge.claude.integration import ClaudeIntegration
from cc_feishu_bridge.claude.session_manager import SessionManager
from cc_feishu_bridge.format.reply_formatter import ReplyFormatter

import logging

logger = logging.getLogger(__name__)


def create_handler(config, data_dir: str) -> MessageHandler:
    """Create MessageHandler with all dependencies wired up."""
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
    db_path = os.path.join(data_dir, "sessions.db")
    session_manager = SessionManager(db_path=db_path)
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
    return handler


async def handle_message(message: IncomingMessage, handler: MessageHandler) -> None:
    """Callback for incoming Feishu messages — dispatch to handler."""
    try:
        await handler.handle(message)
    except Exception as e:
        logger.exception(f"Error handling message: {e}")


def write_pid(pid_file: str) -> None:
    """Write current PID to file."""
    Path(pid_file).write_text(str(os.getpid()))


def remove_pid(pid_file: str) -> None:
    """Remove PID file."""
    Path(pid_file).unlink(missing_ok=True)


RISK_WARNING = """
⚠️  安全风险警告 / Security Risk Warning
==============================================================

cc-feishu-bridge 以 bypassPermissions 模式运行。
Claude Code 可以执行任意终端命令、读写本地文件，无需每次授权确认。

这意味着如果有人通过飞书向机器人发送恶意指令，攻击者可以：
  • 在你的电脑上执行任意命令
  • 读取、修改或删除你的本地文件
  • 访问你的敏感信息

请仅在可信任的网络环境下使用本工具。

cc-feishu-bridge runs in bypassPermissions mode.
Claude Code can execute arbitrary terminal commands and read/write local files
without asking for permission each time.

Do you understand and accept these risks? (yes/no): """


def confirm_risk_warning() -> bool:
    """Show risk warning and get user confirmation. Returns True only on 'yes'."""
    print(RISK_WARNING)
    while True:
        try:
            response = input().strip().lower()
            if response in ("yes", "y"):
                return True
            elif response in ("no", "n", ""):
                print("Cancelled — not starting the bridge.")
                return False
            else:
                print("Please enter 'yes' or 'no': ", end="")
        except EOFError:
            print("no (EOF)")
            return False


def start_bridge(config_path: str, data_dir: str) -> None:
    """Start the bridge: load config and run WebSocket connection."""
    config = load_config(config_path)
    handler = create_handler(config, data_dir)

    ws_client = FeishuWSClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
        domain=config.feishu.domain,
        on_message=lambda msg: handle_message(msg, handler),
    )

    # Write PID file for process management
    pid_file = os.path.join(data_dir, "cc-feishu-bridge.pid")
    write_pid(pid_file)

    # Clean up PID file on exit
    def cleanup(signum, frame):
        remove_pid(pid_file)
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    logger.info(f"Starting Feishu bridge (WS mode) — data: {data_dir}")
    ws_client.start()


def list_bridges() -> None:
    """List all cc-feishu-bridge instances by scanning .cc-feishu-bridge/*.pid files."""
    print("\nRunning cc-feishu-bridge instances:")
    print(f"{'PID':<8} {'Directory':<40} {'PID File':<50}")
    print("-" * 100)

    found = False
    for root, dirs, files in os.walk("."):
        # Only look in .cc-feishu-bridge directories
        if ".cc-feishu-bridge" not in dirs:
            continue
        cc_dir = os.path.join(root, ".cc-feishu-bridge")
        pid_file = os.path.join(cc_dir, "cc-feishu-bridge.pid")
        if not os.path.exists(pid_file):
            continue
        try:
            pid = int(Path(pid_file).read_text().strip())
            # Check if process is alive
            try:
                os.kill(pid, 0)
                status = "running"
            except OSError:
                status = "dead (clean up pid file)"
            print(f"{pid:<8} {os.path.abspath(root):<40} {pid_file:<50} {status}")
            found = True
        except (ValueError, OSError):
            pass

    if not found:
        print("No running instances found.")
    print()


def stop_bridge(pid: int) -> None:
    """Stop a cc-feishu-bridge instance by PID."""
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped PID {pid}")
    except OSError as e:
        print(f"Failed to stop PID {pid}: {e}")


def detect_config() -> bool:
    """Check if .cc-feishu-bridge/config.yaml exists and is non-empty."""
    cfg, _ = resolve_config_path()
    p = Path(cfg)
    return p.exists() and p.stat().st_size > 0


async def interactive_install() -> tuple[str, str]:
    """Run the QR-code install flow. Returns (cfg_path, data_dir) on success."""
    from cc_feishu_bridge.install.flow import run_install_flow
    cfg_path, data_dir = resolve_config_path()
    await run_install_flow(cfg_path)
    return cfg_path, data_dir


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Claude Code Feishu Bridge — data stored in .cc-feishu-bridge/"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # start (default)
    start_parser = subparsers.add_parser("start", help="Start the bridge (default)")

    # list
    list_parser = subparsers.add_parser("list", help="List all running instances")

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop a running instance")
    stop_parser.add_argument("pid", type=int, help="PID of the instance to stop")

    args = parser.parse_args(args)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("qrcode").setLevel(logging.WARNING)

    command = args.command

    if command == "list":
        list_bridges()
        return

    if command == "stop":
        stop_bridge(args.pid)
        return

    # Default: start
    is_installed = detect_config()
    if not is_installed:
        logger.info("No config found, running install flow...")
        cfg_path, data_dir = asyncio.run(interactive_install())
    else:
        cfg_path, data_dir = resolve_config_path()

    # Risk warning must be acknowledged before starting
    if not confirm_risk_warning():
        return

    # Set up logging to file
    log_file = os.path.join(data_dir, "cc-feishu-bridge.log")
    Path(data_dir).mkdir(exist_ok=True)
    fh = logging.FileHandler(log_file)
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    if is_installed:
        logger.info(f"Config found, starting bridge...")
    else:
        logger.info("Install complete, starting bridge...")
    start_bridge(cfg_path, data_dir)


if __name__ == "__main__":
    main()
