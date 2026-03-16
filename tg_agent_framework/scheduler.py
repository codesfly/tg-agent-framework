"""
定时任务调度器基类

提供通用的 register_check + start/stop 接口，
子类或使用者注册具体的健康检查逻辑。
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine

from tg_agent_framework.config import BaseConfig
from tg_agent_framework.events import EventBus, Events

logger = logging.getLogger(__name__)

# 连续失败多少次后告警
DEFAULT_ALERT_THRESHOLD = 2

CheckFn = Callable[[], Coroutine[Any, Any, tuple[bool, str]]]


class BaseScheduler:
    """
    定时健康检查调度器基类。

    用法:
        scheduler = BaseScheduler(config, bot_send)
        scheduler.register_check("API Health", check_api_fn, interval=300)
        scheduler.start()
    """

    def __init__(
        self,
        config: BaseConfig,
        bot_send_func: Callable,
        *,
        alert_threshold: int = DEFAULT_ALERT_THRESHOLD,
        event_bus: EventBus | None = None,
    ):
        self._config = config
        self._bot_send = bot_send_func
        self._alert_threshold = alert_threshold
        self._event_bus = event_bus

        self._checks: list[tuple[str, CheckFn, int]] = []  # (name, fn, interval)
        self._tasks: list[asyncio.Task] = []
        self._fail_counts: dict[str, int] = {}
        self._alerted: set[str] = set()

    def register_check(
        self,
        name: str,
        check_fn: CheckFn,
        interval: int = 300,
    ) -> None:
        """注册一个健康检查"""
        self._checks.append((name, check_fn, interval))

    def start(self) -> None:
        """启动所有注册的检查"""
        for name, fn, interval in self._checks:
            task = asyncio.create_task(self._check_loop(name, fn, interval))
            self._tasks.append(task)
        logger.info("调度器已启动，注册了 %d 个检查项", len(self._checks))

    def stop(self) -> None:
        """停止所有检查"""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("调度器已停止")

    async def _check_loop(self, name: str, fn: CheckFn, interval: int) -> None:
        await asyncio.sleep(30)  # 给服务启动时间
        while True:
            try:
                ok, msg = await fn()
                await self._process_result(name, ok, msg)
            except Exception:
                logger.exception("健康检查异常: %s", name)
            await asyncio.sleep(interval)

    async def _process_result(self, name: str, ok: bool, msg: str) -> None:
        if ok:
            if name in self._alerted:
                self._alerted.discard(name)
                self._fail_counts[name] = 0
                await self._send_recovery(name, msg)
                if self._event_bus:
                    self._event_bus.emit_fire_and_forget(
                        Events.ALERT_RECOVERED, service=name, detail=msg
                    )
            self._fail_counts[name] = 0
        else:
            self._fail_counts[name] = self._fail_counts.get(name, 0) + 1
            if (
                self._fail_counts[name] >= self._alert_threshold
                and name not in self._alerted
            ):
                self._alerted.add(name)
                await self._send_alert(name, msg)
                if self._event_bus:
                    self._event_bus.emit_fire_and_forget(
                        Events.ALERT_TRIGGERED, service=name, detail=msg
                    )

    async def _send_alert(self, service: str, detail: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        safe_detail = _html.escape(detail)
        text = (
            f"🚨 <b>告警: {_html.escape(service)} 异常</b>\n\n"
            f"时间: {now}\n"
            f"详情: {safe_detail}\n"
            f"连续失败: {self._fail_counts.get(service, 0)} 次\n\n"
            f"请及时处理！"
        )
        for uid in self._config.telegram_allowed_users:
            try:
                await self._bot_send(uid, text, parse_mode="HTML")
            except Exception:
                logger.exception("发送告警到 %d 失败", uid)

    async def _send_recovery(self, service: str, detail: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        safe_detail = _html.escape(detail)
        text = (
            f"✅ <b>恢复: {_html.escape(service)} 已正常</b>\n\n"
            f"时间: {now}\n"
            f"状态: {safe_detail}"
        )
        for uid in self._config.telegram_allowed_users:
            try:
                await self._bot_send(uid, text, parse_mode="HTML")
            except Exception:
                logger.exception("发送恢复通知到 %d 失败", uid)
