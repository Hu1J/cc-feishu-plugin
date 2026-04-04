"""Restart and update — hot restart / hot upgrade for cc-feishu-bridge."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from cc_feishu_bridge.feishu.client import FeishuClient


class RestartError(Exception): pass
class StartupTimeoutError(RestartError): pass


# Step labels for CLI display (short, single line)
_CLI_STEP_LABELS = [
    "准备重启",
    "启动新 bridge",
    "等待新进程就绪",
    "重启完成",
]

# Step labels for Feishu messages (detailed, emoji)
_FEISHU_STEP_LABELS = [
    "🛑 准备重启",
    "🚀 启动新 bridge",
    "⏳ 等待新进程就绪",
    "✅ 重启完成",
]


@dataclass
class RestartStep:
    """A single step in the restart process, yielded as it happens."""
    step: int          # 1–4
    total: int         # always 4
    label: str         # short label shown to user
    status: str        # "done" | "error" | "final"
    detail: str = ""   # extra info (PID, path, etc.)
    success: bool = False   # True only on the final step on success
    new_pid: Optional[int] = None  # available on the final step


@dataclass
class RestartResult:
    success: bool
    new_pid: Optional[int] = None


def _pid_file_path(project_path: str) -> str:
    """Return the PID file path for a project."""
    return os.path.join(project_path, ".cc-feishu-bridge", "cc-feishu-bridge.pid")


def _read_pid(pid_file: str) -> Optional[int]:
    """Read PID from file. Returns None if file doesn't exist or is invalid."""
    if not os.path.exists(pid_file):
        return None
    try:
        return int(Path(pid_file).read_text().strip())
    except (ValueError, OSError):
        return None


def _is_process_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_process(pid: int, sig: int, timeout: float) -> bool:
    """Send signal to process and wait for it to die. Returns True if process stopped."""
    try:
        os.kill(pid, sig)
    except OSError:
        return True  # Process already dead

    # Wait for process to die
    start = time.time()
    while time.time() - start < timeout:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.1)
    return False


def _stop_bridge(project_path: str) -> bool:
    """Stop the bridge for a project. Uses SIGTERM then SIGKILL. Returns True if stopped, False if failed."""
    pid_file = _pid_file_path(project_path)
    pid = _read_pid(pid_file)

    if pid is None:
        return True  # Already stopped

    # SIGTERM first
    if not _kill_process(pid, signal.SIGTERM, timeout=5.0):
        # SIGKILL if still alive
        if not _kill_process(pid, signal.SIGKILL, timeout=2.0):
            return False

    # Clean up pid file
    try:
        Path(pid_file).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def _restart_to(file_lock=None):
    """Restart bridge in the current directory.

    Args:
        file_lock: FileLock object acquired by main.py; released before
                   starting new process so the new instance can acquire it.
    Yields RestartStep objects (4 steps total).
    """
    # Step 1: 准备重启
    yield RestartStep(step=1, total=4, label=_CLI_STEP_LABELS[0], status="done")

    # Step 2: 释放 FileLock（如果有），然后启动新进程
    if file_lock is not None:
        file_lock.release()

    # Yield "启动新 bridge" before starting so the step label is shown before waiting
    yield RestartStep(step=2, total=4, label=_CLI_STEP_LABELS[1], status="done")

    new_pid = _start_bridge(os.getcwd())

    # Step 3: 等待新进程就绪（_start_bridge already waits for pid file, so this step is immediate）
    yield RestartStep(step=3, total=4, label=_CLI_STEP_LABELS[2], status="done")

    # Step 4: 重启完成
    yield RestartStep(
        step=4, total=4, label=_CLI_STEP_LABELS[3],
        status="final", detail=f"新 PID {new_pid}",
        success=True, new_pid=new_pid,
    )


async def run_restart(file_lock, feishu: "FeishuClient",
                      chat_id: str, reply_to_message_id: str) -> None:
    """Run the restart with detailed step-by-step Feishu notifications.

    Sends a rich progress card to Feishu, updating it as each step completes.
    """
    current_path = os.getcwd()
    total = 4

    for step_obj in _restart_to(file_lock=file_lock):
        bar = "▓" * step_obj.step + "░" * (total - step_obj.step)
        label = _FEISHU_STEP_LABELS[step_obj.step - 1] if step_obj.step <= len(_FEISHU_STEP_LABELS) else f"步骤 {step_obj.step}"

        if step_obj.status == "final":
            final_card = (
                f"## ✅ 重启完成\n\n"
                f"**当前目录**: `{current_path}`\n"
                f"**新进程 PID**: `{step_obj.new_pid}`\n\n"
                f"🎉 Bridge 已重启，可以在飞书中继续对话了。"
            )
            await feishu.send_interactive_reply(chat_id, final_card, reply_to_message_id)
        else:
            progress_card = (
                f"## 🔄 正在重启\n\n"
                f"**当前目录**: `{current_path}`\n\n"
                f"{bar} `{step_obj.step}/{total}` {label}\n\n"
                f"⏳ 即将重启，请稍候..."
            )
            await feishu.send_interactive_reply(chat_id, progress_card, reply_to_message_id)


def run_restart_cli(file_lock, feishu=None, chat_id: str | None = None):
    """CLI version of restart — yields RestartStep, optionally sends Feishu notifications.

    Args:
        file_lock: FileLock object acquired by main.py
        feishu: FeishuClient instance (optional, for notifications)
        chat_id: Feishu chat_id (optional, required if feishu is provided)
    """
    import asyncio

    async def _run():
        if not feishu or not chat_id:
            for step in _restart_to(file_lock=file_lock):
                yield step
            return

        async def _send(card_md: str):
            try:
                await feishu.send_interactive_reply(chat_id, card_md, "")
            except Exception:
                pass  # non-fatal, CLI continues

        # Initial card
        initial = f"## 🔄 正在重启\n\n⏳ 准备重启，请稍候..."
        await _send(initial)

        for step_obj in _restart_to(file_lock=file_lock):
            bar = "▓" * step_obj.step + "░" * (4 - step_obj.step)
            label = _FEISHU_STEP_LABELS[step_obj.step - 1]

            if step_obj.status == "final":
                card = (
                    f"## ✅ 重启完成\n\n"
                    f"**当前目录**: `{os.getcwd()}`\n"
                    f"**新进程 PID**: `{step_obj.new_pid}`\n\n"
                    f"🎉 Bridge 已重启，可以在飞书中继续对话了。"
                )
                await _send(card)
            else:
                card = (
                    f"## 🔄 正在重启\n\n"
                    f"{bar} `{step_obj.step}/4` {label}\n\n"
                    f"⏳ 即将重启，请稍候..."
                )
                await _send(card)
            yield step_obj

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        gen = _run()
        try:
            while True:
                yielded = loop.run_until_complete(gen.__anext__())
                yield yielded
        except StopAsyncIteration:
            pass
    finally:
        loop.close()


def _start_bridge(project_path: str, timeout: float = 8.0) -> int:
    """Start the bridge for project using subprocess.Popen with start_new_session=True.

    Returns the PID of the started process.
    Raises StartupTimeoutError if pid file doesn't appear within timeout.
    """
    pid_file = _pid_file_path(project_path)

    # Remove stale pid file if exists
    Path(pid_file).unlink(missing_ok=True)

    # Start bridge via the installed binary (works for both pip installs and
    # PyInstaller binaries — cc-feishu-bridge is in PATH in both cases)
    project_cc = os.path.join(project_path, ".cc-feishu-bridge")
    stdout_log = open(os.path.join(project_cc, "bridge-stdout.log"), "w")
    stderr_log = open(os.path.join(project_cc, "bridge-stderr.log"), "w")
    try:
        proc = subprocess.Popen(
            ["cc-feishu-bridge", "start"],
            cwd=project_path,
            stdout=stdout_log,
            stderr=stderr_log,
            start_new_session=True,
        )

        # Wait for pid file to appear
        start = time.time()
        while time.time() - start < timeout:
            pid = _read_pid(pid_file)
            if pid is not None:
                stdout_log.close()
                stderr_log.close()
                return pid
            # Check if process crashed
            if proc.poll() is not None:
                stdout_log.close()
                stderr_log.close()
                raise StartupTimeoutError(f"Bridge process exited unexpectedly during startup")
            time.sleep(0.2)

        stdout_log.close()
        stderr_log.close()
        raise StartupTimeoutError(
            f"PID file did not appear within {timeout}s after starting bridge"
        )
    except Exception:
        stdout_log.close()
        stderr_log.close()
        raise
