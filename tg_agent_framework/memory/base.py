"""
记忆抽象基类 — 定义 Agent 事件记录接口

子类可实现 PostgreSQL、SQLite、或其他后端。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from tg_agent_framework.memory.types import MemoryRecord, MemoryScope


class BaseMemory(ABC):
    """Agent 记忆抽象基类"""

    @abstractmethod
    async def record_event(
        self,
        event_type: str,
        description: str,
        *,
        service: str = "",
        triggered_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录一条运维/操作事件"""
        ...

    @abstractmethod
    async def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取最近的事件记录"""
        ...

    async def upsert_memory(self, record: MemoryRecord) -> str:
        """写入或更新一条长期记忆。默认不支持。"""
        raise NotImplementedError("当前记忆后端不支持 upsert_memory")

    async def list_memories(
        self,
        scope: MemoryScope,
        *,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """列出某个 scope 下的长期记忆。默认不支持。"""
        raise NotImplementedError("当前记忆后端不支持 list_memories")

    async def delete_memory(self, memory_id: str) -> bool:
        """删除一条长期记忆。默认不支持。"""
        raise NotImplementedError("当前记忆后端不支持 delete_memory")

    async def summarize_scope(self, scope: MemoryScope) -> str | None:
        """返回 scope 的最新摘要。默认不支持。"""
        raise NotImplementedError("当前记忆后端不支持 summarize_scope")

    async def cleanup_old_events(self, days: int = 90) -> int:
        """
        清理过期事件，返回删除数量。

        默认不清理，子类可覆盖。
        """
        return 0

    async def init_schema(self) -> None:
        """初始化存储 schema（如建表）。默认空操作。"""
        pass
