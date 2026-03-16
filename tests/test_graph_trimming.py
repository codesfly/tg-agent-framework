import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.messages.modifier import RemoveMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.graph import (
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
