"""
Bot 类型定义 — QuickAction, BotCommand 等
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QuickAction:
    """快捷操作面板按钮"""

    label: str  # 按钮显示文本（如 "📊 状态"）
    callback_data: str  # 回调数据（如 "quick:status"）
    row: int = 0  # 所在行号（用于布局）
