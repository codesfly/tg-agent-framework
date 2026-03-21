"""
LangGraph 主状态图 — 通用化编排

工具分两类:
- 只读工具 (safe): 直接执行，无需确认
- 危险工具 (dangerous): 通过 interrupt_before 暂停，等待 Telegram 确认
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.messages.modifier import RemoveMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import SecretStr

from tg_agent_framework.config import BaseConfig
from tg_agent_framework.memory.checkpointer import PersistentMemorySaver
from tg_agent_framework.memory.runtime_backend import RuntimeStateBackend
from tg_agent_framework.registry import ToolRegistry, tool_registry
from tg_agent_framework.state import AgentState

logger = logging.getLogger(__name__)
MALFORMED_LLM_RESPONSE_MAX_ATTEMPTS = 3


def _sanitize_message_window(
    messages: list[AnyMessage],
    full_history: Sequence[AnyMessage] | None = None,
) -> list[AnyMessage]:
    """确保 ToolMessage 总能找到对应的 AIMessage（含 tool_calls）。

    策略：
    1. 优先从 full_history 中找回缺失的 AIMessage 并拼接到窗口前部
    2. 如果找不到（full_history 为空或 AIMessage 已被 checkpoint 清理），
       则移除孤立的 ToolMessage 作为 fallback
    """
    # 1. 收集窗口内 AIMessage 提供的所有 tool_call_id
    available_call_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                call_id = tc.get("id")
                if call_id:
                    available_call_ids.add(call_id)

    # 2. 查找孤立的 ToolMessage（call_id 不在窗口内）
    orphan_call_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            call_id = getattr(msg, "tool_call_id", None)
            if call_id and call_id not in available_call_ids:
                orphan_call_ids.add(call_id)

    if not orphan_call_ids:
        return messages  # 无孤立消息，直接返回

    # 3. 尝试从完整历史中找回缺失的 AIMessage（拼接策略）
    spliced_ai_messages: list[AnyMessage] = []
    resolved_ids: set[str] = set()

    if full_history:
        # 用 id() 集合做 O(1) 查找，避免 O(n²)
        window_ids = {id(m) for m in messages}
        for msg in full_history:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                msg_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
                matched = msg_call_ids & orphan_call_ids
                if matched and id(msg) not in window_ids:
                    spliced_ai_messages.append(msg)
                    resolved_ids |= matched

    remaining_orphans = orphan_call_ids - resolved_ids

    # 4. 拼接找回的 AIMessage 到窗口中（插入到第一个孤立 ToolMessage 之前）
    if spliced_ai_messages:
        # 找到第一个孤立 ToolMessage 的位置
        insert_pos = 0
        for i, msg in enumerate(messages):
            if (
                isinstance(msg, ToolMessage)
                and getattr(msg, "tool_call_id", None) in resolved_ids
            ):
                insert_pos = i
                break
        result = messages[:insert_pos] + spliced_ai_messages + messages[insert_pos:]
        logger.info(
            "消息历史修复: 从完整历史中拼接回 %d 条 AIMessage (call_ids: %s)",
            len(spliced_ai_messages),
            resolved_ids,
        )
    else:
        result = list(messages)

    # 5. 对仍然无法解决的孤立 ToolMessage，fallback 移除
    if remaining_orphans:
        result = [
            msg
            for msg in result
            if not (
                isinstance(msg, ToolMessage)
                and getattr(msg, "tool_call_id", None) in remaining_orphans
            )
        ]
        logger.warning(
            "消息历史清理: 移除了 %d 条无法恢复的孤立 ToolMessage (call_ids: %s)",
            len(remaining_orphans),
            remaining_orphans,
        )

    return result


def trim_messages_for_prompt(
    messages: Sequence[AnyMessage],
    *,
    max_history_messages: int,
    full_history: Sequence[AnyMessage] | None = None,
) -> list[AnyMessage]:
    if max_history_messages <= 0:
        return [message for message in messages if isinstance(message, SystemMessage)]
    system_messages = [message for message in messages if isinstance(message, SystemMessage)]
    history_messages = [message for message in messages if not isinstance(message, SystemMessage)]
    if len(history_messages) <= max_history_messages:
        return list(messages)
    trimmed = system_messages + history_messages[-max_history_messages:]
    return _sanitize_message_window(trimmed, full_history=full_history)


def build_trim_messages_delta(
    messages: Sequence[AnyMessage],
    *,
    max_history_messages: int,
) -> list[RemoveMessage]:
    if max_history_messages <= 0:
        removable_candidates = [message for message in messages if not isinstance(message, SystemMessage)]
    else:
        history_messages = [
            message for message in messages if not isinstance(message, SystemMessage)
        ]
        removable_candidates = history_messages[:-max_history_messages]

    # 收集要保留的消息中所有 ToolMessage 的 tool_call_id
    kept_messages = [msg for msg in messages if msg not in removable_candidates]
    needed_call_ids: set[str] = set()
    for msg in kept_messages:
        if isinstance(msg, ToolMessage):
            call_id = getattr(msg, "tool_call_id", None)
            if call_id:
                needed_call_ids.add(call_id)

    # 不要移除 AIMessage 如果其 tool_call_id 仍被保留区的 ToolMessage 引用
    delta: list[RemoveMessage] = []
    for message in removable_candidates:
        message_id = getattr(message, "id", None)
        if not isinstance(message_id, str):
            continue
        # 保护 AIMessage：如果其 tool_calls 的 id 仍被后续 ToolMessage 需要
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            provided_ids = {tc.get("id") for tc in message.tool_calls if tc.get("id")}
            if provided_ids & needed_call_ids:
                continue  # 跳过，不删除此 AIMessage
        delta.append(RemoveMessage(id=message_id))
    return delta


def _is_orphan_tool_message_error(exc: Exception) -> bool:
    """检测是否为 OpenAI 'No tool call found for function call output' 400 错误。"""
    error_text = str(exc).lower()
    return (
        "no tool call found" in error_text
        or "function call output" in error_text
    )


async def _invoke_llm_with_retries(
    llm_with_tools: Any,
    prompt_messages: list[AnyMessage],
    *,
    max_attempts: int = MALFORMED_LLM_RESPONSE_MAX_ATTEMPTS,
    full_history: Sequence[AnyMessage] | None = None,
) -> Any:
    attempts = max(1, max_attempts)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await llm_with_tools.ainvoke(prompt_messages)
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            logger.warning(
                "LLM 返回了畸形 JSON，准备重试 (%s/%s): %s",
                attempt,
                attempts,
                exc,
            )
            await asyncio.sleep(0)
        except Exception as exc:
            # 捕获 OpenAI 400 孤立 ToolMessage 错误，清理后重试
            if _is_orphan_tool_message_error(exc) and attempt < attempts:
                logger.warning(
                    "检测到孤立 ToolMessage 400 错误，清理消息后重试 (%s/%s): %s",
                    attempt,
                    attempts,
                    exc,
                )
                prompt_messages = _sanitize_message_window(prompt_messages, full_history=full_history)
                await asyncio.sleep(0)
                last_error = exc
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM 调用失败，但未捕获具体异常")


def build_graph(
    config: BaseConfig,
    state_store: RuntimeStateBackend,
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

    llm = ChatOpenAI(  # type: ignore[call-arg]
        openai_api_key=SecretStr(config.llm_api_key) if config.llm_api_key else None,
        openai_api_base=config.llm_base_url,
        model_name=config.llm_model,
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
        prompt_messages = trim_messages_for_prompt(
            messages,
            max_history_messages=config.max_history_messages,
            full_history=messages,  # 传入完整历史用于拼接
        )
        if not prompt_messages or not isinstance(prompt_messages[0], SystemMessage):
            prompt_messages = [SystemMessage(content=system_prompt)] + prompt_messages
        response = await _invoke_llm_with_retries(llm_with_tools, prompt_messages, full_history=messages)
        trim_delta = build_trim_messages_delta(
            messages,
            max_history_messages=config.max_history_messages,
        )
        return {"messages": [*trim_delta, response]}

    tool_node = ToolNode(all_tools)

    # ── 4. 路由逻辑 ──
    def should_continue(state: dict) -> str:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                if tc["name"] in dangerous_names:
                    return "dangerous_tools"
            return "safe_tools"
        return END

    # ── 5. 构建状态图 ──
    graph: Any = StateGraph(state_class)
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
