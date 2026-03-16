"""
tg-agent-framework: Telegram + LangGraph Agent 快速开发框架

开发新 Agent 只需 3 步:
1. 继承 BaseConfig 添加业务字段
2. 编写 Tools（safe_tools + dangerous_tools）
3. 写 System Prompt
"""

from tg_agent_framework.config import BaseConfig, SSHConfigMixin, load_base_config, persist_llm_settings
from tg_agent_framework.state import AgentState
from tg_agent_framework.graph import build_graph
from tg_agent_framework.registry import ToolRegistry, ToolCategory, tool_registry
from tg_agent_framework.events import EventBus
from tg_agent_framework.memory.base import BaseMemory
from tg_agent_framework.memory.null import NullMemory
from tg_agent_framework.memory.checkpointer import PersistentMemorySaver
from tg_agent_framework.memory.runtime_store import RuntimeStateStore
from tg_agent_framework.bot.agent_bot import AgentBot
from tg_agent_framework.bot.types import QuickAction
from tg_agent_framework.tools.executor import CommandExecutor
from tg_agent_framework.tools.tasks import BackgroundTaskManager
from tg_agent_framework.tools.security import validate_shell_command, ALLOWED_SHELL_COMMANDS, BLOCKED_SHELL_PATTERNS
from tg_agent_framework.scheduler import BaseScheduler

__all__ = [
    # Config
    "BaseConfig",
    "SSHConfigMixin",
    "load_base_config",
    "persist_llm_settings",
    # State & Graph
    "AgentState",
    "build_graph",
    # Registry
    "ToolRegistry",
    "ToolCategory",
    "tool_registry",
    # Events
    "EventBus",
    # Memory
    "BaseMemory",
    "NullMemory",
    "PersistentMemorySaver",
    "RuntimeStateStore",
    # Bot
    "AgentBot",
    "QuickAction",
    # Tools
    "CommandExecutor",
    "BackgroundTaskManager",
    "validate_shell_command",
    "ALLOWED_SHELL_COMMANDS",
    "BLOCKED_SHELL_PATTERNS",
    # Scheduler
    "BaseScheduler",
]
