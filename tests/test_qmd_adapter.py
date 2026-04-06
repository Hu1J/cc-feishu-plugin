"""Tests for qmd_adapter.py."""
import os
import shutil
import subprocess
import tempfile

import pytest


@pytest.fixture
def tmp_memory_docs(monkeypatch):
    """Use a temp dir for memory-docs so tests don't pollute real data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        docs_dir = os.path.join(tmpdir, "memory-docs")
        index_db = os.path.join(tmpdir, "qmd-index.sqlite")
        data_dir = os.path.join(tmpdir, "cc-feishu-bridge")
        os.makedirs(docs_dir)
        os.makedirs(data_dir)

        # Patch QMD_DATA_DIR and QMD_INDEX_PATH for this test
        import cc_feishu_bridge.claude.qmd_adapter as qa
        from pathlib import Path as _Path
        monkeypatch.setattr(qa, "QMD_MEMORY_DOCS", _Path(docs_dir))
        monkeypatch.setattr(qa, "QMD_INDEX_PATH", _Path(index_db))
        monkeypatch.setattr(qa, "QMD_DATA_DIR", _Path(data_dir))
        monkeypatch.setattr(qa, "_qmd_adapter", None)  # reset singleton
        yield docs_dir, index_db
        # Restore
        from pathlib import Path as _Path2
        monkeypatch.setattr(qa, "QMD_MEMORY_DOCS", _Path2.home() / ".cc-feishu-bridge" / "memory-docs")
        monkeypatch.setattr(qa, "QMD_INDEX_PATH", _Path2.home() / ".cc-feishu-bridge" / "qmd-index.sqlite")
        monkeypatch.setattr(qa, "QMD_DATA_DIR", _Path2.home() / ".cc-feishu-bridge")
        monkeypatch.setattr(qa, "_qmd_adapter", None)


def _qmd(db_path: str, subcmd: list[str], timeout=30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["qmd", "--db", db_path] + subcmd,
        capture_output=True, text=True, timeout=timeout,
    )


def test_adapter_start_creates_collection(tmp_memory_docs):
    """start() creates qmd collection and is idempotent."""
    import cc_feishu_bridge.claude.qmd_adapter as qa
    from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter

    docs_dir, index_db = tmp_memory_docs

    adapter = QmdAdapter()
    ok = adapter.start()
    # qmd CLI should be available in test env
    assert ok is True
    assert adapter.is_available() is True

    # Idempotent second start
    ok2 = adapter.start()
    assert ok2 is True
    adapter.stop()


def test_add_and_search_memory(tmp_memory_docs):
    """Add a memory, then search for it via qmd."""
    import cc_feishu_bridge.claude.qmd_adapter as qa
    from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter

    docs_dir, index_db = tmp_memory_docs

    adapter = QmdAdapter()
    ok = adapter.start()
    if not ok:
        pytest.skip("qmd not available")

    added = adapter.add_memory(
        memory_id="test123",
        title="Python FTS5 optimization",
        content="Using jieba pre-tokenization for better Chinese search",
        keywords="FTS5,jieba,search",
        project_path="/tmp/test-project",
    )
    assert added is True

    # Search should find it
    docs = adapter.search("jieba", project_path="/tmp/test-project", limit=5)
    assert len(docs) >= 1
    body = docs[0].content
    assert "jieba" in body.lower() or "jieba" in (docs[0].keywords or "").lower()


def test_remove_memory(tmp_memory_docs):
    """Remove a memory and verify it's gone from search."""
    import cc_feishu_bridge.claude.qmd_adapter as qa
    from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter

    docs_dir, index_db = tmp_memory_docs

    adapter = QmdAdapter()
    ok = adapter.start()
    if not ok:
        pytest.skip("qmd not available")

    proj = "/tmp/test-remove-proj"
    adapter.add_memory("rem456", "DeleteMe Title", "DeleteMe content here", "kw", proj)

    docs_before = adapter.search("DeleteMe", project_path=proj)
    assert len(docs_before) >= 1

    adapter.remove_memory("rem456", proj)

    docs_after = adapter.search("DeleteMe", project_path=proj)
    assert len(docs_after) == 0


def test_search_isolated_by_project(tmp_memory_docs):
    """Memory in project A should not appear in project B search."""
    import cc_feishu_bridge.claude.qmd_adapter as qa
    from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter

    docs_dir, index_db = tmp_memory_docs

    adapter = QmdAdapter()
    ok = adapter.start()
    if not ok:
        pytest.skip("qmd not available")

    adapter.add_memory("memA", "ProjectA Exclusive", "Only in A project", "A-ex", "/proj/A")
    adapter.add_memory("memB", "ProjectB Exclusive", "Only in B project", "B-ex", "/proj/B")

    docs_a = adapter.search("Exclusive", project_path="/proj/A")
    docs_b = adapter.search("Exclusive", project_path="/proj/B")

    assert all(d.memory_id == "memA" for d in docs_a)
    assert all(d.memory_id == "memB" for d in docs_b)


def test_singleton():
    """get_qmd_adapter returns the same instance."""
    from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter, get_qmd_adapter

    a = get_qmd_adapter()
    b = get_qmd_adapter()
    assert a is b
    # QmdAdapter is shared singleton
    assert isinstance(a, QmdAdapter)


class TestEscapeMd:
    """Tests for _escape_md — markdown special character escaping."""

    def test_escapes_backtick(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("foo`bar") == r"foo\`bar"

    def test_escapes_asterisk(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("foo*bar") == r"foo\*bar"

    def test_escapes_underscore(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("foo_bar") == r"foo\_bar"

    def test_escapes_brackets(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("foo[bar]") == r"foo\[bar\]"

    def test_escapes_hash(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("# title") == r"\# title"

    def test_escapes_pipe(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("a|b") == r"a\|b"

    def test_escapes_backslash(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md(r"a\b") == r"a\\b"

    def test_preserves_chinese(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        assert _escape_md("中文测试") == "中文测试"

    def test_escape_all_together(self):
        from cc_feishu_bridge.claude.qmd_adapter import _escape_md
        title = "Test: *title* with `code` [and] _more_"
        result = _escape_md(title)
        assert "\\*" in result
        assert "\\`" in result
        assert "\\[" in result
        assert "\\_" in result
        assert "Test:" in result  # colon preserved


class TestBuildMdContent:
    """Tests for _build_md_content markdown escaping."""

    def test_title_escaped(self):
        from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter, _escape_md
        adapter = QmdAdapter()
        content = adapter._build_md_content(
            title="My *Bold* Title",
            content="Normal content",
            keywords="kw1,kw2",
            project_path="/path/to/proj",
        )
        assert r"\*" in content
        assert "My \\*Bold\\* Title" in content

    def test_content_escaped(self):
        from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter
        adapter = QmdAdapter()
        content = adapter._build_md_content(
            title="Title",
            content="List:\n- item1\n- item2",
            keywords="kw",
            project_path="/path",
        )
        assert "\\-" in content

    def test_project_path_escaped(self):
        from cc_feishu_bridge.claude.qmd_adapter import QmdAdapter
        adapter = QmdAdapter()
        content = adapter._build_md_content(
            title="Title",
            content="Content",
            keywords="kw",
            project_path="/path/[v1]/test",
        )
        assert "\\[" in content
        assert "\\]" in content
