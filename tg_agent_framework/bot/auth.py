"""
Telegram 用户权限校验
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import types

if TYPE_CHECKING:
    from tg_agent_framework.config import BaseConfig


def is_authorized(message: types.Message, config: "BaseConfig") -> bool:
    """检查消息发送者是否在白名单内"""
    if not config.telegram_allowed_users:
        return False
    user_id = message.from_user.id if message.from_user else 0
    return user_id in config.telegram_allowed_users


def get_user_display(message: types.Message) -> str:
    """获取用户显示名称"""
    if message.from_user:
        name = message.from_user.full_name or message.from_user.username or "Unknown"
        return f"{name} (ID: {message.from_user.id})"
    return "Unknown"
