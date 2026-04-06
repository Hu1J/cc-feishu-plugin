"""Local memory store with SQLite FTS5 for Claude Code bridge."""
from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import jieba

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> str:
    """用 jieba 分词，返回空格分隔的词串。"""
    return " ".join(jieba.cut(text))


MEMORY_SYSTEM_GUIDE = """
【记忆系统使用指引】
写代码、部署、调试、执行工具等遇到问题时搜索记忆：
- 优先用 MemorySearchProj，按 keywords 搜索项目记忆
- 搜索没有相关记忆，自己研究解决，成功后用 MemoryAddProj 新增项目记忆

解决某个问题后：主动问"xxx解决方案，需要记住吗？" 确认后写入 MemoryAddProj
平时用户说"记住 XXX" → 根据内容判断用 MemoryAddProj 或 MemoryAddUser
关键词统一用逗号分隔（若有多个）。

各工具触发场景：
- MemoryAddProj / MemoryAddUser — 新增记忆
- MemoryDeleteProj / MemoryDeleteUser — 删除记忆
- MemoryUpdateProj / MemoryUpdateUser — 编辑记忆
- MemoryListProj / MemoryListUser — 列出记忆
- MemorySearchProj / MemorySearchUser — 搜索记忆
"""


@dataclass
class UserPreference:
    """用户偏好条目（按飞书用户隔离）"""
    id: str
    user_open_id: str
    title: str
    content: str
    keywords: str  # 逗号分隔
    created_at: str
    updated_at: str


@dataclass
class ProjectMemory:
    """项目记忆条目（按项目隔离）"""
    id: str
    project_path: str
    title: str
    content: str
    keywords: str  # 逗号分隔
    created_at: str
    updated_at: str


@dataclass
class MemorySearchResult:
    """记忆搜索结果"""
    memory: ProjectMemory
    rank: float  # FTS5 bm25 rank


class MemoryManager:
    """SQLite+FTS5 双表记忆管理器"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base = Path.home() / ".cc-feishu-bridge"
            base.mkdir(exist_ok=True)
            db_path = str(base / "memories.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """创建/升级数据库：新建表或迁移已有表"""
        with sqlite3.connect(self.db_path) as conn:
            # ── user_preferences ──────────────────────────────────────────────────
            pref_cols = [r[1] for r in conn.execute("PRAGMA table_info(user_preferences)")]
            if not pref_cols:
                # 新表：包含 user_open_id
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        id           TEXT PRIMARY KEY,
                        user_open_id TEXT NOT NULL,
                        title        TEXT NOT NULL,
                        content      TEXT NOT NULL,
                        keywords     TEXT NOT NULL,
                        created_at   TEXT NOT NULL,
                        updated_at   TEXT NOT NULL
                    )
                """)
            elif "user_open_id" not in pref_cols:
                # 迁移：旧表没有 user_open_id，加列
                conn.execute("ALTER TABLE user_preferences ADD COLUMN user_open_id TEXT NOT NULL DEFAULT ''")
                logger.info("migrated user_preferences: added user_open_id column")

            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS user_preferences_fts USING fts5(
                    id UNINDEXED, title, content, keywords, tokenize='unicode61'
                )
            """)

            # ── project_memories ─────────────────────────────────────────────────
            proj_cols = [r[1] for r in conn.execute("PRAGMA table_info(project_memories)")]
            if not proj_cols:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS project_memories (
                        id           TEXT PRIMARY KEY,
                        project_path TEXT NOT NULL,
                        title        TEXT NOT NULL,
                        content      TEXT NOT NULL,
                        keywords     TEXT NOT NULL,
                        created_at   TEXT NOT NULL,
                        updated_at   TEXT NOT NULL
                    )
                """)

            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS project_memories_fts USING fts5(
                    id UNINDEXED, title, content, keywords, tokenize='unicode61'
                )
            """)

    # ── 用户偏好 ───────────────────────────────────────────────────────────────

    def add_preference(
        self,
        user_open_id: str,
        title: str,
        content: str,
        keywords: str,
    ) -> UserPreference:
        """添加一条用户偏好（按飞书用户隔离）"""
        now = datetime.utcnow().isoformat()
        pref = UserPreference(
            id=str(uuid.uuid4())[:8],
            user_open_id=user_open_id,
            title=title,
            content=content,
            keywords=keywords,
            created_at=now,
            updated_at=now,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO user_preferences (id, user_open_id, title, content, keywords, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pref.id, pref.user_open_id, pref.title, pref.content,
                 pref.keywords, pref.created_at, pref.updated_at)
            )
            conn.execute(
                "INSERT INTO user_preferences_fts(id, title, content, keywords) VALUES (?, ?, ?, ?)",
                (pref.id, _tokenize(pref.title),
                 _tokenize(f"{pref.title} {pref.content} {pref.keywords}"),
                 _tokenize(pref.keywords))
            )
        return pref

    def get_all_preferences(self) -> list[UserPreference]:
        """获取所有用户偏好（按创建时间倒序）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM user_preferences ORDER BY created_at DESC"
            ).fetchall()
        return [UserPreference(**{k: v for k, v in dict(r).items() if k != "_rank"}) for r in rows]

    def get_preferences_by_user(self, user_open_id: str) -> list[UserPreference]:
        """获取指定用户的所有偏好（按创建时间倒序）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM user_preferences WHERE user_open_id = ? ORDER BY created_at DESC",
                (user_open_id,)
            ).fetchall()
        return [UserPreference(**{k: v for k, v in dict(r).items() if k != "_rank"}) for r in rows]

    def search_preferences(
        self,
        query: str,
        user_open_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[UserPreference]:
        """
        全文搜索用户偏好：按 user_open_id 过滤，keywords 优先（prefix 匹配），无结果再搜 title + content。
        """
        if not query.strip():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            keywords_query = _tokenize(query)

            base_cols = "m.id, m.user_open_id, m.title, m.content, m.keywords, m.created_at, m.updated_at"

            def _run(query_str: str):
                if user_open_id:
                    return conn.execute(
                        f"SELECT {base_cols}, bm25(user_preferences_fts) as _rank "
                        "FROM user_preferences_fts "
                        "JOIN user_preferences m ON user_preferences_fts.id = m.id "
                        "WHERE user_preferences_fts MATCH ? AND m.user_open_id = ? "
                        "ORDER BY _rank LIMIT ?",
                        (query_str, user_open_id, limit)
                    ).fetchall()
                else:
                    return conn.execute(
                        f"SELECT {base_cols}, bm25(user_preferences_fts) as _rank "
                        "FROM user_preferences_fts "
                        "JOIN user_preferences m ON user_preferences_fts.id = m.id "
                        "WHERE user_preferences_fts MATCH ? ORDER BY _rank LIMIT ?",
                        (query_str, limit)
                    ).fetchall()

            rows = _run(keywords_query)
            if not rows:
                rows = _run(keywords_query)
        return [UserPreference(**{k: v for k, v in dict(r).items() if k != "_rank"}) for r in rows]

    def update_preference(
        self,
        pref_id: str,
        title: str,
        content: str,
        keywords: str,
    ) -> bool:
        """更新一条用户偏好"""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute("""
                UPDATE user_preferences
                SET title=?, content=?, keywords=?, updated_at=?
                WHERE id=?
            """, (title, content, keywords, now, pref_id)).rowcount
            if affected > 0:
                conn.execute(
                    "DELETE FROM user_preferences_fts WHERE id = ?", (pref_id,)
                )
                conn.execute(
                    "INSERT INTO user_preferences_fts(id, title, content, keywords) VALUES (?, ?, ?, ?)",
                    (pref_id, _tokenize(title),
                     _tokenize(f"{title} {content} {keywords}"),
                     _tokenize(keywords))
                )
        return affected > 0

    def delete_preference(self, pref_id: str) -> bool:
        """删除一条用户偏好"""
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute(
                "DELETE FROM user_preferences WHERE id = ?", (pref_id,)
            ).rowcount
            conn.execute("DELETE FROM user_preferences_fts WHERE id = ?", (pref_id,))
        return affected > 0

    def inject_context(
        self,
        user_open_id: str,
        project_path: Optional[str] = None,
    ) -> str:
        """
        注入指定用户的偏好到 prompt（按 user_open_id 过滤，全量返回）。
        """
        prefs = self.get_preferences_by_user(user_open_id)
        if not prefs:
            return ""
        lines = ["\n【用户偏好】", "---"]
        for p in prefs:
            lines.append(f"**{p.title}**")
            lines.append(f"{p.content}")
            lines.append("")
        return "\n".join(lines)

    # ── 项目记忆 ───────────────────────────────────────────────────────────────

    def add_project_memory(
        self,
        project_path: str,
        title: str,
        content: str,
        keywords: str,
    ) -> ProjectMemory:
        """添加一条项目记忆（按项目隔离）"""
        now = datetime.utcnow().isoformat()
        mem = ProjectMemory(
            id=str(uuid.uuid4())[:8],
            project_path=project_path,
            title=title,
            content=content,
            keywords=keywords,
            created_at=now,
            updated_at=now,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO project_memories (id, project_path, title, content, keywords, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mem.id, mem.project_path, mem.title, mem.content, mem.keywords, mem.created_at, mem.updated_at)
            )
            conn.execute(
                "INSERT INTO project_memories_fts(id, title, content, keywords) VALUES (?, ?, ?, ?)",
                (mem.id, _tokenize(mem.title),
                 _tokenize(f"{mem.title} {mem.content} {mem.keywords}"),
                 _tokenize(mem.keywords))
            )
        return mem

    def search_project_memories(
        self,
        query: str,
        project_path: str,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        按项目搜索项目记忆：keywords 优先（前缀匹配），无结果再搜 title + content。
        """
        if not query.strip() or not project_path:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # 第一步：只搜 keywords（前缀匹配，兼容中文）
            keywords_query = _tokenize(query)
            rows = conn.execute(f"""
                SELECT m.*, bm25(project_memories_fts) as rank
                FROM project_memories_fts
                JOIN project_memories m ON project_memories_fts.id = m.id
                WHERE project_memories_fts MATCH ?
                  AND m.project_path = ?
                ORDER BY rank
                LIMIT ?
            """, (keywords_query, project_path, limit)).fetchall()
            # 第二步：keywords 无结果，再搜 title + content（分词后匹配）
            if not rows:
                fallback_query = _tokenize(query)
                rows = conn.execute(f"""
                    SELECT m.*, bm25(project_memories_fts) as rank
                    FROM project_memories_fts
                    JOIN project_memories m ON project_memories_fts.id = m.id
                    WHERE project_memories_fts MATCH ?
                      AND m.project_path = ?
                    ORDER BY rank
                    LIMIT ?
                """, (fallback_query, project_path, limit)).fetchall()
        results = []
        for row in rows:
            mem = ProjectMemory(
                id=row["id"],
                project_path=row["project_path"],
                title=row["title"],
                content=row["content"],
                keywords=row["keywords"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            results.append(MemorySearchResult(memory=mem, rank=row["rank"]))
        return results

    def get_project_memories(self, project_path: str) -> list[ProjectMemory]:
        """列出某项目下所有记忆（按创建时间倒序）"""
        if not project_path:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM project_memories
                WHERE project_path = ?
                ORDER BY created_at DESC
            """, (project_path,)).fetchall()
        return [
            ProjectMemory(
                id=row["id"],
                project_path=row["project_path"],
                title=row["title"],
                content=row["content"],
                keywords=row["keywords"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def update_project_memory(
        self,
        memory_id: str,
        title: str,
        content: str,
        keywords: str,
    ) -> bool:
        """更新一条项目记忆"""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute("""
                UPDATE project_memories
                SET title=?, content=?, keywords=?, updated_at=?
                WHERE id=?
            """, (title, content, keywords, now, memory_id)).rowcount
            if affected > 0:
                conn.execute(
                    "DELETE FROM project_memories_fts WHERE id = ?", (memory_id,)
                )
                conn.execute(
                    "INSERT INTO project_memories_fts(id, title, content, keywords) VALUES (?, ?, ?, ?)",
                    (memory_id, _tokenize(title),
                     _tokenize(f"{title} {content} {keywords}"),
                     _tokenize(keywords))
                )
        return affected > 0

    def delete_project_memory(self, memory_id: str) -> bool:
        """删除一条项目记忆"""
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute(
                "DELETE FROM project_memories WHERE id = ?", (memory_id,)
            ).rowcount
            conn.execute("DELETE FROM project_memories_fts WHERE id = ?", (memory_id,))
        return affected > 0

    def clear_project_memories(self, project_path: str) -> int:
        """清空某项目下所有记忆"""
        if not project_path:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM project_memories WHERE project_path = ?",
                (project_path,)
            ).fetchone()[0]
            conn.execute("DELETE FROM project_memories WHERE project_path = ?", (project_path,))
        return count
