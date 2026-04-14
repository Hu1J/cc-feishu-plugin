"""Proactive outreach scheduler — proactively message users when they've been silent."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, time

from cc_feishu_bridge.config import Config
from cc_feishu_bridge.claude.integration import ClaudeIntegration
from cc_feishu_bridge.claude.session_manager import SessionManager
from cc_feishu_bridge.feishu.client import FeishuClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """分析 {project_path} 项目：
- 当前状况和进展（看 git log / 文件变更）
- 下一步应该做什么

给用户一段简短汇报（200字以内），让他知道项目在哪、下一步往哪走。
语气自然，像同事之间的日常交流。开头不要加"嗨"或"你好"之类的客套话。"""


def _is_in_time_window(start: str, end: str) -> bool:
    """Return True if current local time is within [start, end)."""
    now = datetime.now().time()
    start_t = time.fromisoformat(start)
    end_t = time.fromisoformat(end)
    if start_t <= end_t:
        return start_t <= now < end_t
    # handles overnight window like 22:00-08:00
    return now >= start_t or now < end_t


async def _send_proactive_message(
    session,
    config: Config,
    session_manager: SessionManager,
) -> None:
    """Call Claude and send the result to Feishu. Silently skips on any error."""
    feishu = FeishuClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
        data_dir=config.data_dir,
    )

    # 创建独立的 Claude 进程，不与 MessageHandler 共享（避免并发冲突）
    claude = ClaudeIntegration(
        cli_path=config.claude.cli_path,
        max_turns=5,
        approved_directory=session.project_path,
    )
    claude._init_options()

    prompt = PROMPT_TEMPLATE.format(project_path=session.project_path)

    try:
        response, _, _ = await claude.query(prompt=prompt)
    except Exception as e:
        logger.warning(f"Proactive Claude call failed: {e}")
        return

    if not response or not response.strip():
        return

    # 去除 Claude 回复中可能自带的 emoji 标题前缀，避免重复
    cleaned = response.strip()
    for prefix in ("📋 项目进展提醒", "📋 项目提醒", "📋 项目进展", "📋 进展提醒", "📋 项目"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip("：: \n")
            break

    text = f"📋 项目进展提醒\n\n{cleaned}"

    try:
        await feishu.send_text(session.chat_id, text)
        session_manager.bump_proactive_count(session.session_id)
        session_manager.update_last_proactive_at(session.session_id)
        logger.info(f"Proactive outreach sent to chat {session.chat_id}")
    except Exception as e:
        logger.warning(f"Proactive send failed: {e}")


async def _check_and_notify(
    config: Config,
    session_manager: SessionManager,
) -> None:
    """Check all users and send proactive messages where conditions are met."""
    cfg = config.proactive
    today = datetime.utcnow().strftime("%Y-%m-%d")

    for session in session_manager.get_all_users():
        if not session.chat_id:
            continue

        # Time window check
        if not _is_in_time_window(cfg.time_window_start, cfg.time_window_end):
            continue

        # Silence threshold check
        if session.last_message_at:
            elapsed = (datetime.utcnow() - session.last_message_at).total_seconds() / 60
            if elapsed < cfg.silence_threshold_minutes:
                continue
        else:
            # no message ever received, skip
            continue

        # Daily cap check
        if cfg.max_per_day > 0:
            if session.proactive_today_date == today:
                if session.proactive_today_count >= cfg.max_per_day:
                    continue

        # Cooldown check: skip if a proactive message was sent recently
        if session.last_proactive_at:
            cooldown = (datetime.utcnow() - session.last_proactive_at).total_seconds() / 60
            if cooldown < cfg.cooldown_minutes:
                continue

        await _send_proactive_message(session, config, session_manager)


class ProactiveScheduler:
    """Background scheduler that periodically checks for silent users."""

    def __init__(
        self,
        config: Config,
        session_manager: SessionManager,
    ):
        self.config = config
        self.session_manager = session_manager
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.proactive.enabled:
            logger.info("Proactive scheduler disabled")
            return
        if self._task is not None:
            return
        self._stop.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Proactive scheduler started")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run())

    def stop(self) -> None:
        """Synchronous stop — safe to call from signal handlers."""
        if self._task is None:
            return
        self._stop.set()
        # Cancel the task from within its own event loop (thread-safe)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._task = None
        self._loop = None
        logger.info("Proactive scheduler stopped")

    async def _run(self) -> None:
        interval = self.config.proactive.check_interval_minutes * 60
        while not self._stop.is_set():
            try:
                await _check_and_notify(self.config, self.session_manager)
            except Exception:
                logger.exception("Error in proactive scheduler")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass