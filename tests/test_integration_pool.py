import pytest
from cc_feishu_bridge.claude.integration_pool import ClaudeIntegrationPool


@pytest.mark.anyio
async def test_pool_creates_integration():
    pool = ClaudeIntegrationPool(max_size=3, cli_path="claude")
    assert pool.size == 0

    int1 = await pool.get("session_A")
    assert pool.size == 1
    assert int1 is not None

    int2 = await pool.get("session_B")
    assert pool.size == 2


@pytest.mark.anyio
async def test_pool_reuses_same_integration():
    pool = ClaudeIntegrationPool(cli_path="claude")
    int1 = await pool.get("session_A")
    int2 = await pool.get("session_A")
    assert int1 is int2
    assert pool.size == 1


@pytest.mark.anyio
async def test_pool_lru_eviction():
    pool = ClaudeIntegrationPool(max_size=2, cli_path="claude")
    await pool.get("session_A")
    await pool.get("session_B")
    assert pool.size == 2

    # session_C triggers eviction of oldest (session_A)
    await pool.get("session_C")
    assert pool.size == 2
    assert "session_A" not in pool.active_keys
    assert "session_B" in pool.active_keys
    assert "session_C" in pool.active_keys


@pytest.mark.anyio
async def test_unlimited_pool():
    pool = ClaudeIntegrationPool(max_size=0, cli_path="claude")
    for i in range(20):
        await pool.get(f"session_{i}")
    assert pool.size == 20