"""
AgentBot — Telegram + LangGraph Agent 通用 Bot 基类

继承此类并覆盖以下方法即可创建新 Agent：
- get_start_message()     — /start 欢迎文案
- get_quick_actions()     — 快捷操作面板
- get_bot_commands()      — Bot 命令菜单

框架自动处理:
- 消息收发与格式化
- 前台操作进度追踪与心跳
- 危险操作确认/拒绝流程
- 超时自动重置 thread
- /reset、/stop、/model 内置命令
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import html as _html
import logging
import time
import uuid
from typing import Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from langchain_core.messages import HumanMessage

from tg_agent_framework.bot.auth import get_user_display, is_authorized
from tg_agent_framework.bot.keyboards import build_approval_keyboard, build_quick_action_keyboard
from tg_agent_framework.bot.markdown import (
    markdown_to_telegram_html,
    strip_html_tags,
    truncate_for_telegram,
)
from tg_agent_framework.bot.types import QuickAction
from tg_agent_framework.config import BaseConfig, persist_llm_settings
from tg_agent_framework.events import EventBus, Events
from tg_agent_framework.memory.base import BaseMemory
from tg_agent_framework.memory.null import NullMemory
from tg_agent_framework.memory.runtime_store import PersistedForegroundOperation, RuntimeStateStore

logger = logging.getLogger(__name__)

# 常量
FOREGROUND_HEARTBEAT_INTERVAL = 2.0
FOREGROUND_HEARTBEAT_SCHEDULE = (
    (0.0, "已接收请求，正在规划下一步"),
    (8.0, "正在执行，请稍候"),
    (25.0, "仍在执行，这类操作可能需要几十秒"),
    (60.0, "仍在执行，如果是长时间操作，通常属于正常现象"),
)


# ── 异常类 ──

class ProgressInvocationError(Exception):
    def __init__(self, original: Exception, elapsed_seconds: float):
        super().__init__(str(original))
        self.original = original
        self.elapsed_seconds = elapsed_seconds


class ForegroundOperationCancelled(Exception):
    pass


class ForegroundOperationTimedOut(Exception):
    def __init__(self, timeout_seconds: float):
        super().__init__(
            f"前台请求超过 {timeout_seconds:.0f}s 未完成，已自动中止。"
            "对话上下文已自动重置，请直接重试。"
        )
        self.timeout_seconds = timeout_seconds


@dataclass
class ActiveForegroundOperation:
    user_id: int
    action_label: str
    cancel_event: asyncio.Event
    cancel_reason: str | None = None
    chat_id: int = 0
    message_id: int = 0
    started_at: float = 0.0


class AgentBot:
    """
    Telegram + LangGraph Agent 通用 Bot 基类。

    子类覆盖扩展点来定制行为。
    """

    def __init__(
        self,
        config: BaseConfig,
        graph: Any,
        state_store: RuntimeStateStore,
        *,
        memory: BaseMemory | None = None,
        task_manager: Any = None,
        event_bus: EventBus | None = None,
        dangerous_tool_names: set[str] | None = None,
    ):
        self._config = config
        self._graph = graph
        self._state_store = state_store
        self._memory: BaseMemory = memory or NullMemory()
        self._task_manager = task_manager
        self._event_bus = event_bus or EventBus()
        self._dangerous_tool_names = dangerous_tool_names or set()

        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None

        # 运行时状态
        self._user_threads: dict[int, str] = {}
        self._user_latest_task: dict[int, str] = {}
        self._active_foreground_ops: dict[int, ActiveForegroundOperation] = {}

    # ═══════════════════════════════════════════
    #  子类覆盖点
    # ═══════════════════════════════════════════

    def get_start_message(self) -> str:
        """子类覆盖: /start 欢迎文案"""
        return (
            "🤖 **Agent 已就绪！**\n\n"
            "你可以直接发送自然语言指令与我交互。\n\n"
            "**内置命令：**\n"
            "• `/reset` - 重置对话上下文\n"
            "• `/stop` - 取消当前操作\n"
            "• `/model` - 查看/切换 LLM 模型\n"
        )

    def get_quick_actions(self) -> list[QuickAction]:
        """子类覆盖: 快捷操作面板按钮"""
        return []

    def get_bot_commands(self) -> list[BotCommand]:
        """子类覆盖: Bot 命令菜单"""
        return [
            BotCommand(command="start", description="启动对话"),
            BotCommand(command="reset", description="重置对话上下文"),
            BotCommand(command="stop", description="取消当前执行"),
            BotCommand(command="model", description="查看/切换 LLM 模型"),
        ]

    async def on_quick_action(self, action: str, callback: types.CallbackQuery) -> str | None:
        """
        子类覆盖: 处理快捷操作回调。

        Args:
            action: 去掉 "quick:" 前缀后的动作标识
            callback: Telegram 回调查询对象

        Returns:
            要发送给 Agent 的文本，或 None 跳过
        """
        return action

    # ═══════════════════════════════════════════
    #  公共 API
    # ═══════════════════════════════════════════

    async def run(self) -> None:
        """启动 Bot 轮询"""
        self._bot = Bot(token=self._config.telegram_bot_token)
        self._dp = Dispatcher()
        self._register_handlers()
        await self.recover_interrupted_foreground_operations()

        logger.info("🤖 Agent Bot 启动中...")
        try:
            await self._bot.set_my_commands(self.get_bot_commands())
            await self._dp.start_polling(self._bot)
        finally:
            if self._bot:
                await self._bot.session.close()
            logger.info("Agent Bot 已停止")

    async def recover_interrupted_foreground_operations(self):
        """恢复因重启中断的前台操作"""
        if not self._bot:
            return
        operations = self._state_store.load_foreground_operations()
        for operation in operations:
            user_id = int(operation.user_id)
            text = truncate_for_telegram(
                self._build_completion_message(
                    action_label=operation.action_label,
                    response_text=(
                        "Agent 在执行期间发生重启或中断，这次请求未执行完成。"
                        "请重新发送指令；如果问题持续，请先执行 /reset。"
                    ),
                    elapsed_seconds=0.0,
                    success=False,
                )
            )
            try:
                await self._bot.edit_message_text(
                    chat_id=operation.chat_id,
                    message_id=operation.message_id,
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning("恢复前台操作提示失败: %s", exc)
            finally:
                self._state_store.delete_foreground_operation(user_id)

    # ═══════════════════════════════════════════
    #  内部: Thread 管理
    # ═══════════════════════════════════════════

    def _get_thread_id(self, user_id: int) -> str:
        if user_id not in self._user_threads:
            persisted = self._state_store.get_thread_id(user_id)
            self._user_threads[user_id] = persisted or f"tg-{user_id}"
            self._state_store.set_thread_id(user_id, self._user_threads[user_id])
        return self._user_threads[user_id]

    def _set_thread_id(self, user_id: int, thread_id: str):
        self._user_threads[user_id] = thread_id
        self._state_store.set_thread_id(user_id, thread_id)

    def _get_latest_task_id(self, user_id: int) -> str | None:
        if user_id in self._user_latest_task:
            return self._user_latest_task[user_id]
        task_id = self._state_store.get_latest_task(user_id)
        if task_id:
            self._user_latest_task[user_id] = task_id
        return task_id

    def _set_latest_task_id(self, user_id: int, task_id: str):
        self._user_latest_task[user_id] = task_id
        self._state_store.set_latest_task(user_id, task_id)

    # ═══════════════════════════════════════════
    #  内部: 前台操作管理
    # ═══════════════════════════════════════════

    def _get_active_foreground_operation(self, user_id: int) -> ActiveForegroundOperation | None:
        return self._active_foreground_ops.get(user_id)

    def _register_active_foreground_operation(
        self, user_id: int, action_label: str, chat_id: int, message_id: int,
    ) -> ActiveForegroundOperation:
        started_at = time.monotonic()
        operation = ActiveForegroundOperation(
            user_id=user_id,
            action_label=self._summarize_action_label(action_label),
            cancel_event=asyncio.Event(),
            chat_id=chat_id,
            message_id=message_id,
            started_at=started_at,
        )
        self._active_foreground_ops[user_id] = operation
        self._state_store.save_foreground_operation(
            PersistedForegroundOperation(
                user_id=str(user_id),
                action_label=operation.action_label,
                chat_id=chat_id,
                message_id=message_id,
                started_at=datetime.now().isoformat(timespec="seconds"),
            )
        )
        return operation

    def _clear_active_foreground_operation(
        self, user_id: int, operation: ActiveForegroundOperation, *, clear_persisted_state: bool = True,
    ):
        if self._active_foreground_ops.get(user_id) is operation:
            self._active_foreground_ops.pop(user_id, None)
        if clear_persisted_state:
            self._state_store.delete_foreground_operation(user_id)

    def _request_cancel_active_foreground(self, user_id: int, reason: str) -> ActiveForegroundOperation | None:
        operation = self._active_foreground_ops.get(user_id)
        if not operation:
            return None
        operation.cancel_reason = reason
        operation.cancel_event.set()
        return operation

    def _foreground_operation_timeout_seconds(self) -> float:
        raw = getattr(self._config, "foreground_operation_timeout_seconds", 45.0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 45.0
        return value if value > 0 else 45.0

    # ═══════════════════════════════════════════
    #  内部: 消息格式化
    # ═══════════════════════════════════════════

    @staticmethod
    def _summarize_action_label(action_label: str) -> str:
        compact = " ".join((action_label or "").split())
        if not compact:
            return "当前请求"
        return compact[:77] + "..." if len(compact) > 80 else compact

    def _progress_phase(self, elapsed_seconds: float) -> str:
        phase = FOREGROUND_HEARTBEAT_SCHEDULE[0][1]
        for threshold, label in FOREGROUND_HEARTBEAT_SCHEDULE:
            if elapsed_seconds >= threshold:
                phase = label
            else:
                break
        return phase

    def _build_progress_message(self, action_label: str, elapsed_seconds: float) -> str:
        phase = self._progress_phase(elapsed_seconds)
        safe_action = _html.escape(self._summarize_action_label(action_label))
        return (
            "⏳ <b>请求处理中</b>\n\n"
            f"<b>请求:</b> <code>{safe_action}</code>\n"
            f"<b>状态:</b> {phase}\n"
            f"<b>已等待:</b> <code>{elapsed_seconds:.1f}s</code>"
        )

    def _build_completion_message(
        self, action_label: str, response_text: str, elapsed_seconds: float, success: bool,
    ) -> str:
        icon = "✅" if success else "❌"
        title = "操作完成" if success else "执行失败"
        safe_action = _html.escape(self._summarize_action_label(action_label))
        body = markdown_to_telegram_html(response_text)
        return (
            f"{icon} <b>{title}</b> (<code>{elapsed_seconds:.1f}s</code>)\n"
            f"<b>请求:</b> <code>{safe_action}</code>\n\n"
            f"{body}"
        )

    def _build_cancellation_message(
        self, action_label: str, response_text: str, elapsed_seconds: float,
    ) -> str:
        safe_action = _html.escape(self._summarize_action_label(action_label))
        body = markdown_to_telegram_html(response_text)
        return (
            f"🛑 <b>操作已取消</b> (<code>{elapsed_seconds:.1f}s</code>)\n"
            f"<b>请求:</b> <code>{safe_action}</code>\n\n"
            f"{body}"
        )

    # ═══════════════════════════════════════════
    #  内部: LangGraph 响应提取
    # ═══════════════════════════════════════════

    @staticmethod
    def _extract_response(result: dict) -> str:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                return msg.content
        return "（Agent 无返回内容）"

    @staticmethod
    def _extract_pending_tools(result: dict) -> str:
        messages = result.get("messages", [])
        lines: list[str] = []
        for msg in reversed(messages):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "unknown")
                    args = tc.get("args", {})
                    args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                    lines.append(f"🔧 <code>{_html.escape(name)}</code>({_html.escape(args_str[:200])})")
                break
        return "\n".join(lines) if lines else "（未知操作）"

    @staticmethod
    def _extract_background_task_id(response_text: str) -> str | None:
        import re
        match = re.search(r"(task_[a-f0-9]+)", response_text)
        return match.group(1) if match else None

    # ═══════════════════════════════════════════
    #  内部: 前台进度追踪
    # ═══════════════════════════════════════════

    async def _invoke_with_progress(
        self, user_id: int, chat_id: int, message_id: int,
        action_label: str, operation,
    ) -> tuple[Any, float]:
        """执行 LangGraph operation 并实时更新进度"""
        assert self._bot is not None

        operation_timeout = self._foreground_operation_timeout_seconds()
        active_operation = self._register_active_foreground_operation(
            user_id, action_label, chat_id, message_id,
        )
        stop_event = asyncio.Event()
        started_at = time.monotonic()
        preserve_for_recovery = False

        async def heartbeat():
            await asyncio.sleep(FOREGROUND_HEARTBEAT_INTERVAL)
            while not stop_event.is_set():
                elapsed = time.monotonic() - started_at
                text = self._build_progress_message(action_label, elapsed)
                try:
                    await self._bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=text, parse_mode="HTML",
                    )
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=FOREGROUND_HEARTBEAT_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    continue

        heartbeat_task = asyncio.create_task(heartbeat())
        operation_task = asyncio.create_task(
            asyncio.wait_for(operation(), timeout=operation_timeout)
        )
        cancel_task = asyncio.create_task(active_operation.cancel_event.wait())

        try:
            done, _ = await asyncio.wait(
                {operation_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                reason = active_operation.cancel_reason or "用户取消了当前操作"
                raise ProgressInvocationError(
                    ForegroundOperationCancelled(reason),
                    time.monotonic() - started_at,
                )
            result = await operation_task
            return result, time.monotonic() - started_at
        except Exception as exc:
            if isinstance(exc, ProgressInvocationError):
                raise
            if isinstance(exc, asyncio.TimeoutError):
                logger.warning(
                    "前台操作超时 (user=%s, timeout=%ss)，自动重置对话上下文",
                    user_id, operation_timeout,
                )
                self._set_thread_id(user_id, f"tg-{user_id}-{uuid.uuid4().hex[:8]}")
                if self._event_bus:
                    self._event_bus.emit_fire_and_forget(
                        Events.OPERATION_TIMEOUT, user_id=user_id, timeout=operation_timeout,
                    )
                exc = ForegroundOperationTimedOut(operation_timeout)
            raise ProgressInvocationError(exc, time.monotonic() - started_at) from exc
        except asyncio.CancelledError:
            preserve_for_recovery = True
            raise
        finally:
            stop_event.set()
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self._clear_active_foreground_operation(
                user_id, active_operation,
                clear_persisted_state=not preserve_for_recovery,
            )

    # ═══════════════════════════════════════════
    #  内部: Handler 注册
    # ═══════════════════════════════════════════

    def _register_handlers(self):
        assert self._dp is not None
        assert self._bot is not None
        dp = self._dp
        bot = self._bot

        @dp.message(Command("start"))
        async def handle_start(message: types.Message):
            if not is_authorized(message, self._config):
                await message.reply("⛔ 无权限访问")
                return
            keyboard = build_quick_action_keyboard(self.get_quick_actions())
            await message.reply(
                self.get_start_message(),
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

        @dp.message(Command("reset"))
        async def handle_reset(message: types.Message):
            if not is_authorized(message, self._config):
                return
            user_id = message.from_user.id  # type: ignore[union-attr]
            cancelled = self._request_cancel_active_foreground(user_id, "用户执行 /reset")
            self._set_thread_id(user_id, f"tg-{user_id}-{uuid.uuid4().hex[:8]}")
            suffix = "\n🛑 已同时请求取消当前执行中的前台操作" if cancelled else ""
            await message.reply(f"🔄 对话上下文已重置{suffix}")
            await self._memory.record_event(
                event_type="admin",
                description="用户重置了对话上下文",
                triggered_by=str(user_id),
            )

        @dp.message(Command("stop"))
        async def handle_stop(message: types.Message):
            if not is_authorized(message, self._config):
                return
            user_id = message.from_user.id  # type: ignore[union-attr]
            if not self._task_manager:
                cancelled = self._request_cancel_active_foreground(user_id, "用户执行 /stop")
                if cancelled:
                    await message.reply("🛑 已请求取消当前前台操作")
                else:
                    await message.reply("当前没有正在执行的操作")
                return
            parts = message.text.split() if message.text else []
            task_id = parts[1] if len(parts) > 1 else None
            if not task_id:
                cancelled = self._request_cancel_active_foreground(user_id, "用户执行 /stop")
                if cancelled:
                    await message.reply(f"🛑 已请求取消当前前台操作")
                    return
                task_id = self._get_latest_task_id(user_id)
            if not task_id:
                await message.reply("❓ 未指定任务 ID，且找不到你最近执行的后台任务。\n格式: `/stop task_xxxxxx`")
                return
            success = self._task_manager.stop_task(task_id)
            if success:
                await message.reply(f"🛑 已发起进程终止信号: `{task_id}`")
            else:
                await message.reply(f"⚠️ 无法停止任务 `{task_id}`，可能已结束或不存在。")

        @dp.message(Command("model"))
        async def handle_model(message: types.Message):
            if not is_authorized(message, self._config):
                return
            parts = message.text.split(maxsplit=2) if message.text else []
            if len(parts) < 2:
                await message.reply(
                    f"🧠 当前模型: `{self._config.llm_model}`\n"
                    f"🌐 API: `{self._config.llm_base_url}`\n\n"
                    f"切换: `/model <模型名> [API地址]`",
                    parse_mode="Markdown",
                )
                return
            new_model = parts[1]
            new_base_url = parts[2] if len(parts) > 2 else self._config.llm_base_url
            thinking_msg = await message.reply("⏳ 正在切换模型...")
            try:
                old_model = self._config.llm_model
                old_base_url = self._config.llm_base_url
                self._config.llm_model = new_model
                self._config.llm_base_url = new_base_url
                from tg_agent_framework.graph import build_graph
                new_graph, _ = build_graph(
                    self._config, self._state_store,
                    system_prompt="",  # 子类应重建整个 bot
                )
                persist_llm_settings(self._config, new_model, new_base_url)
                self._graph = new_graph
                user_id = message.from_user.id  # type: ignore[union-attr]
                self._set_thread_id(user_id, f"tg-{user_id}-{uuid.uuid4().hex[:8]}")
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=thinking_msg.message_id,
                    text=(
                        f"✅ 模型已切换！\n\n"
                        f"🧠 <b>模型:</b> <code>{new_model}</code>\n"
                        f"🌐 <b>API:</b> <code>{new_base_url}</code>\n\n"
                        f"🔄 对话上下文已自动重置"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                self._config.llm_model = old_model
                self._config.llm_base_url = old_base_url
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=thinking_msg.message_id,
                    text=f"❌ 切换失败: {e}",
                )

        # ── 核心消息处理 ──
        @dp.message()
        async def handle_message(message: types.Message):
            if not is_authorized(message, self._config):
                return
            if not message.text:
                return
            user_id = message.from_user.id  # type: ignore[union-attr]
            thread_id = self._get_thread_id(user_id)
            if self._get_active_foreground_operation(user_id):
                await message.reply(
                    "⏳ 当前还有前台操作在执行中，请先等待完成，或发送 /stop 取消。"
                )
                return
            snapshot = self._graph.get_state(config={"configurable": {"thread_id": thread_id}})
            if snapshot.next:
                if "dangerous_tools" in snapshot.next:
                    await message.reply("⚠️ 上一个操作还在等待确认，请先点击【确定】或【取消】。若不可见，请 /reset。")
                else:
                    await message.reply("⚠️ Agent 状态异常，请发送 /reset 重置对话。")
                return
            thinking_msg = await message.reply("🤔 思考中...")
            action_label = message.text
            try:
                result, elapsed = await self._invoke_with_progress(
                    user_id=user_id,
                    chat_id=message.chat.id,
                    message_id=thinking_msg.message_id,
                    action_label=action_label,
                    operation=lambda: self._graph.ainvoke(
                        {"messages": [HumanMessage(content=message.text)]},
                        config={"configurable": {"thread_id": thread_id}},
                    ),
                )
                snapshot = self._graph.get_state(config={"configurable": {"thread_id": thread_id}})
                if snapshot.next:
                    pending_tools = self._extract_pending_tools(result)
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=thinking_msg.message_id,
                        text=f"⚠️ <b>需要确认以下操作：</b>\n\n{pending_tools}\n\n请点击按钮确认或取消：",
                        reply_markup=build_approval_keyboard(thread_id, user_id),
                        parse_mode="HTML",
                    )
                else:
                    response_text = self._extract_response(result)
                    task_id = self._extract_background_task_id(response_text)
                    if task_id:
                        self._set_latest_task_id(user_id, task_id)
                    try:
                        safe_html = self._build_completion_message(
                            action_label=action_label,
                            response_text=response_text,
                            elapsed_seconds=elapsed,
                            success=True,
                        )
                        await bot.edit_message_text(
                            chat_id=message.chat.id,
                            message_id=thinking_msg.message_id,
                            text=truncate_for_telegram(safe_html),
                            parse_mode="HTML",
                        )
                    except Exception:
                        await bot.edit_message_text(
                            chat_id=message.chat.id,
                            message_id=thinking_msg.message_id,
                            text=truncate_for_telegram(
                                strip_html_tags(self._build_completion_message(
                                    action_label=action_label,
                                    response_text=response_text,
                                    elapsed_seconds=elapsed,
                                    success=True,
                                ))
                            ),
                        )
            except ProgressInvocationError as e:
                logger.exception("Agent 执行异常")
                if isinstance(e.original, ForegroundOperationCancelled):
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=thinking_msg.message_id,
                        text=truncate_for_telegram(
                            self._build_cancellation_message(
                                action_label=action_label,
                                response_text=str(e.original),
                                elapsed_seconds=e.elapsed_seconds,
                            )
                        ),
                        parse_mode="HTML",
                    )
                    return
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=thinking_msg.message_id,
                    text=truncate_for_telegram(
                        self._build_completion_message(
                            action_label=action_label,
                            response_text=f"Agent 执行出错: {e.original}",
                            elapsed_seconds=e.elapsed_seconds,
                            success=False,
                        )
                    ),
                    parse_mode="HTML",
                )

        # ── 审批回调 ──
        @dp.callback_query(F.data.startswith("approve:"))
        async def handle_approval(callback: types.CallbackQuery):
            if not callback.message or not callback.from_user:
                return
            parts = callback.data.split(":", 2)  # type: ignore
            thread_id = parts[1] if len(parts) > 1 else ""
            initiator_id = parts[2] if len(parts) > 2 else ""
            user_id = callback.from_user.id
            if user_id not in self._config.telegram_allowed_users:
                await callback.answer("⛔ 无权限", show_alert=True)
                return
            if initiator_id and str(user_id) != str(initiator_id):
                await callback.answer("⛔ 只有操作发起者可以确认", show_alert=True)
                return
            await callback.answer("正在执行...")
            action_label = "确认危险操作"
            try:
                result, elapsed = await self._invoke_with_progress(
                    user_id=user_id,
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    action_label=action_label,
                    operation=lambda: self._graph.ainvoke(
                        None, config={"configurable": {"thread_id": thread_id}},
                    ),
                )
                snapshot = self._graph.get_state(config={"configurable": {"thread_id": thread_id}})
                if snapshot.next and "dangerous_tools" in snapshot.next:
                    pending_tools = self._extract_pending_tools(result)
                    await bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        text=f"⚠️ <b>还有后续操作需要确认：</b>\n\n{pending_tools}\n\n继续确认或取消：",
                        reply_markup=build_approval_keyboard(thread_id, user_id),
                        parse_mode="HTML",
                    )
                    return
                response_text = self._extract_response(result)
                await self._memory.record_event(
                    event_type="tool_execution",
                    description=f"用户确认执行危险操作",
                    triggered_by=str(user_id),
                )
                safe_html = self._build_completion_message(
                    action_label=action_label,
                    response_text=response_text,
                    elapsed_seconds=elapsed,
                    success=True,
                )
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=truncate_for_telegram(safe_html),
                    parse_mode="HTML",
                )
            except ProgressInvocationError as e:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=truncate_for_telegram(
                        self._build_completion_message(
                            action_label=action_label,
                            response_text=f"执行出错: {e.original}",
                            elapsed_seconds=e.elapsed_seconds,
                            success=False,
                        )
                    ),
                    parse_mode="HTML",
                )

        @dp.callback_query(F.data.startswith("reject:"))
        async def handle_rejection(callback: types.CallbackQuery):
            if not callback.message or not callback.from_user:
                return
            parts = callback.data.split(":", 2)  # type: ignore
            thread_id = parts[1] if len(parts) > 1 else ""
            initiator_id = parts[2] if len(parts) > 2 else ""
            user_id = callback.from_user.id
            if user_id not in self._config.telegram_allowed_users:
                await callback.answer("⛔ 无权限", show_alert=True)
                return
            if initiator_id and str(user_id) != str(initiator_id):
                await callback.answer("⛔ 只有操作发起者可以取消", show_alert=True)
                return
            await callback.answer("已取消")
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = self._graph.get_state(config)
            if snapshot.next:
                self._set_thread_id(user_id, f"tg-{user_id}-{uuid.uuid4().hex[:8]}")
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text="🛑 操作已取消，对话上下文已重置。",
            )

        # ── 快捷操作回调 ──
        @dp.callback_query(F.data.startswith("quick:"))
        async def handle_quick_action(callback: types.CallbackQuery):
            if not callback.message or not callback.from_user:
                return
            if callback.from_user.id not in self._config.telegram_allowed_users:
                await callback.answer("⛔ 无权限", show_alert=True)
                return
            action = callback.data.split(":", 1)[1]  # type: ignore
            user_text = await self.on_quick_action(action, callback)
            if not user_text:
                await callback.answer()
                return
            user_id = callback.from_user.id
            thread_id = self._get_thread_id(user_id)
            if self._get_active_foreground_operation(user_id):
                await callback.answer("当前有操作执行中，请稍候", show_alert=True)
                return
            await callback.answer()
            thinking_msg = await bot.send_message(
                chat_id=callback.message.chat.id,
                text="🤔 处理中...",
            )
            try:
                result, elapsed = await self._invoke_with_progress(
                    user_id=user_id,
                    chat_id=callback.message.chat.id,
                    message_id=thinking_msg.message_id,
                    action_label=user_text,
                    operation=lambda: self._graph.ainvoke(
                        {"messages": [HumanMessage(content=user_text)]},
                        config={"configurable": {"thread_id": thread_id}},
                    ),
                )
                snapshot = self._graph.get_state(config={"configurable": {"thread_id": thread_id}})
                if snapshot.next:
                    pending_tools = self._extract_pending_tools(result)
                    await bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=thinking_msg.message_id,
                        text=f"⚠️ <b>需要确认以下操作：</b>\n\n{pending_tools}\n\n请点击按钮确认或取消：",
                        reply_markup=build_approval_keyboard(thread_id, user_id),
                        parse_mode="HTML",
                    )
                else:
                    response_text = self._extract_response(result)
                    safe_html = self._build_completion_message(
                        action_label=user_text,
                        response_text=response_text,
                        elapsed_seconds=elapsed,
                        success=True,
                    )
                    await bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=thinking_msg.message_id,
                        text=truncate_for_telegram(safe_html),
                        parse_mode="HTML",
                    )
            except ProgressInvocationError as e:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=thinking_msg.message_id,
                    text=truncate_for_telegram(
                        self._build_completion_message(
                            action_label=user_text,
                            response_text=f"执行出错: {e.original}",
                            elapsed_seconds=e.elapsed_seconds,
                            success=False,
                        )
                    ),
                    parse_mode="HTML",
                )
