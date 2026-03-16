import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.bot.agent_bot import AgentBot
from tg_agent_framework.memory.runtime_store import RuntimeStateStore


def test_extract_response_prefers_ai_message_content():
    result = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}

    assert AgentBot._extract_response(result) == "hello"


def test_background_task_helpers_are_not_part_of_base_framework():
    assert not hasattr(AgentBot, "_extract_background_task_id")
    assert not hasattr(RuntimeStateStore, "get_latest_task")
    assert not hasattr(RuntimeStateStore, "save_task")
