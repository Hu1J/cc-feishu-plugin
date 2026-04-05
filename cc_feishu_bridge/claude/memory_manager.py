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
        """Add a memory entry and index it in FTS."""
        data = asdict(entry)
        if isinstance(data.get("tags"), list):
            data["tags"] = ",".join(data["tags"])
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
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        if not query.strip():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Fetch results with bm25 ranking
            sql = """
                SELECT m.*, bm25(memories_fts) as rank
                FROM memories_fts
                JOIN memories m ON memories_fts.id = m.id
                WHERE memories_fts MATCH ?
                  AND m.status = 'active'
                  AND (m.project_path IS NULL OR m.project_path = ?)
                ORDER BY m.use_count DESC, rank
                LIMIT ?
            """
            rows = conn.execute(sql, (query, project_path or "", limit)).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            # Build CASE expression to preserve original bm25 ranking order after UPDATE
            case_expr = "CASE id " + "".join(f"WHEN '{rid}' THEN {i} " for i, rid in enumerate(ids)) + "END"
            conn.execute(
                "UPDATE memories SET use_count = use_count + 1, last_used_at = ? "
                "WHERE id IN (" + ",".join("?" * len(ids)) + ")",
                (datetime.utcnow().isoformat(), *ids)
            )
            # Re-fetch with ORDER BY CASE to preserve bm25 ranking
            rows = conn.execute(
                f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(ids))}) "
                f"ORDER BY {case_expr}",
                ids
            ).fetchall()
        return [MemoryEntry(**{k: v for k, v in dict(row).items() if k != "rank"}) for row in rows]

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
            type_filter = ["user_preference", "project_context"]
        placeholders = ",".join("?" * len(type_filter))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT * FROM memories
                WHERE status = 'active'
                  AND type IN ({placeholders})
                  AND (project_path IS NULL OR project_path = ?)
                ORDER BY use_count DESC, created_at DESC
            """, (*type_filter, project_path)).fetchall()
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