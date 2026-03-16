"""
运行时状态存储 - 持久化线程、后台任务和图状态快照

基于 SQLite，线程安全。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_threads (
    user_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_latest_tasks (
    user_id TEXT PRIMARY KEY,
    task_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foreground_operations (
    user_id TEXT PRIMARY KEY,
    action_label TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS background_tasks (
    task_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    is_remote INTEGER NOT NULL,
    status TEXT NOT NULL,
    log_file TEXT NOT NULL,
    pid INTEGER,
    exit_code INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_state (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass
class PersistedTask:
    task_id: str
    command: str
    started_at: str
    is_remote: bool
    status: str
    log_file: str
    pid: int | None = None
    exit_code: int | None = None


@dataclass
class PersistedForegroundOperation:
    user_id: str
    action_label: str
    chat_id: int
    message_id: int
    started_at: str


class RuntimeStateStore:
    """基于 sqlite 的轻量运行时状态存储。"""

    def __init__(self, state_dir: str | Path):
        self._state_dir = Path(state_dir).expanduser()
        self._db_path = self._state_dir / "runtime_state.sqlite3"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def from_config(cls, config) -> "RuntimeStateStore":
        """从任何含 state_dir 属性的 config 对象创建"""
        return cls(state_dir=config.state_dir)

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    def init_schema(self):
        with self._lock:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(SCHEMA_SQL)

    def get_thread_id(self, user_id: int) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT thread_id FROM session_threads WHERE user_id = ?",
                    (str(user_id),),
                ).fetchone()
        return row[0] if row else None

    def set_thread_id(self, user_id: int, thread_id: str):
        self._upsert(
            "session_threads",
            ("user_id", "thread_id", "updated_at"),
            (str(user_id), thread_id, self._now()),
            conflict_cols=("user_id",),
            update_cols=("thread_id", "updated_at"),
        )

    def get_latest_task(self, user_id: int) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT task_id FROM user_latest_tasks WHERE user_id = ?",
                    (str(user_id),),
                ).fetchone()
        return row[0] if row and row[0] else None

    def set_latest_task(self, user_id: int, task_id: str | None):
        self._upsert(
            "user_latest_tasks",
            ("user_id", "task_id", "updated_at"),
            (str(user_id), task_id, self._now()),
            conflict_cols=("user_id",),
            update_cols=("task_id", "updated_at"),
        )

    def save_foreground_operation(self, operation: PersistedForegroundOperation):
        self._upsert(
            "foreground_operations",
            ("user_id", "action_label", "chat_id", "message_id", "started_at", "updated_at"),
            (
                operation.user_id,
                operation.action_label,
                operation.chat_id,
                operation.message_id,
                operation.started_at,
                self._now(),
            ),
            conflict_cols=("user_id",),
            update_cols=("action_label", "chat_id", "message_id", "started_at", "updated_at"),
        )

    def load_foreground_operations(self) -> list[PersistedForegroundOperation]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT user_id, action_label, chat_id, message_id, started_at
                    FROM foreground_operations
                    ORDER BY started_at ASC
                    """
                ).fetchall()
        return [
            PersistedForegroundOperation(
                user_id=row[0],
                action_label=row[1],
                chat_id=int(row[2]),
                message_id=int(row[3]),
                started_at=row[4],
            )
            for row in rows
        ]

    def delete_foreground_operation(self, user_id: int):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM foreground_operations WHERE user_id = ?",
                    (str(user_id),),
                )
                conn.commit()

    def save_task(self, task: PersistedTask):
        self._upsert(
            "background_tasks",
            ("task_id", "command", "started_at", "is_remote", "status", "log_file", "pid", "exit_code", "updated_at"),
            (task.task_id, task.command, task.started_at, 1 if task.is_remote else 0, task.status, task.log_file, task.pid, task.exit_code, self._now()),
            conflict_cols=("task_id",),
            update_cols=("command", "started_at", "is_remote", "status", "log_file", "pid", "exit_code", "updated_at"),
        )

    def load_tasks(self) -> list[PersistedTask]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT task_id, command, started_at, is_remote, status, log_file, pid, exit_code
                    FROM background_tasks
                    ORDER BY started_at DESC
                    """
                ).fetchall()
        return [
            PersistedTask(
                task_id=row[0], command=row[1], started_at=row[2],
                is_remote=bool(row[3]), status=row[4], log_file=row[5],
                pid=row[6], exit_code=row[7],
            )
            for row in rows
        ]

    def save_blob(self, key: str, value: bytes):
        self._upsert(
            "kv_state",
            ("key", "value", "updated_at"),
            (key, sqlite3.Binary(value), self._now()),
            conflict_cols=("key",),
            update_cols=("value", "updated_at"),
        )

    def load_blob(self, key: str) -> bytes | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM kv_state WHERE key = ?", (key,),
                ).fetchone()
        return bytes(row[0]) if row else None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._conn

    def _upsert(
        self,
        table: str,
        columns: tuple[str, ...],
        values: tuple[Any, ...],
        conflict_cols: tuple[str, ...],
        update_cols: tuple[str, ...],
    ):
        placeholders = ", ".join(["?"] * len(columns))
        assignments = ", ".join(f"{col}=excluded.{col}" for col in update_cols)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    f"""
                    INSERT INTO {table} ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT ({", ".join(conflict_cols)}) DO UPDATE SET {assignments}
                    """,
                    values,
                )
                conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
