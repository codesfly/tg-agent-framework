"""
运行时状态存储 - 持久化线程、前台操作和图状态快照

基于 SQLite，线程安全。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3

FOREGROUND_STATUS_RUNNING = "running"
FOREGROUND_STATUS_AWAITING_APPROVAL = "awaiting_approval"
FOREGROUND_STATUS_CANCELLING = "cancelling"
FOREGROUND_STATUS_TIMED_OUT = "timed_out"
FOREGROUND_STATUS_INTERRUPTED = "interrupted"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_threads (
    user_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foreground_operations (
    user_id TEXT PRIMARY KEY,
    action_label TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT '',
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_state (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass
class PersistedForegroundOperation:
    user_id: str
    action_label: str
    chat_id: int
    message_id: int
    started_at: str
    thread_id: str = ""
    status: str = FOREGROUND_STATUS_RUNNING


class RuntimeStateStore:
    """基于 sqlite 的轻量运行时状态存储。"""

    def __init__(self, state_dir: str | Path, namespace: str | None = None):
        self._state_dir = Path(state_dir).expanduser()
        self._db_path = self._state_dir / "runtime_state.sqlite3"
        self._namespace = self._normalize_namespace(namespace)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def from_config(cls, config) -> "RuntimeStateStore":
        """从任何含 state_dir 属性的 config 对象创建"""
        return cls(
            state_dir=config.state_dir,
            namespace=getattr(config, "state_namespace", None),
        )

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    @property
    def namespace(self) -> str:
        return self._namespace

    def init_schema(self):
        with self._lock:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(SCHEMA_SQL)
                self._apply_migrations(conn)
                self._set_metadata(conn, "schema_version", str(SCHEMA_VERSION))
                if self._get_metadata(conn, "created_at") is None:
                    self._set_metadata(conn, "created_at", self._now())

    def get_schema_version(self) -> int:
        with self._lock:
            with self._connect() as conn:
                raw = self._get_metadata(conn, "schema_version")
        return int(raw) if raw and raw.isdigit() else 0

    def validate_integrity(self) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"

    def get_thread_id(self, user_id: int) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT thread_id FROM session_threads WHERE user_id = ?",
                    (self._scope_user_id(user_id),),
                ).fetchone()
        return row[0] if row else None

    def set_thread_id(self, user_id: int, thread_id: str):
        self._upsert(
            "session_threads",
            ("user_id", "thread_id", "updated_at"),
            (self._scope_user_id(user_id), thread_id, self._now()),
            conflict_cols=("user_id",),
            update_cols=("thread_id", "updated_at"),
        )

    def save_foreground_operation(self, operation: PersistedForegroundOperation):
        self._upsert(
            "foreground_operations",
            (
                "user_id",
                "action_label",
                "thread_id",
                "chat_id",
                "message_id",
                "started_at",
                "status",
                "updated_at",
            ),
            (
                self._scope_user_id(operation.user_id),
                operation.action_label,
                operation.thread_id,
                operation.chat_id,
                operation.message_id,
                operation.started_at,
                operation.status,
                self._now(),
            ),
            conflict_cols=("user_id",),
            update_cols=(
                "action_label",
                "thread_id",
                "chat_id",
                "message_id",
                "started_at",
                "status",
                "updated_at",
            ),
        )

    def load_foreground_operations(self) -> list[PersistedForegroundOperation]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT user_id, thread_id, action_label, chat_id, message_id, started_at, status
                    FROM foreground_operations
                    WHERE substr(user_id, 1, ?) = ?
                    ORDER BY started_at ASC
                    """,
                    (len(self._scope_prefix()), self._scope_prefix()),
                ).fetchall()
        return [
            PersistedForegroundOperation(
                user_id=self._unscope(row[0]),
                action_label=row[2],
                chat_id=int(row[3]),
                message_id=int(row[4]),
                started_at=row[5],
                thread_id=row[1],
                status=row[6],
            )
            for row in rows
        ]

    def delete_foreground_operation(self, user_id: int | str):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM foreground_operations WHERE user_id = ?",
                    (self._scope_user_id(user_id),),
                )
                conn.commit()

    def save_blob(self, key: str, value: bytes):
        self._upsert(
            "kv_state",
            ("key", "value", "updated_at"),
            (self._scope_key(key), sqlite3.Binary(value), self._now()),
            conflict_cols=("key",),
            update_cols=("value", "updated_at"),
        )

    def load_blob(self, key: str) -> bytes | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM kv_state WHERE key = ?",
                    (self._scope_key(key),),
                ).fetchone()
        return bytes(row[0]) if row else None

    def delete_blob(self, key: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM kv_state WHERE key = ?", (self._scope_key(key),))
                conn.commit()

    def list_blob_keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT key
                    FROM kv_state
                    WHERE substr(key, 1, ?) = ?
                    ORDER BY key ASC
                    """,
                    (len(self._scope_prefix()), self._scope_prefix()),
                ).fetchall()
        keys = [self._unscope(row[0]) for row in rows]
        if not prefix:
            return keys
        return [key for key in keys if key.startswith(prefix)]

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._conn

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        columns = self._get_table_columns(conn, "foreground_operations")
        if "thread_id" not in columns:
            conn.execute(
                "ALTER TABLE foreground_operations ADD COLUMN thread_id TEXT NOT NULL DEFAULT ''"
            )
        if "status" not in columns:
            conn.execute(
                "ALTER TABLE foreground_operations ADD COLUMN status TEXT NOT NULL DEFAULT 'running'"
            )
        conn.commit()

    def _get_table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
            raise ValueError(f"非法的表名: {table!r}")
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}

    def _get_metadata(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT value FROM runtime_metadata WHERE key = ?",
            (key,),
        ).fetchone()
        return row[0] if row else None

    def _set_metadata(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO runtime_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, self._now()),
        )
        conn.commit()

    def _scope_user_id(self, user_id: int | str) -> str:
        return self._scope_key(str(user_id))

    def _scope_key(self, value: str) -> str:
        return f"{self._scope_prefix()}{value}"

    def _scope_prefix(self) -> str:
        return f"{self._namespace}:"

    def _unscope(self, value: str) -> str:
        prefix = self._scope_prefix()
        return value[len(prefix) :] if value.startswith(prefix) else value

    _SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _upsert(
        self,
        table: str,
        columns: tuple[str, ...],
        values: tuple[Any, ...],
        conflict_cols: tuple[str, ...],
        update_cols: tuple[str, ...],
    ):
        # 防止 SQL 注入：校验表名和列名
        for ident in (table, *columns, *conflict_cols, *update_cols):
            if not self._SAFE_IDENT_RE.match(ident):
                raise ValueError(f"非法的 SQL 标识符: {ident!r}")
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
        return datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _normalize_namespace(value: str | None) -> str:
        if not value:
            value = Path.cwd().resolve().name
        compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        compact = compact.strip("-.")
        return compact or "default"
