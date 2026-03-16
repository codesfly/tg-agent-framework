"""
长期记忆类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MemoryScopeType = Literal["global", "user", "thread"]
MemoryKind = Literal["event", "fact", "preference", "summary"]


@dataclass(frozen=True)
class MemoryScope:
    scope_type: MemoryScopeType
    scope_id: str = ""

    def __post_init__(self) -> None:
        normalized_scope_id = "" if self.scope_type == "global" else str(self.scope_id)
        object.__setattr__(self, "scope_id", normalized_scope_id)

    @classmethod
    def global_scope(cls) -> "MemoryScope":
        return cls(scope_type="global", scope_id="")

    @classmethod
    def user_scope(cls, user_id: int | str) -> "MemoryScope":
        return cls(scope_type="user", scope_id=str(user_id))

    @classmethod
    def thread_scope(cls, thread_id: str) -> "MemoryScope":
        return cls(scope_type="thread", scope_id=thread_id)


@dataclass
class MemoryRecord:
    scope: MemoryScope
    kind: MemoryKind
    content: str
    memory_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
