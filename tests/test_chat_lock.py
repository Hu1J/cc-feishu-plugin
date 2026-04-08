import asyncio
import pytest
from cc_feishu_bridge.claude.chat_lock import ChatLockManager


@pytest.fixture
def lock_mgr():
    return ChatLockManager(max_concurrent=2)


@pytest.mark.anyio
async def test_acquire_release(lock_mgr):
    result = await lock_mgr.acquire("och_test")
    assert result.acquired is True
    assert result.lock is not None

    await lock_mgr.release("och_test")
    assert lock_mgr.active_count == 0


@pytest.mark.anyio
async def test_same_chat_blocked(lock_mgr):
    r1 = await lock_mgr.acquire("och_test")
    assert r1.acquired is True

    r2 = await lock_mgr.acquire("och_test")
    assert r2.acquired is False  # already locked

    await lock_mgr.release("och_test")
    r3 = await lock_mgr.acquire("och_test")
    assert r3.acquired is True  # now available again


@pytest.mark.anyio
async def test_different_chats_independent(lock_mgr):
    r1 = await lock_mgr.acquire("och_chatA")
    r2 = await lock_mgr.acquire("och_chatB")
    assert r1.acquired is True
    assert r2.acquired is True
    assert lock_mgr.active_count == 2


@pytest.mark.anyio
async def test_concurrent_acquire_same_chat(lock_mgr):
    """Two coroutines racing on same chat — exactly one succeeds, one fails fast."""
    results = []

    async def try_acquire():
        r = await lock_mgr.acquire("och_race")
        results.append(r)
        if r.acquired:
            await lock_mgr.release("och_race")

    await asyncio.gather(try_acquire(), try_acquire())
    # Exactly one should succeed, one should fail — no hang
    acquired = [r for r in results if r.acquired]
    rejected = [r for r in results if not r.acquired]
    assert len(acquired) == 1, f"Expected 1 acquired, got {len(acquired)}: {results}"
    assert len(rejected) == 1, f"Expected 1 rejected, got {len(rejected)}: {results}"


@pytest.mark.anyio
async def test_max_concurrent_limit(lock_mgr):
    # max_concurrent=2
    r1 = await lock_mgr.acquire("och_A")
    r2 = await lock_mgr.acquire("och_B")
    assert r1.acquired is True
    assert r2.acquired is True

    r3 = await lock_mgr.acquire("och_C")
    assert r3.acquired is False  # limit reached

    await lock_mgr.release("och_A")
    r4 = await lock_mgr.acquire("och_C")
    assert r4.acquired is True  # now available