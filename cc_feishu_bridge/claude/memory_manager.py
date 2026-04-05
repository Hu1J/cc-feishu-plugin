"""Local memory store with SQLite FTS5 for Claude Code bridge."""
from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_TYPES = ("problem_solution", "project_context", "user_preference")

# Injected before user_preference + project_context to guide CC's memory behaviour
MEMORY_SYSTEM_GUIDE = """
【记忆系统使用指引】
遇到报错、构建失败、工具执行异常时，优先用 MemorySearch 搜索本地记忆库。
解决问题后主动问用户："需要记住吗？" 用户确认后用 MemoryAdd 写入。
用户说"记住 XXX"时，直接调用 MemoryAdd 写入。
"""

@dataclass
class MemoryEntry:
    type: str
    title: str
    solution: str
    problem: Optional[str] = None
    root_cause: Optional[str] = None
    tags: Optional[str] = None
    project_path: Optional[str] = None
    user_id: Optional[str] = None
    file_context: Optional[str] = None
    status: str = "active"
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_used_at: Optional[str] = None
    use_count: int = 0

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON serialization."""
        return asdict(self)


@dataclass
class MemorySearchResult:
    """A memory entry with its FTS search rank (lower = better match)."""
    entry: MemoryEntry
    rank: float  # FTS5 bm25 rank (lower = more relevant)


class MemoryManager:
    """SQLite+FTS5-backed memory manager."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base = Path.home() / ".cc-feishu-bridge"
            base.mkdir(exist_ok=True)
            db_path = str(base / "memories.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL CHECK(type IN (
                        'problem_solution','project_context','user_preference'
                    )),
                    status      TEXT NOT NULL DEFAULT 'active',
                    title       TEXT NOT NULL,
                    problem     TEXT,
                    root_cause  TEXT,
                    solution    TEXT NOT NULL,
                    tags        TEXT,
                    project_path TEXT,
                    user_id     TEXT,
                    file_context TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count   INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id UNINDEXED,
                    title, problem, root_cause, solution, tags
                )
            """)

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add a memory entry and index it in FTS.

        - problem_solution: always global (project_path=NULL)
        - user_preference: always global (project_path=NULL)
        - project_context: project-scoped (keep given project_path)
        """
        data = asdict(entry)
        if isinstance(data.get("tags"), list):
            data["tags"] = ",".join(data["tags"])
        if entry.type in ("problem_solution", "user_preference"):
            data["project_path"] = None  # always global
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO memories
                (id, type, status, title, problem, root_cause, solution, tags,
                 project_path, user_id, file_context, created_at, updated_at,
                 last_used_at, use_count)
                VALUES (:id, :type, :status, :title, :problem, :root_cause,
                        :solution, :tags, :project_path, :user_id, :file_context,
                        :created_at, :updated_at, :last_used_at, :use_count)
            """, data)
            conn.execute(
                "INSERT INTO memories_fts(id, title, problem, root_cause, solution, tags) VALUES (?, ?, ?, ?, ?, ?)",
                (entry.id, entry.title, entry.problem or "", entry.root_cause or "",
                 entry.solution, ",".join(entry.tags) if isinstance(entry.tags, list) else (entry.tags or ""))
            )
        return entry

    def search(
        self,
        query: str,
        project_path: Optional[str] = None,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        Full-text search via FTS5:
        - problem_solution + user_preference: always searched globally
        - project_context: scoped to current project

        Returns results with FTS rank so callers can assess match quality.
        """
        if not query.strip():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Fetch problem_solution globally
            ps_rows = conn.execute("""
                SELECT m.*, bm25(memories_fts) as rank
                FROM memories_fts
                JOIN memories m ON memories_fts.id = m.id
                WHERE memories_fts MATCH ?
                  AND m.status = 'active'
                  AND m.type = 'problem_solution'
                ORDER BY m.use_count DESC, rank
                LIMIT ?
            """, (query, limit)).fetchall()

            # Fetch user_preference globally (always shared across projects)
            up_rows = conn.execute("""
                SELECT m.*, bm25(memories_fts) as rank
                FROM memories_fts
                JOIN memories m ON memories_fts.id = m.id
                WHERE memories_fts MATCH ?
                  AND m.status = 'active'
                  AND m.type = 'user_preference'
                ORDER BY m.use_count DESC, rank
                LIMIT ?
            """, (query, limit)).fetchall()

            # Fetch project_context scoped to current project
            pc_rows = []
            if project_path:
                pc_rows = conn.execute("""
                    SELECT m.*, bm25(memories_fts) as rank
                    FROM memories_fts
                    JOIN memories m ON memories_fts.id = m.id
                    WHERE memories_fts MATCH ?
                      AND m.status = 'active'
                      AND m.type = 'project_context'
                      AND m.project_path = ?
                    ORDER BY m.use_count DESC, rank
                    LIMIT ?
                """, (query, project_path, limit)).fetchall()

            # Merge: problem_solution → user_preference → project_context
            rows = ps_rows + up_rows + pc_rows
            if not rows:
                return []

            # Build rank map {id: rank} before the use_count update wipes it
            rank_map = {dict(r)["id"]: dict(r)["rank"] for r in rows}
            ids = list(rank_map.keys())

            # Update use_count for all matched entries
            conn.execute(
                "UPDATE memories SET use_count = use_count + 1, last_used_at = ? "
                "WHERE id IN (" + ",".join("?" * len(ids)) + ")",
                (datetime.utcnow().isoformat(), *ids)
            )

        # Re-fetch entries and pair with preserved ranks
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Build CASE expression to preserve original bm25 ranking order
            case_expr = "CASE id " + "".join(f"WHEN '{rid}' THEN {i} " for i, rid in enumerate(ids)) + "END"
            entries = conn.execute(
                f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(ids))}) "
                f"ORDER BY {case_expr}",
                ids
            ).fetchall()

        results = []
        for row in entries:
            entry = MemoryEntry(**dict(row))
            rank = rank_map.get(entry.id, 0.0)
            results.append(MemorySearchResult(entry=entry, rank=rank))
        return results

    def get_by_project(
        self,
        project_path: str,
        type_filter: list[str] | None = None,
    ) -> list[MemoryEntry]:
        """
        Get all active memories for a project (including global ones).
        If type_filter is given, only return memories of those types.
        """
        if type_filter is None:
            type_filter = ["project_context", "user_preference"]

        user_pref_globally = "user_preference" in type_filter
        proj_ctx_locally   = "project_context" in type_filter

        conditions = []
        params: list = []

        if user_pref_globally:
            conditions.append("(type = 'user_preference' AND project_path IS NULL)")
        if proj_ctx_locally:
            conditions.append("(type = 'project_context' AND (project_path = ? OR project_path IS NULL))")
            params.append(project_path)

        where_clause = " OR ".join(conditions) if conditions else "0"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT * FROM memories
                WHERE status = 'active'
                  AND ({where_clause})
                ORDER BY use_count DESC, created_at DESC
            """, params).fetchall()
        return [MemoryEntry(**dict(row)) for row in rows]

    def delete(self, memory_id: str) -> bool:
        """Soft-delete a memory entry."""
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute(
                "UPDATE memories SET status='deleted' WHERE id = ?",
                (memory_id,)
            ).rowcount
        return affected > 0

    def inject_context(
        self,
        project_path: str,
        type_filter: list[str] | None = None,
    ) -> str:
        """
        Build a memory context string for passive injection into prompts.
        Only user_preference and project_context are injected here;
        problem_solution entries are retrieved on-demand via search().
        """
        if project_path is None:
            return ""
        entries = self.get_by_project(project_path, type_filter=type_filter)
        if not entries:
            return ""

        lines = ["\n【项目记忆]", "---"]
        for e in entries:
            type_label = {"project_context": "📁", "user_preference": "👤"}.get(e.type, "💡")
            lines.append(f"{type_label} **{e.title}**")
            if e.problem:
                lines.append(f"  问题: {e.problem}")
            if e.solution:
                lines.append(f"  解决: {e.solution}")
            if e.root_cause:
                lines.append(f"  根因: {e.root_cause}")
            lines.append("")
        return "\n".join(lines)