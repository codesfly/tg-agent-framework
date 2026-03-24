import sys
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.messages.modifier import RemoveMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.graph import (
    _sanitize_message_window,
    build_trim_messages_delta,
    trim_messages_for_prompt,
)


def test_trim_messages_for_prompt_keeps_most_recent_messages():
    messages = [HumanMessage(content=f"msg-{index}", id=f"m-{index}") for index in range(5)]

    trimmed = trim_messages_for_prompt(messages, max_history_messages=3)

    assert [message.id for message in trimmed] == ["m-2", "m-3", "m-4"]


def test_build_trim_messages_delta_returns_remove_messages_for_old_history():
    messages = [HumanMessage(content=f"msg-{index}", id=f"m-{index}") for index in range(5)]

    delta = build_trim_messages_delta(messages, max_history_messages=3)

    assert all(isinstance(message, RemoveMessage) for message in delta)
    assert [message.id for message in delta] == ["m-0", "m-1"]


def test_build_trim_messages_delta_keeps_tool_outputs_required_by_retained_ai_message():
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"name": "delete", "args": {"slug": "a"}, "id": "call_1", "type": "tool_call"},
            {"name": "delete", "args": {"slug": "b"}, "id": "call_2", "type": "tool_call"},
        ],
        id="ai-1",
    )
    messages = [
        HumanMessage(content="old", id="human-0"),
        ai_message,
        ToolMessage(content="ok-a", tool_call_id="call_1", id="tool-1"),
        ToolMessage(content="ok-b", tool_call_id="call_2", id="tool-2"),
        HumanMessage(content="new-1", id="human-1"),
        HumanMessage(content="new-2", id="human-2"),
        HumanMessage(content="new-3", id="human-3"),
    ]

    delta = build_trim_messages_delta(messages, max_history_messages=4)

    assert [message.id for message in delta] == ["human-0"]


def test_sanitize_message_window_prunes_unresolved_tool_calls():
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"name": "delete", "args": {"slug": "a"}, "id": "call_1", "type": "tool_call"},
            {"name": "delete", "args": {"slug": "b"}, "id": "call_2", "type": "tool_call"},
        ],
        id="ai-1",
    )
    messages = [
        ai_message,
        ToolMessage(content="ok-b", tool_call_id="call_2", id="tool-2"),
    ]

    sanitized = _sanitize_message_window(messages)

    assert isinstance(sanitized[0], AIMessage)
    assert [call["id"] for call in sanitized[0].tool_calls] == ["call_2"]
    assert isinstance(sanitized[1], ToolMessage)
    assert sanitized[1].tool_call_id == "call_2"
