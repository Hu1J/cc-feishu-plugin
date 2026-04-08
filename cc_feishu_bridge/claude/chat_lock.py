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
        # Semaphore is None when unlimited (max_concurrent==0), otherwise guards
        # the global slot limit atomically. Using a large initial value for unlimited
        # would grow unbounded, so we gate it conditionally.
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        )

    async def acquire(self, chat_id: str) -> LockResult:
        """Attempt to acquire a lock for chat_id.

        Returns LockResult(acquired=True, lock=lock) if successful.
        Returns LockResult(acquired=False, lock=None) if:
          - max concurrent limit reached
          - chat is already locked (another task is running in this chat)

        Safety: _active_count is only incremented after the per-chat lock is
        confirmed acquired, and release() only decrements when lock.locked() is
        True — preventing double-decrement races.
        """
        # Claim a global semaphore slot first (only in limited mode).
        if self._semaphore is not None:
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=1e-9)
            except asyncio.TimeoutError:
                logger.warning(f"Max concurrent limit ({self._max_concurrent}) reached")
                return LockResult(acquired=False, lock=None)

        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        # Try fast-path acquire without yielding
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=1e-9)
            acquired = True
        except asyncio.TimeoutError:
            pass

        if not acquired:
            # Lock was held — release the semaphore slot we just claimed.
            if self._semaphore is not None:
                self._semaphore.release()
            logger.info(f"Chat {chat_id} is already locked")
            return LockResult(acquired=False, lock=None)

        # Only increment after confirmed lock acquisition
        async with self._count_lock:
            self._active_count += 1
        mode_str = f"({self._active_count}/{self._max_concurrent})" if self._max_concurrent > 0 else f"({self._active_count}/unlimited)"
        logger.info(f"Acquired lock for chat {chat_id} {mode_str}")
        return LockResult(acquired=True, lock=lock)

    async def release(self, chat_id: str) -> None:
        """Release the lock for chat_id.

        Only decrements _active_count when the lock was actually held (locked() is True).
        This prevents double-decrement when release() races with an acquire() timeout.
        """
        if chat_id not in self._locks:
            return
        lock = self._locks[chat_id]
        if not lock.locked():
            # Lock was never acquired (acquire timed out) or already released —
            # nothing to clean up. In particular, _active_count was NOT incremented
            # in the acquire() timeout path, so no decrement is needed here either.
            return
        lock.release()
        async with self._count_lock:
            self._active_count -= 1
        if self._semaphore is not None:
            self._semaphore.release()
        mode_str = f"({self._active_count}/{self._max_concurrent})" if self._max_concurrent > 0 else f"({self._active_count}/unlimited)"
        logger.info(f"Released lock for chat {chat_id} {mode_str}")

    @property
    def active_count(self) -> int:
        return self._active_count