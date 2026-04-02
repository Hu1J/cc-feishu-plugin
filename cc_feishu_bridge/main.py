"""CLI entry point — starts WebSocket long connection to Feishu.

Data is stored in .cc-feishu-bridge/ subdirectory of the current working directory,
enabling natural multi-instance isolation.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import filelock

from cc_feishu_bridge.config import load_config, resolve_config_path
from cc_feishu_bridge.feishu.client import FeishuClient, IncomingMessage
from cc_feishu_bridge.feishu.ws_client import FeishuWSClient
from cc_feishu_bridge.feishu.message_handler import MessageHandler
from cc_feishu_bridge.feishu.error_notifier import setup as setup_error_notifier, update_chat_id as notifier_update_chat_id
from cc_feishu_bridge.security.auth import Authenticator
from cc_feishu_bridge.security.validator import SecurityValidator
from cc_feishu_bridge.claude.integration import ClaudeIntegration
from cc_feishu_bridge.claude.session_manager import SessionManager
from cc_feishu_bridge.format.reply_formatter import ReplyFormatter

logger = logging.getLogger(__name__)


class _SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that silently ignores UnicodeEncodeError on Windows GBK consoles."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # Fallback: encode with errors='replace' and write directly
            try:
                msg = self.format(record) + self.terminator
                encoded = msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                self.stream.write(encoded)
                self.flush()
            except Exception:
                pass


# ANSI color codes for terminal output
class ColoredFormatter(logging.Formatter):
    """Add ANSI color codes to log records based on level. Used for terminal only."""

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def create_handler(config, data_dir: str) -> MessageHandler:
    """Create MessageHandler with all dependencies wired up."""
    feishu = FeishuClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
        data_dir=data_dir,
    )
    setup_error_notifier(feishu)
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
        data_dir=data_dir,
    )
    return handler


async def handle_message(message: IncomingMessage, handler: MessageHandler) -> None:
    """Callback for incoming Feishu messages — dispatch to handler."""
    # Keep error notifier's chat_id fresh for error reporting
    notifier_update_chat_id(message.chat_id)
    try:
        await handler.handle(message)
    except Exception as e:
        logger.exception(f"Error handling message: {e}")


def ensure_skill_installed() -> None:
    """Install or update the cc-feishu-send-file skill to ~/.claude/skills/.

    Idempotent: skips if version matches, updates if version differs.
    The skill content is bundled inside the package (cc_feishu_bridge.skill_md)
    so this works correctly whether installed via pip or as a PyInstaller binary.
    """
    import os

    from cc_feishu_bridge.skill_md import SKILL_MD, SKILL_NAME, SKILL_VERSION

    dest_dir = os.path.expanduser(f"~/.claude/skills/{SKILL_NAME}")
    dest_path = os.path.join(dest_dir, "skill.md")
    version_marker = os.path.join(dest_dir, ".version")

    if os.path.exists(dest_path):
        current_version = ""
        if os.path.exists(version_marker):
            current_version = open(version_marker).read().strip()
        if current_version == SKILL_VERSION:
            logger.info(f"Skill {SKILL_NAME} v{SKILL_VERSION} already installed, skipping.")
            return

    # Install or update — write the bundled string to disk
    os.makedirs(dest_dir, exist_ok=True)
    open(dest_path, "w", encoding="utf-8").write(SKILL_MD)
    open(version_marker, "w").write(SKILL_VERSION)
    logger.info(f"Installed skill {SKILL_NAME} v{SKILL_VERSION} to {dest_dir}")


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


def confirm_risk_warning(config_path: str) -> bool:
    """Show risk warning and get user confirmation. Saves acceptance to config on 'yes'."""
    from cc_feishu_bridge.config import accept_bypass_warning
    print(RISK_WARNING)
    while True:
        try:
            response = input().strip().lower()
            if response in ("yes", "y"):
                accept_bypass_warning(config_path)
                print("已记录，下次启动将不再提示。")
                return True
            elif response in ("no", "n", ""):
                print("Cancelled — not starting the bridge.")
                return False
            else:
                print("Please enter 'yes' or 'no': ", end="")
        except EOFError:
            print("no (EOF)")
            return False


def _claude_available(cli_path: str) -> bool:
    """Return True if the Claude CLI is found in PATH or at the given path."""
    if cli_path != "claude":
        # Explicit path — just check if file exists and is executable
        return os.path.isfile(cli_path) and os.access(cli_path, os.X_OK)
    return shutil.which("claude") is not None


def start_bridge(config_path: str, data_dir: str) -> None:
    """Start the bridge: load config and run WebSocket connection."""
    # Acquire exclusive lock before starting — prevents multiple instances in the same directory
    lock_file = os.path.join(data_dir, ".instance.lock")
    lock = filelock.FileLock(lock_file, timeout=1)
    try:
        lock.acquire()
    except filelock.Timeout:
        print(f"错误：当前目录下已有一个 cc-feishu-bridge 实例正在运行 ({data_dir})")
        print("如果确认没有实例在运行，请删除 .instance.lock 文件后重试。")
        sys.exit(1)

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

    # Clean up PID file and lock on exit
    def cleanup(signum, frame):
        remove_pid(pid_file)
        lock.release()
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    logger.info(f"Starting Feishu bridge (WS mode) — data: {data_dir}")

    # Check Claude Code CLI availability before connecting — fail fast with a clear message
    if not _claude_available(config.claude.cli_path):
        print()
        print("❌ Claude Code 未安装或不可用，bridge 无法启动。")
        print()
        print("请先安装 Claude Code：")
        print("  npm install -g @anthropic-ai/claude-code")
        print()
        print("安装完成后重新运行 cc-feishu-bridge 即可。")
        print()
        sys.exit(1)

    # Auto-install Claude skill for file sending
    ensure_skill_installed()

    # Create media subdirectories
    for sub in ("received_images", "received_files"):
        sub_dir = os.path.join(data_dir, sub)
        os.makedirs(sub_dir, exist_ok=True)

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


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB


def run_send_command(file_paths: list[str], config_path: str) -> None:
    """Send one or more files to the active Feishu chat."""
    import os
    from pathlib import Path

    # 1. Load config
    if not os.path.exists(config_path):
        print(f"Error: config file not found: {config_path}")
        return
    from cc_feishu_bridge.config import load_config
    config = load_config(config_path)

    # 2. Locate sessions.db (same directory as config)
    data_dir = str(Path(config_path).parent.resolve())
    db_path = os.path.join(data_dir, "sessions.db")
    if not os.path.exists(db_path):
        print("Error: sessions.db not found. Has the bridge ever been run?")
        return

    # 3. Find the most recently active session's chat_id
    from cc_feishu_bridge.claude.session_manager import SessionManager
    sm = SessionManager(db_path=db_path)
    session = sm.get_active_session_by_chat_id()
    if not session or not session.chat_id:
        print("Error: no active chat session found. Make sure the bridge has been used.")
        return
    chat_id = session.chat_id
    print(f"Sending to chat: {chat_id}")

    # 4. Create FeishuClient
    from cc_feishu_bridge.feishu.client import FeishuClient
    feishu = FeishuClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
    )

    # 5. Process each file
    import asyncio
    try:
        from cc_feishu_bridge.feishu.media import guess_file_type
    except ImportError:
        guess_file_type = None

    async def send_one(file_path: str) -> str:
        """Send a single file. Raises on error so gather() can collect it."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        size = os.path.getsize(file_path)
        if size > MAX_FILE_SIZE:
            raise ValueError(f"{file_path} exceeds 30MB limit")

        with open(file_path, "rb") as f:
            data = f.read()

        ext = os.path.splitext(file_path)[1].lower()
        file_name = os.path.basename(file_path)

        if ext in SUPPORTED_IMAGE_EXTS:
            image_key = await feishu.upload_image(data)
            msg_id = await feishu.send_image(chat_id, image_key)
            print(f"Sent image: {file_name} → {msg_id}")
        else:
            if guess_file_type is not None:
                file_type = guess_file_type(ext)
            else:
                file_type = None
            file_key = await feishu.upload_file(data, file_name, file_type)
            msg_id = await feishu.send_file(chat_id, file_key, file_name)
            print(f"Sent file: {file_name} → {msg_id}")

        return msg_id

    async def main_async():
        # Upload all files concurrently, then send all concurrently.
        # Feishu renders consecutive image messages grouped together.
        results = await asyncio.gather(*[send_one(fp) for fp in file_paths], return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error sending {file_paths[i]}: {result}")

    asyncio.run(main_async())


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

    # send
    send_parser = subparsers.add_parser("send", help="Send a file or image to the active Feishu chat")
    send_parser.add_argument("files", nargs="+", help="Path(s) to the file(s) to send")
    send_parser.add_argument("--config", required=True, help="Path to config.yaml for this bridge instance")

    args = parser.parse_args(args)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # Python < 3.7
    _stdout_handler = _SafeStreamHandler(sys.stdout)
    _stdout_handler.setLevel(args.log_level)
    _stdout_handler.setFormatter(ColoredFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.root.addHandler(_stdout_handler)
    logging.root.setLevel(args.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("qrcode").setLevel(logging.WARNING)

    command = args.command

    if command == "list":
        list_bridges()
        return

    if command == "stop":
        stop_bridge(args.pid)
        return

    if command == "send":
        from cc_feishu_bridge.main import run_send_command
        run_send_command(args.files, args.config)
        return

    # Default: start
    is_installed = detect_config()
    if not is_installed:
        logger.info("No config found, running install flow...")
        cfg_path, data_dir = asyncio.run(interactive_install())
    else:
        cfg_path, data_dir = resolve_config_path()

    # Risk warning must be acknowledged before starting (skip if already accepted)
    if is_installed:
        from cc_feishu_bridge.config import load_config
        config = load_config(cfg_path)
        if config.bypass_accepted:
            logger.info("Bypass warning already accepted, skipping.")
        else:
            if not confirm_risk_warning(cfg_path):
                return
    else:
        if not confirm_risk_warning(cfg_path):
            return

    # Set up logging to file
    log_file = os.path.join(data_dir, "cc-feishu-bridge.log")
    Path(data_dir).mkdir(exist_ok=True)
    fh = logging.FileHandler(log_file)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    if is_installed:
        logger.info(f"Config found, starting bridge...")
    else:
        logger.info("Install complete, starting bridge...")
    start_bridge(cfg_path, data_dir)


if __name__ == "__main__":
    main()
