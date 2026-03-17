import asyncio
import json
import sys
from pathlib import Path

import pytest

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
