"""
记忆抽象基类 — 定义 Agent 事件记录接口

子类可实现 PostgreSQL、SQLite、或其他后端。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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

    async def cleanup_old_events(self, days: int = 90) -> int:
        """
        清理过期事件，返回删除数量。

        默认不清理，子类可覆盖。
        """
        return 0

    async def init_schema(self) -> None:
        """初始化存储 schema（如建表）。默认空操作。"""
        pass
