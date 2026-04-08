"""Chat-level lock manager for serializing messages per chat."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LockResult:
    acquired: bool
    lock: asyncio.Lock | None


class ChatLockManager:
    """Per-chat async lock with global concurrency limit.

    Usage:
        result = await lock_manager.acquire("och_xxx")
        if not result.acquired:
            return "当前会话繁忙，请稍后再试 🛑"
        try:
            await do_work()
        finally:
            await lock_manager.release("och_xxx")
    """

    def __init__(self, max_concurrent: int = 10):
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_count: int = 0
        self._max_concurrent = max_concurrent
        self._count_lock = asyncio.Lock()

    async def acquire(self, chat_id: str) -> LockResult:
        """Attempt to acquire a lock for chat_id.

        Returns LockResult(acquired=True, lock=lock) if successful.
        Returns LockResult(acquired=False, lock=None) if:
          - max concurrent limit reached
          - chat is already locked (another task is running in this chat)
        """
        async with self._count_lock:
            if self._max_concurrent > 0 and self._active_count >= self._max_concurrent:
                logger.warning(f"Max concurrent limit ({self._max_concurrent}) reached")
                return LockResult(acquired=False, lock=None)

        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        try:
            # timeout=1e-9 (1 nanosecond) is the practical non-blocking equivalent.
            # timeout=0 does not work in Python <=3.11 because Lock.acquire() always
            # yields at least once to the event loop, causing immediate timeout even
            # on a free lock.
            await asyncio.wait_for(lock.acquire(), timeout=1e-9)
        except asyncio.TimeoutError:
            logger.info(f"Chat {chat_id} is already locked")
            return LockResult(acquired=False, lock=None)
        self._active_count += 1
        logger.info(f"Acquired lock for chat {chat_id} ({self._active_count}/{self._max_concurrent})")
        return LockResult(acquired=True, lock=lock)

    async def release(self, chat_id: str) -> None:
        """Release the lock for chat_id."""
        if chat_id not in self._locks:
            return
        lock = self._locks[chat_id]
        if lock.locked():
            lock.release()
            async with self._count_lock:
                self._active_count -= 1
            logger.info(f"Released lock for chat {chat_id} ({self._active_count}/{self._max_concurrent})")

    @property
    def active_count(self) -> int:
        return self._active_count