import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
from cc_feishu_bridge.claude.memory_manager import MemoryManager, MemoryEntry


@pytest.fixture
def mgr():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memories.db")
        m = MemoryManager(db_path)
        yield m


def test_add_and_search(mgr):
    entry = MemoryEntry(
        type="problem_solution",
        title="npm install 报错",
        problem="node_modules 版本冲突",
        solution="删掉 node_modules 重新 npm install",
        tags=["npm", "node_modules"],
    )
    mgr.add(entry)
    results = mgr.search("npm install")
    assert len(results) >= 1
    assert "冲突" in results[0].entry.solution or "npm" in (results[0].entry.tags or "")


def test_project_scope(mgr):
    entry = MemoryEntry(
        type="project_context",
        title="项目用 pnpm",
        solution="不要用 npm，用 pnpm install",
        project_path="/a/b",
    )
    mgr.add(entry)
    global_results = mgr.search("pnpm")
    # global search may return it depending on FTS behaviour
    project_results = mgr.search("pnpm", project_path="/a/b")
    assert len(project_results) >= 1


def test_use_count_bumped_on_search(mgr):
    entry = MemoryEntry(type="problem_solution", title="API v2", solution="用 /v2/ endpoint")
    mgr.add(entry)
    mgr.search("API")
    found = mgr.search("API")
    assert found[0].entry.use_count == 2


def test_delete(mgr):
    entry = MemoryEntry(type="problem_solution", title="delete me", solution="delete this")
    mgr.add(entry)
    results = mgr.search("delete")
    assert len(results) >= 1
    mgr.delete(results[0].entry.id)
    assert len(mgr.search("delete")) == 0


def test_list_by_project(mgr):
    # user_preference is global → get_by_project returns both project_context + user_preference
    mgr.add(MemoryEntry(type="project_context", title="p1", solution="s1", project_path="/p1"))
    mgr.add(MemoryEntry(type="user_preference", title="global_pref", solution="prefer dark mode"))
    mgr.add(MemoryEntry(type="project_context", title="p2", solution="s2", project_path="/p2"))
    mgr.add(MemoryEntry(type="project_context", title="global", solution="s3", project_path=None))
    p1_memories = mgr.get_by_project("/p1")
    assert len(p1_memories) == 3  # p1-specific + global project_context + user_preference


def test_inject_context_formats_correctly(mgr):
    mgr.add(MemoryEntry(
        type="project_context",
        title="项目用 pnpm",
        solution="不要用 npm，用 pnpm install",
    ))
    mgr.add(MemoryEntry(
        type="user_preference",
        title="全局偏好",
        solution="用中文写注释",
    ))
    ctx = mgr.inject_context(project_path="/test")
    assert "pnpm" in ctx
    assert "中文" in ctx
    assert "【项目记忆]" in ctx


def test_inject_context_empty_when_no_memories(mgr):
    ctx = mgr.inject_context(project_path="/nonexistent")
    assert ctx == ""