"""
LangGraph Agent 状态定义 — 通用基类
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Agent 会话状态基类"""

    # 对话消息历史（LangGraph 自动合并）
    messages: Annotated[list, add_messages]
