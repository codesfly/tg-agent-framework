import asyncio
import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.graph import _invoke_llm_with_retries


class FlakyJsonModel:
    def __init__(self, failures: int, result: str = "ok"):
        self.failures = failures
        self.result = result
        self.calls = 0

    async def ainvoke(self, prompt_messages):
        self.calls += 1
        if self.calls <= self.failures:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return {"messages": prompt_messages, "result": self.result}


def test_invoke_llm_with_retries_recovers_from_malformed_json():
    model = FlakyJsonModel(failures=2, result="success")

    result = asyncio.run(
        _invoke_llm_with_retries(
            model,
            ["prompt"],
            max_attempts=3,
        )
    )

    assert result == {"messages": ["prompt"], "result": "success"}
    assert model.calls == 3


def test_invoke_llm_with_retries_raises_after_retry_budget_exhausted():
    model = FlakyJsonModel(failures=3)

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(
            _invoke_llm_with_retries(
                model,
                ["prompt"],
                max_attempts=3,
            )
        )

    assert model.calls == 3


class MissingToolOutputModel:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, prompt_messages):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("No tool output found for function call call_1.")

        assert any(
            isinstance(message, ToolMessage) and message.tool_call_id == "call_1"
            for message in prompt_messages
        )
        return {"messages": prompt_messages, "result": "recovered"}


def test_invoke_llm_with_retries_recovers_missing_tool_output_from_full_history():
    model = MissingToolOutputModel()
    ai_message = AIMessage(
        content="",
        tool_calls=[{"name": "delete_content", "args": {}, "id": "call_1", "type": "tool_call"}],
        id="ai-1",
    )
    tool_message = ToolMessage(content="deleted", tool_call_id="call_1", id="tool-1")
    human_message = HumanMessage(content="继续", id="human-1")

    result = asyncio.run(
        _invoke_llm_with_retries(
            model,
            [ai_message, human_message],
            max_attempts=2,
            full_history=[ai_message, tool_message, human_message],
        )
    )

    assert result["result"] == "recovered"
    assert model.calls == 2
