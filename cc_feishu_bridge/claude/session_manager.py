"""SQLite-based session manager for Claude Code conversations."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    sdk_session_id: str | None
    user_id: str
    project_path: str
    created_at: datetime
    last_used: datetime
    total_cost: float
    message_count: int
    chat_id: str | None = None   # 新增：最近活跃的飞书 chat_id


class SessionManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    sdk_session_id TEXT,
                    user_id TEXT NOT NULL,
                    project_path TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    last_used TIMESTAMP NOT NULL,
                    total_cost REAL DEFAULT 0,
                    message_count INTEGER DEFAULT 0
                )
            """)
            # Migrate: add sdk_session_id column if it doesn't exist (existing installs)
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN sdk_session_id TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
            # Migrate: add chat_id column if it doesn't exist (existing installs)
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN chat_id TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_last
                ON sessions(user_id, last_used DESC)
            """)

    def create_session(self, user_id: str, project_path: str, sdk_session_id: str | None = None) -> Session:
        """Create a new session for a user."""
        now = datetime.utcnow()
        session = Session(
            session_id=f"session_{now.strftime('%Y%m%d%H%M%S')}",
            sdk_session_id=sdk_session_id,
            user_id=user_id,
            project_path=project_path,
            created_at=now,
            last_used=now,
            total_cost=0.0,
            message_count=0,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, sdk_session_id, user_id, chat_id, project_path, created_at, last_used, total_cost, message_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.session_id,
                    session.sdk_session_id,
                    session.user_id,
                    "",   # chat_id 初始为空字符串
                    session.project_path,
                    session.created_at.isoformat(),
                    session.last_used.isoformat(),
                    session.total_cost,
                    session.message_count,
                ),
            )
        return session

    def get_active_session(self, user_id: str) -> Optional[Session]:
        """Get the most recent session for a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM sessions
                   WHERE user_id = ?
                   ORDER BY last_used DESC
                   LIMIT 1""",
                (user_id,),
            ).fetchone()
        if row:
            return Session(
                session_id=row["session_id"],
                sdk_session_id=row["sdk_session_id"],
                user_id=row["user_id"],
                chat_id=row["chat_id"],
                project_path=row["project_path"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_used=datetime.fromisoformat(row["last_used"]),
                total_cost=row["total_cost"],
                message_count=row["message_count"],
            )
        return None

    def update_session(
        self,
        session_id: str,
        cost: float = 0,
        message_increment: int = 0,
    ):
        """Update session stats after a conversation turn."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE sessions
                   SET last_used = ?,
                       total_cost = total_cost + ?,
                       message_count = message_count + ?
                   WHERE session_id = ?""",
                (datetime.utcnow().isoformat(), cost, message_increment, session_id),
            )

    def update_sdk_session_id(self, session_id: str, sdk_session_id: str) -> None:
        """Store the SDK's session ID for future continue_session calls."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE sessions SET sdk_session_id = ? WHERE session_id = ?""",
                (sdk_session_id, session_id),
            )

    def delete_session(self, session_id: str):
        """Delete a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def get_active_session_by_chat_id(self) -> Optional[Session]:
        """Get the most recent session that has a chat_id set."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM sessions
                   WHERE chat_id IS NOT NULL AND chat_id != ''
                   ORDER BY last_used DESC
                   LIMIT 1""",
            ).fetchone()
            if row:
                return Session(
                    session_id=row["session_id"],
                    sdk_session_id=row["sdk_session_id"],
                    user_id=row["user_id"],
                    chat_id=row["chat_id"],
                    project_path=row["project_path"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_used=datetime.fromisoformat(row["last_used"]),
                    total_cost=row["total_cost"],
                    message_count=row["message_count"],
                )
            return None

    def update_chat_id(self, user_id: str, chat_id: str) -> None:
        """Update the chat_id for the most recent session of a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE sessions
                   SET chat_id = ?
                   WHERE session_id = (
                       SELECT session_id FROM sessions
                       WHERE user_id = ?
                       ORDER BY last_used DESC
                       LIMIT 1
                   )""",
                (chat_id, user_id),
            )