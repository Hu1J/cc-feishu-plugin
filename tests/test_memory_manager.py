import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
from cc_feishu_bridge.claude.memory_manager import MemoryManager


@pytest.fixture
def mgr():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memories.db")
        m = MemoryManager(db_path)
        yield m


def test_add_preference_and_get_all(mgr):
    """user_preferences: 添加后能取回，字段正确"""
    pref = mgr.add_preference("主人信息", "我叫狗蛋，我的主人叫姚日华", "狗蛋,主人,姚日华")
    prefs = mgr.get_all_preferences()
    assert len(prefs) == 1
    assert prefs[0].id == pref.id
    assert prefs[0].title == "主人信息"
    assert prefs[0].content == "我叫狗蛋，我的主人叫姚日华"
    assert prefs[0].keywords == "狗蛋,主人,姚日华"


def test_project_memories_isolated_by_path(mgr):
    """不同 project_path 的记忆互不干扰"""
    mgr.add_project_memory("/proj-a", "用 pnpm", "不要用 npm，用 pnpm install", "pnpm,npm")
    mgr.add_project_memory("/proj-b", "用 yarn", "不要用 npm，用 yarn", "yarn,npm")
    results_a = mgr.search_project_memories("pnpm", project_path="/proj-a")
    results_b = mgr.search_project_memories("pnpm", project_path="/proj-b")
    assert any("pnpm" in r.memory.content for r in results_a)
    assert not any("pnpm" in r.memory.content for r in results_b)


def test_inject_context_returns_all_preferences(mgr):
    """inject_context 返回所有 user_preferences"""
    mgr.add_preference("主人信息", "我叫狗蛋", "狗蛋")
    ctx = mgr.inject_context(project_path="/any/path")
    assert "主人信息" in ctx
    assert "我叫狗蛋" in ctx


def test_inject_context_format_correctly(mgr):
    """inject_context 格式正确：标题+内容"""
    mgr.add_preference("发版规则", "发版前必须确认", "发版,确认")
    mgr.add_preference("主人信息", "我叫狗蛋", "狗蛋")
    ctx = mgr.inject_context(project_path="/any/path")
    assert "【用户偏好】" in ctx
    assert "发版规则" in ctx
    assert "发版前必须确认" in ctx
    assert "主人信息" in ctx


def test_inject_context_empty_when_no_preferences(mgr):
    """无用户偏好时返回空字符串"""
    ctx = mgr.inject_context(project_path="/any/path")
    assert ctx == ""


def test_delete_project_memory(mgr):
    """删除项目记忆"""
    mem = mgr.add_project_memory("/proj", "测试记忆", "这是测试内容", "测试")
    results = mgr.search_project_memories("测试", project_path="/proj")
    assert len(results) == 1
    ok = mgr.delete_project_memory(mem.id)
    assert ok is True
    results_after = mgr.search_project_memories("测试", project_path="/proj")
    assert len(results_after) == 0


def test_clear_project_memories(mgr):
    """清空某项目下所有记忆"""
    mgr.add_project_memory("/proj", "记忆1", "内容1", "关键词1")
    mgr.add_project_memory("/proj", "记忆2", "内容2", "关键词2")
    mgr.add_project_memory("/other", "其他", "其他内容", "其他")
    count = mgr.clear_project_memories("/proj")
    assert count == 2
    results = mgr.search_project_memories("记忆", project_path="/proj")
    assert len(results) == 0
    results_other = mgr.search_project_memories("其他", project_path="/other")
    assert len(results_other) == 1
