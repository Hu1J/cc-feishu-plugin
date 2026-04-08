"""ClaudeIntegration instance pool — one Integration per session_key."""
from __future__ import annotations

import asyncio
import logging
import time

from cc_feishu_bridge.claude.integration import ClaudeIntegration

logger = logging.getLogger(__name__)


class ClaudeIntegrationPool:
    """Pool of ClaudeIntegration instances, one per session_key.

    Uses LRU eviction when max_size is reached.
    """

    def __init__(self, max_size: int = 10, **integration_kwargs):
        self._pool: dict[str, ClaudeIntegration] = {}
        self._last_used: dict[str, float] = {}  # session_key -> last access timestamp
        self._max_size = max_size
        self._integration_kwargs = integration_kwargs
        self._lock = asyncio.Lock()

    async def get(self, session_key: str) -> ClaudeIntegration:
        """Get or create an Integration for session_key."""
        async with self._lock:
            if session_key not in self._pool:
                self._ensure_capacity_unlocked()
                integration = ClaudeIntegration(**self._integration_kwargs)
                self._pool[session_key] = integration
                logger.info(f"Created new Integration for session_key={session_key}")
            self._last_used[session_key] = time.monotonic()
            return self._pool[session_key]

    def _ensure_capacity_unlocked(self) -> None:
        """Must be called with self._lock held. Evict oldest if at capacity."""
        if self._max_size <= 0:
            return  # unlimited
        if len(self._pool) < self._max_size:
            return
        oldest_key = min(self._last_used, key=self._last_used.get)
        del self._pool[oldest_key]
        del self._last_used[oldest_key]
        logger.info(f"Pool full — evicted session_key={oldest_key}")

    @property
    def size(self) -> int:
        return len(self._pool)

    @property
    def active_keys(self) -> list[str]:
        return list(self._pool.keys())