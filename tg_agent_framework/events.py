"""
事件总线 — 发布/订阅模式

允许框架和业务层解耦通信。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """简单的异步事件发布/订阅总线"""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._background_tasks: set[asyncio.Task] = set()

    def on(self, event: str, handler: EventHandler) -> None:
        """注册事件处理函数"""
        self._handlers[event].append(handler)

    def off(self, event: str, handler: EventHandler) -> None:
        """注销事件处理函数"""
        handlers = self._handlers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: str, **data: Any) -> None:
        """发布事件，依次调用所有处理函数"""
        for handler in self._handlers.get(event, []):
            try:
                await handler(**data)
            except Exception:
                logger.exception("事件处理异常: event=%s handler=%s", event, handler.__name__)

    def emit_fire_and_forget(self, event: str, **data: Any) -> None:
        """发布事件（不等待），适用于不需要等待结果的场景"""
        for handler in self._handlers.get(event, []):
            task = asyncio.create_task(self._safe_call(handler, event, data))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _safe_call(self, handler: EventHandler, event: str, data: dict) -> None:
        try:
            await handler(**data)
        except Exception:
            logger.exception("事件处理异常: event=%s handler=%s", event, handler.__name__)


# 内置事件名常量
class Events:
    TOOL_EXECUTED = "tool.executed"
    TOOL_APPROVED = "tool.approved"
    TOOL_REJECTED = "tool.rejected"
    OPERATION_TIMEOUT = "operation.timeout"
    OPERATION_CANCELLED = "operation.cancelled"
    MODEL_SWITCHED = "model.switched"
    ALERT_TRIGGERED = "alert.triggered"
    ALERT_RECOVERED = "alert.recovered"
