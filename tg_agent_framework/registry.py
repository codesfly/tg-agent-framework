"""
工具注册中心 — 声明式工具注册 + 自动扫描

用法:
    from tg_agent_framework import tool_registry, ToolCategory

    @tool_registry.register(category=ToolCategory.SAFE)
    @tool
    async def check_status(...): ...

    @tool_registry.register(category=ToolCategory.DANGEROUS)
    @tool
    async def restart_service(...): ...
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    SAFE = "safe"
    DANGEROUS = "dangerous"


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: dict[ToolCategory, list[Any]] = {
            ToolCategory.SAFE: [],
            ToolCategory.DANGEROUS: [],
        }

    def register(self, category: ToolCategory = ToolCategory.SAFE):
        """装饰器：注册工具到指定类别"""

        def decorator(tool_func):
            self._tools[category].append(tool_func)
            return tool_func

        return decorator

    def add(self, tool_func: Any, category: ToolCategory = ToolCategory.SAFE):
        """手动注册工具"""
        self._tools[category].append(tool_func)

    def add_many(self, tools: list[Any], category: ToolCategory = ToolCategory.SAFE):
        """批量注册工具"""
        self._tools[category].extend(tools)

    @property
    def safe_tools(self) -> list[Any]:
        return list(self._tools[ToolCategory.SAFE])

    @property
    def dangerous_tools(self) -> list[Any]:
        return list(self._tools[ToolCategory.DANGEROUS])

    @property
    def all_tools(self) -> list[Any]:
        return self.safe_tools + self.dangerous_tools

    @property
    def dangerous_tool_names(self) -> set[str]:
        return {t.name for t in self.dangerous_tools}

    def scan_package(self, package_name: str) -> None:
        """
        自动扫描指定包下所有模块，触发 @tool_registry.register 装饰器执行。

        用法: tool_registry.scan_package("my_agent.tools")
        """
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.error("无法导入包: %s", package_name)
            return

        if not hasattr(package, "__path__"):
            # 单文件模块，导入即可触发装饰器
            return

        for _importer, module_name, _is_pkg in pkgutil.walk_packages(
            package.__path__, prefix=f"{package_name}."
        ):
            try:
                importlib.import_module(module_name)
            except (ImportError, SyntaxError) as exc:
                logger.warning("扫描模块失败: %s: %s", module_name, exc)
            except Exception:
                logger.warning("扫描模块异常: %s", module_name, exc_info=True)

    def clear(self):
        """清空所有注册（测试用）"""
        for category in self._tools:
            self._tools[category].clear()


# 全局单例
tool_registry = ToolRegistry()
