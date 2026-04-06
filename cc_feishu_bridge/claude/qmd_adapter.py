"""
qmd adapter — wraps qmd CLI for project memory operations.

Design:
- qmd stores hybrid (BM25 + vector) search index at ~/.config/qmd/qmd.db
  (overridden to ~/.cc-feishu-bridge/qmd-index.sqlite via --db flag)
- Each memory is a markdown file on disk:
    ~/.cc-feishu-bridge/memory-docs/{proj_hash}/{memory_id}.md
- A single qmd collection "project_memories" indexes all files
- After each add/delete/update, run "qmd update project_memories"
- Search results filtered by project_hash directory
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Fixed data directory under user's home
QMD_DATA_DIR = Path.home() / ".cc-feishu-bridge"
QMD_INDEX_PATH = QMD_DATA_DIR / "qmd-index.sqlite"
QMD_MEMORY_DOCS = QMD_DATA_DIR / "memory-docs"
QMD_COLLECTION = "project_memories"


def _proj_hash(project_path: str) -> str:
    """MD5 hash prefix (16 chars / 64 bits) for project isolation in file paths. 10万项目碰撞概率 < 0.0004%"""
    return hashlib.md5(project_path.encode()).hexdigest()[:16]


def _mem_file_path(project_path: str, memory_id: str) -> Path:
    """Path to a memory's markdown file on disk."""
    return QMD_MEMORY_DOCS / _proj_hash(project_path) / f"{memory_id}.md"


@dataclass
class QmdDoc:
    """A document returned from qmd search/list."""
    memory_id: str
    project_path: str
    title: str
    content: str
    keywords: str
    score: float


class QmdUnavailableError(Exception):
    """Raised when qmd CLI is not available."""
    pass


class QmdAdapter:
    """
    Manages qmd CLI and file operations for project memories.

    qmd CLI workflow:
        qmd add project_memories <docs_dir>
        qmd update project_memories   # after each file change
        qmd query <q> --collection project_memories --format json --full

    Usage (singleton via get_qmd_adapter()):
        adapter = QmdAdapter()
        ok = adapter.start()          # init collection, idempotent
        adapter.add_memory("abc", "标题", "内容", "kw", "/proj")
        docs = adapter.search("搜索词", "/proj")
        adapter.remove_memory("abc", "/proj")
        adapter.stop()
    """

    _proc: Optional[subprocess.Popen] = None  # kept for future MCP stdio use
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __init__(self):
        self._started = False

    def _ensure_data_dir(self):
        QMD_MEMORY_DOCS.mkdir(parents=True, exist_ok=True)

    def _qmd(self, subcmd_args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        """
        Run a qmd CLI command with --db pointing to our index.
        Raises FileNotFoundError if qmd not found.
        """
        cmd = ["qmd", "--db", str(QMD_INDEX_PATH)] + subcmd_args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(QMD_DATA_DIR),
        )

    def start(self) -> bool:
        """
        Initialize qmd collection. Idempotent.

        Returns True if qmd is available and collection was (re)created,
        False if qmd CLI not found.
        """
        with self._lock:
            if self._started:
                return self._initialized

            self._ensure_data_dir()

            try:
                # Ensure collection exists (re-add if already exists — safe)
                result = self._qmd([
                    "add", QMD_COLLECTION, str(QMD_MEMORY_DOCS),
                    "--pattern", "**/*.md",
                ])
                logger.info("qmd collection init: %s", result.stdout.strip() or result.stderr.strip())

                # Initial index build
                update_result = self._qmd(["update", QMD_COLLECTION])
                if update_result.returncode != 0:
                    logger.warning("qmd initial update: %s", update_result.stderr.strip())

                self._initialized = True
                self._started = True
                logger.info("qmd adapter started, index=%s", QMD_INDEX_PATH)
                return True

            except FileNotFoundError:
                logger.warning("qmd CLI not found — semantic search disabled")
                self._initialized = False
                # 不设置 _started=True，允许下次重试
                return False
            except Exception as e:
                logger.warning("qmd start failed: %s", e)
                self._initialized = False
                # 不设置 _started=True，允许下次重试
                return False

    def stop(self):
        """Stop adapter (no-op for CLI mode)."""
        with self._lock:
            self._initialized = False
            self._started = False

    def is_available(self) -> bool:
        """True if qmd CLI is available and collection was initialized."""
        return self._initialized

    # ── File operations ─────────────────────────────────────────────────────

    def _build_md_content(
        self,
        title: str,
        content: str,
        keywords: str,
        project_path: str,
    ) -> str:
        return (
            f"# {_escape_md(title)}\n\n"
            f"{_escape_md(content)}\n\n"
            f"**Keywords**: {_escape_md(keywords)}\n"
            f"**Project**: {_escape_md(project_path)}\n"
        )

    def add_memory(
        self,
        memory_id: str,
        title: str,
        content: str,
        keywords: str,
        project_path: str,
    ) -> bool:
        """
        Write a memory as a markdown file and reindex qmd.
        Idempotent: overwrites existing file with same memory_id.
        """
        if not self.is_available():
            return False

        try:
            self._ensure_data_dir()
            fp = _mem_file_path(project_path, memory_id)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(
                self._build_md_content(title, content, keywords, project_path),
                encoding="utf-8",
            )
            # Reindex
            result = self._qmd(["update", QMD_COLLECTION], timeout=60)
            if result.returncode != 0:
                logger.warning("qmd update after add: %s", result.stderr.strip())
            return True
        except Exception as e:
            logger.warning("add_memory failed: %s", e)
            return False

    def remove_memory(self, memory_id: str, project_path: str) -> bool:
        """Delete a memory file and reindex qmd."""
        if not self.is_available():
            return False

        try:
            fp = _mem_file_path(project_path, memory_id)
            if fp.exists():
                fp.unlink()
                # Clean up empty project hash dir
                try:
                    fp.parent.rmdir()
                except OSError:
                    pass  # not empty
            result = self._qmd(["update", QMD_COLLECTION], timeout=60)
            if result.returncode != 0:
                logger.warning("qmd update after remove: %s", result.stderr.strip())
            return True
        except Exception as e:
            logger.warning("remove_memory failed: %s", e)
            return False

    def list_memories(self, project_path: str) -> list[QmdDoc]:
        """
        List all memories for a project via qmd query.
        Uses a catch-all query to get all docs, then filters.
        """
        if not self.is_available():
            return []

        try:
            proj_hash = _proj_hash(project_path)
            # Query for a space to get broad results, filter by path
            result = self._qmd([
                "query", " ",
                "--collection", QMD_COLLECTION,
                "--format", "json",
                "--full",
                "--limit", "100",
            ])
            if result.returncode != 0:
                return []

            items = json.loads(result.stdout) if result.stdout.strip() else []
            docs = []
            for item in items:
                file_rel = item.get("file", "")
                # file_rel is like "project_memories/{hash}/{id}.md"
                # we need to check if the {hash} directory matches
                parts = file_rel.split("/")
                if len(parts) >= 2 and parts[0] == QMD_COLLECTION and parts[1] == proj_hash:
                    fname = parts[-1]
                    if fname.endswith(".md"):
                        mem_id = fname[:-3]
                        body = item.get("body") or item.get("snippet") or ""
                        docs.append(QmdDoc(
                            memory_id=mem_id,
                            project_path=project_path,
                            title=item.get("title", mem_id),
                            content=body,
                            keywords=_extract_keywords(body),
                            score=float(item.get("score", 1.0)),
                        ))
            return docs
        except Exception as e:
            logger.warning("list_memories failed: %s", e)
            return []

    def search(self, query: str, project_path: str, limit: int = 5) -> list[QmdDoc]:
        """
        Hybrid search via qmd, filtered to one project.
        Returns list of QmdDoc sorted by relevance score (desc).
        """
        if not self.is_available():
            return []

        try:
            proj_hash = _proj_hash(project_path)
            result = self._qmd([
                "query", query,
                "--collection", QMD_COLLECTION,
                "--format", "json",
                "--full",
                "--limit", str(limit * 3),
            ], timeout=60)
            if result.returncode != 0:
                logger.warning("qmd search failed: %s", result.stderr.strip())
                return []

            items = json.loads(result.stdout) if result.stdout.strip() else []
            docs = []
            for item in items:
                file_rel = item.get("file", "")
                parts = file_rel.split("/")
                # Filter: must be in our collection and correct project hash dir
                if len(parts) < 3 or parts[0] != QMD_COLLECTION or parts[1] != proj_hash:
                    continue

                fname = parts[-1]
                if not fname.endswith(".md"):
                    continue
                mem_id = fname[:-3]
                body = item.get("body") or item.get("snippet") or ""

                # Extract title from first # heading if not provided
                title = item.get("title", "")
                if not title and body:
                    for line in body.split("\n"):
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break

                docs.append(QmdDoc(
                    memory_id=mem_id,
                    project_path=project_path,
                    title=title or mem_id,
                    content=body,
                    keywords=_extract_keywords(body),
                    score=float(item.get("score", 0.0)),
                ))

                if len(docs) >= limit:
                    break

            return docs
        except subprocess.TimeoutExpired:
            logger.warning("qmd search timed out")
            return []
        except Exception as e:
            logger.warning("qmd search failed: %s", e)
            return []

    def format_results(self, docs: list[QmdDoc]) -> str:
        """Format search results as readable text for MCP tool response."""
        if not docs:
            return "未找到相关记忆。"
        lines = [f"🔍 找到 {len(docs)} 条相关记忆\n"]
        for doc in docs:
            summary = doc.content[:200].replace("\n", " ")
            if len(doc.content) > 200:
                summary += "..."
            lines.append("")
            lines.append(f"**{doc.title}**")
            lines.append(f"  {summary}")
            lines.append(f"  相关度: {doc.score:.2f}  ID: `{doc.memory_id}`")
        return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape markdown special characters to prevent rendering issues."""
    return (
        text.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("#", "\\#")
            .replace("+", "\\+")
            .replace("-", "\\-")
            .replace(".", "\\.")
            .replace("!", "\\!")
            .replace("|", "\\|")
    )


def _extract_keywords(body: str) -> str:
    """Pull **Keywords**: value out of markdown body."""
    for line in body.split("\n"):
        if "**Keywords**" in line:
            return line.split("**Keywords**")[-1].strip()
    return ""


# Singleton
_qmd_adapter: Optional[QmdAdapter] = None
_qmd_adapter_lock = threading.Lock()


def get_qmd_adapter() -> QmdAdapter:
    global _qmd_adapter
    if _qmd_adapter is None:
        with _qmd_adapter_lock:
            if _qmd_adapter is None:  # 双重检查
                _qmd_adapter = QmdAdapter()
    return _qmd_adapter
