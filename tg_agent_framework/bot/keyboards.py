"""
Telegram 内联键盘构建器

通用键盘: 审批确认/拒绝
快捷面板: 由 AgentBot 子类的 get_quick_actions() 动态生成
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from tg_agent_framework.bot.types import QuickAction


# Telegram callback_data 最大 64 字节
_CALLBACK_DATA_MAX_BYTES = 64


def _safe_callback_data(prefix: str, thread_id: str, user_id: int) -> str:
    """构建 callback_data 并确保不超过 64 字节限制"""
    data = f"{prefix}:{thread_id}:{user_id}"
    if len(data.encode("utf-8")) <= _CALLBACK_DATA_MAX_BYTES:
        return data
    # 截断 thread_id 以适应限制
    overhead = len(f"{prefix}::{user_id}".encode("utf-8"))
    max_tid_bytes = _CALLBACK_DATA_MAX_BYTES - overhead
    truncated = thread_id.encode("utf-8")[:max_tid_bytes].decode("utf-8", errors="ignore")
    return f"{prefix}:{truncated}:{user_id}"


def build_approval_keyboard(thread_id: str, user_id: int) -> InlineKeyboardMarkup:
    """构建危险操作确认/拒绝键盘"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ 确定执行",
                    callback_data=_safe_callback_data("approve", thread_id, user_id),
                ),
                InlineKeyboardButton(
                    text="❌ 取消",
                    callback_data=_safe_callback_data("reject", thread_id, user_id),
                ),
            ]
        ]
    )


def build_quick_action_keyboard(
    quick_actions: list["QuickAction"],
) -> InlineKeyboardMarkup | None:
    """根据 QuickAction 列表构建快捷面板键盘"""
    if not quick_actions:
        return None

    rows: dict[int, list[InlineKeyboardButton]] = defaultdict(list)
    for action in quick_actions:
        rows[action.row].append(
            InlineKeyboardButton(
                text=action.label,
                callback_data=action.callback_data,
            )
        )

    keyboard = [rows[k] for k in sorted(rows.keys())]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
