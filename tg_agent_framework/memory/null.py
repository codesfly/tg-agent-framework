"""
空记忆实现 — 适用于不需要事件存储的 Agent
"""

from __future__ import annotations

from typing import Any

from tg_agent_framework.memory.base import BaseMemory
from tg_agent_framework.memory.types import MemoryRecord, MemoryScope


class NullMemory(BaseMemory):
    """空实现，所有操作静默忽略"""

    async def record_event(self, event_type: str, description: str, **kwargs) -> None:
        pass

    async def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        return []

    async def upsert_memory(self, record: MemoryRecord) -> str:
        return record.memory_id

    async def list_memories(
        self,
        scope: MemoryScope,
        *,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        return []

    async def delete_memory(self, memory_id: str) -> bool:
        return False

    async def summarize_scope(self, scope: MemoryScope) -> str | None:
        return None
