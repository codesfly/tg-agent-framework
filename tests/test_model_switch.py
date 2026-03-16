import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.bot.agent_bot import AgentBot
from tg_agent_framework.config import BaseConfig
from tg_agent_framework.memory.runtime_store import RuntimeStateStore


class DummyBot(AgentBot):
    pass


def test_model_switch_uses_injected_graph_factory(tmp_path):
    state_store = RuntimeStateStore(tmp_path / "state")
    config = BaseConfig(llm_model="gpt-4.1")
    observed = {}

    def graph_factory(current_config, current_state_store):
        observed["model"] = current_config.llm_model
        observed["state_store"] = current_state_store
        return {"system_prompt": "custom", "model": current_config.llm_model}, object()

    bot = DummyBot(
        config=config,
        graph={"system_prompt": "old"},
        state_store=state_store,
        graph_factory=graph_factory,
    )

    assert bot._build_graph_for_current_config() == {
        "system_prompt": "custom",
        "model": "gpt-4.1",
    }
    assert observed == {
        "model": "gpt-4.1",
        "state_store": state_store,
    }
