import sys
from pathlib import Path
import json
import asyncio
from types import SimpleNamespace

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


def test_describe_execution_error_highlights_json_decode_context():
    bot = AgentBot(
        config=type(
            "Cfg",
            (),
            {
                "telegram_bot_token": "x",
                "telegram_allowed_users": [],
                "llm_api_key": "sk-test",
                "llm_base_url": "https://example.invalid/v1",
                "llm_model": "gpt-test",
                "llm_reasoning_effort": "",
                "llm_request_timeout_seconds": 30.0,
                "foreground_operation_timeout_seconds": 45.0,
                "max_history_messages": 24,
            },
        )(),
        graph=object(),
        state_store=type(
            "StateStore",
            (),
            {
                "get_thread_id": lambda self, user_id: None,
                "set_thread_id": lambda self, user_id, thread_id: None,
                "save_foreground_operation": lambda self, operation: None,
                "delete_foreground_operation": lambda self, user_id: None,
                "load_foreground_operations": lambda self: [],
            },
        )(),
    )

    error = json.JSONDecodeError("Expecting value", "", 0)
    text = bot._describe_execution_error(
        error,
        action_label="检查所有服务的运行状态",
        thread_id="tg-42",
    )

    assert "JSON 解析失败" in text
    assert "tg-42" in text
    assert "gpt-test" in text
    assert "https://example.invalid/v1" in text
    assert "检查所有服务的运行状态" in text


def test_execute_message_operation_uses_direct_hook_before_graph():
    class DirectMessageBot(AgentBot):
        async def run_direct_message_action(self, text, message):
            return ("检查下服务状态", "direct ok", True)

    class FailingGraph:
        async def ainvoke(self, *_args, **_kwargs):
            raise AssertionError("graph should not be called")

    bot = DirectMessageBot(
        config=type(
            "Cfg",
            (),
            {
                "telegram_bot_token": "x",
                "telegram_allowed_users": [],
                "llm_api_key": "sk-test",
                "llm_base_url": "https://example.invalid/v1",
                "llm_model": "gpt-test",
                "llm_reasoning_effort": "",
                "llm_request_timeout_seconds": 30.0,
                "foreground_operation_timeout_seconds": 45.0,
                "max_history_messages": 24,
            },
        )(),
        graph=FailingGraph(),
        state_store=type(
            "StateStore",
            (),
            {
                "get_thread_id": lambda self, user_id: None,
                "set_thread_id": lambda self, user_id, thread_id: None,
                "save_foreground_operation": lambda self, operation: None,
                "delete_foreground_operation": lambda self, user_id: None,
                "load_foreground_operations": lambda self: [],
            },
        )(),
    )

    result = asyncio.run(
        bot._execute_message_operation(
            user_text="检查下服务状态",
            message=SimpleNamespace(text="检查下服务状态"),
            thread_id="tg-42",
        )
    )

    assert result == ("检查下服务状态", "direct ok", True)
