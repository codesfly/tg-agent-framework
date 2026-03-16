"""
空记忆实现 — 适用于不需要事件存储的 Agent
"""

from __future__ import annotations

from typing import Any

from tg_agent_framework.memory.base import BaseMemory


class NullMemory(BaseMemory):
    """空实现，所有操作静默忽略"""

    async def record_event(self, event_type: str, description: str, **kwargs) -> None:
        pass

    async def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        return []
