"""
SQLite 长期记忆实现。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from tg_agent_framework.memory.base import BaseMemory
from tg_agent_framework.memory.types import MemoryRecord, MemoryScope

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (namespace, memory_id)
);

CREATE INDEX IF NOT EXISTS idx_memories_scope_kind_updated
ON memories (namespace, scope_type, scope_id, kind, updated_at DESC);
"""


class SqliteLongTermMemory(BaseMemory):
    def __init__(self, state_dir: str | Path, namespace: str | None = None):
        self._state_dir = Path(state_dir).expanduser()
        self._db_path = self._state_dir / "memory_store.sqlite3"
        self._namespace = self._normalize_namespace(namespace)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def from_config(cls, config) -> "SqliteLongTermMemory":
        return cls(
            state_dir=config.state_dir,
            namespace=getattr(config, "state_namespace", None),
        )

    async def init_schema(self) -> None:
        with self._lock:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.commit()

    async def upsert_memory(self, record: MemoryRecord) -> str:
        memory_id = record.memory_id or uuid.uuid4().hex
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    """
                    SELECT created_at
                    FROM memories
                    WHERE namespace = ? AND memory_id = ?
                    """,
                    (self._namespace, memory_id),
                ).fetchone()
                created_at = existing[0] if existing else record.created_at
                conn.execute(
                    """
                    INSERT INTO memories (
                        memory_id, namespace, scope_type, scope_id, kind, content,
                        metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(namespace, memory_id) DO UPDATE SET
                        scope_type=excluded.scope_type,
                        scope_id=excluded.scope_id,
                        kind=excluded.kind,
                        content=excluded.content,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        memory_id,
                        self._namespace,
                        record.scope.scope_type,
                        record.scope.scope_id,
                        record.kind,
                        record.content,
                        json.dumps(record.metadata, ensure_ascii=True, sort_keys=True),
                        created_at,
                        record.updated_at,
                    ),
                )
                conn.commit()
        return memory_id

    async def list_memories(
        self,
        scope: MemoryScope,
        *,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        query = [
            """
            SELECT memory_id, scope_type, scope_id, kind, content, metadata_json, created_at, updated_at
            FROM memories
            WHERE namespace = ? AND scope_type = ? AND scope_id = ?
            """
        ]
        params: list[object] = [self._namespace, scope.scope_type, scope.scope_id]
        if kind is not None:
            query.append("AND kind = ?")
            params.append(kind)
        query.append("ORDER BY updated_at DESC, rowid DESC LIMIT ?")
        params.append(limit)

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM memories WHERE namespace = ? AND memory_id = ?",
                    (self._namespace, memory_id),
                )
                conn.commit()
        return cursor.rowcount > 0

    async def summarize_scope(self, scope: MemoryScope) -> str | None:
        summaries = await self.list_memories(scope, kind="summary", limit=1)
        return summaries[0].content if summaries else None

    async def record_event(
        self,
        event_type: str,
        description: str,
        *,
        service: str = "",
        triggered_by: str = "",
        metadata: dict | None = None,
    ) -> None:
        await self.upsert_memory(
            MemoryRecord(
                scope=MemoryScope.global_scope(),
                kind="event",
                content=description,
                metadata={
                    "event_type": event_type,
                    "service": service,
                    "triggered_by": triggered_by,
                    "metadata": metadata or {},
                },
            )
        )

    async def get_recent_events(self, limit: int = 20) -> list[dict]:
        events = await self.list_memories(MemoryScope.global_scope(), kind="event", limit=limit)
        results: list[dict] = []
        for event in events:
            meta = event.metadata
            results.append(
                {
                    "event_type": meta.get("event_type", ""),
                    "description": event.content,
                    "service": meta.get("service", ""),
                    "triggered_by": meta.get("triggered_by", ""),
                    "metadata": meta.get("metadata", {}),
                    "created_at": event.created_at,
                    "updated_at": event.updated_at,
                }
            )
        return results

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._conn

    @staticmethod
    def _row_to_record(row: tuple) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row[0],
            scope=MemoryScope(scope_type=row[1], scope_id=row[2]),
            kind=row[3],
            content=row[4],
            metadata=json.loads(row[5]),
            created_at=row[6],
            updated_at=row[7],
        )

    @staticmethod
    def _normalize_namespace(value: str | None) -> str:
        if not value:
            value = "default"
        compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        compact = compact.strip("-.")
        return compact or "default"
