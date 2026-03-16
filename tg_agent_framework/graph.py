"""
LangGraph 主状态图 — 通用化编排

工具分两类:
- 只读工具 (safe): 直接执行，无需确认
- 危险工具 (dangerous): 通过 interrupt_before 暂停，等待 Telegram 确认
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tg_agent_framework.config import BaseConfig
from tg_agent_framework.memory.checkpointer import PersistentMemorySaver
from tg_agent_framework.memory.runtime_store import RuntimeStateStore
from tg_agent_framework.registry import ToolRegistry, tool_registry
from tg_agent_framework.state import AgentState


def build_graph(
    config: BaseConfig,
    state_store: RuntimeStateStore,
    system_prompt: str,
    registry: ToolRegistry | None = None,
    *,
    safe_tools: list[Any] | None = None,
    dangerous_tools: list[Any] | None = None,
    state_class: type = AgentState,
) -> tuple:
    """
    构建 LangGraph 状态图。

    工具来源（二选一）:
    - 传入 registry（推荐，声明式注册）
    - 传入 safe_tools + dangerous_tools 列表（兼容模式）

    返回: (compiled_graph, checkpointer)
    """
    reg = registry or tool_registry

    _safe = safe_tools if safe_tools is not None else reg.safe_tools
    _dangerous = dangerous_tools if dangerous_tools is not None else reg.dangerous_tools
    all_tools = _safe + _dangerous
    dangerous_names = {t.name for t in _dangerous}

    if not all_tools:
        raise ValueError("至少需要注册一个工具")

    # ── 1. 初始化 LLM ──
    model_kwargs = {}
    if config.llm_reasoning_effort:
        model_kwargs["reasoning_effort"] = config.llm_reasoning_effort

    llm = ChatOpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        temperature=0,
        request_timeout=config.llm_request_timeout_seconds,
        model_kwargs=model_kwargs,
    )

    # ── 2. 绑定工具 ──
    llm_with_tools = llm.bind_tools(all_tools)

    # ── 3. 定义节点函数 ──
    async def agent_node(state: dict) -> dict:
        """LLM 推理节点"""
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(all_tools)

    # ── 4. 路由逻辑 ──
    def should_continue(state: dict) -> str:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tc in last_message.tool_calls:
                if tc["name"] in dangerous_names:
                    return "dangerous_tools"
            return "safe_tools"
        return END

    # ── 5. 构建状态图 ──
    graph = StateGraph(state_class)
    graph.add_node("agent", agent_node)
    graph.add_node("safe_tools", tool_node)
    graph.add_node("dangerous_tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("safe_tools", "agent")
    graph.add_edge("dangerous_tools", "agent")

    # ── 6. 编译 ──
    checkpointer = PersistentMemorySaver(state_store)
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["dangerous_tools"],
    )

    return compiled, checkpointer
