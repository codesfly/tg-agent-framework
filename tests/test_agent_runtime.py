import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram import Dispatcher

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.bot.agent_bot import AgentBot
from tg_agent_framework.config import BaseConfig
from tg_agent_framework.memory.runtime_store import (
    FOREGROUND_STATUS_AWAITING_APPROVAL,
    FOREGROUND_STATUS_RUNNING,
    PersistedForegroundOperation,
    RuntimeStateStore,
)


class DummyBot(AgentBot):
    pass


class FakeTelegramBot:
    def __init__(self):
        self.edits: list[dict] = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class FakeGraph:
    def __init__(self, next_nodes):
        self._snapshot = SimpleNamespace(next=next_nodes)

    def get_state(self, config):
        return self._snapshot


class RecordingGraph(FakeGraph):
    def __init__(self):
        super().__init__(())
        self.calls: list[tuple[dict, dict]] = []

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        return {"messages": []}


def test_runtime_store_persists_foreground_operation_status_and_thread_id(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")
    store.init_schema()
    store.save_foreground_operation(
        PersistedForegroundOperation(
            user_id="42",
            thread_id="tg-42",
            action_label="deploy",
            chat_id=1,
            message_id=2,
            started_at="2026-03-16T18:00:00",
            status=FOREGROUND_STATUS_AWAITING_APPROVAL,
        )
    )

    loaded = store.load_foreground_operations()

    assert loaded == [
        PersistedForegroundOperation(
            user_id="42",
            thread_id="tg-42",
            action_label="deploy",
            chat_id=1,
            message_id=2,
            started_at="2026-03-16T18:00:00",
            status=FOREGROUND_STATUS_AWAITING_APPROVAL,
        )
    ]


def test_recover_interrupted_foreground_operations_notifies_and_clears(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")
    store.init_schema()
    store.save_foreground_operation(
        PersistedForegroundOperation(
            user_id="42",
            thread_id="tg-42",
            action_label="deploy",
            chat_id=1,
            message_id=2,
            started_at="2026-03-16T18:00:00",
            status=FOREGROUND_STATUS_RUNNING,
        )
    )

    bot = DummyBot(
        config=BaseConfig(),
        graph=FakeGraph(()),
        state_store=store,
    )
    fake_tg_bot = FakeTelegramBot()
    bot._bot = fake_tg_bot

    import asyncio

    asyncio.run(bot.recover_interrupted_foreground_operations())

    assert len(fake_tg_bot.edits) == 1
    assert "未执行完成" in fake_tg_bot.edits[0]["text"]
    assert store.load_foreground_operations() == []


def test_dangerous_approval_guard_requires_pending_snapshot(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")
    bot = DummyBot(
        config=BaseConfig(),
        graph=FakeGraph(("dangerous_tools",)),
        state_store=store,
    )

    assert bot._thread_requires_dangerous_approval("tg-42") is True

    bot._graph = FakeGraph(())
    assert bot._thread_requires_dangerous_approval("tg-42") is False


def test_execute_message_operation_preprocesses_user_text_before_graph(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")
    graph = RecordingGraph()

    class PreprocessBot(AgentBot):
        async def preprocess_user_text(self, text, *, thread_id, message=None, callback=None, action=None):
            assert message.from_user.id == 42
            assert callback is None
            assert action is None
            return f"{text}::{thread_id}::{message.from_user.id}"

    bot = PreprocessBot(
        config=BaseConfig(),
        graph=graph,
        state_store=store,
    )

    result = asyncio.run(
        bot._execute_message_operation(
            user_text="hello",
            message=SimpleNamespace(from_user=SimpleNamespace(id=42)),
            thread_id="tg-42",
        )
    )

    assert result == {"messages": []}
    assert graph.calls[0][0]["messages"][0].content == "hello::tg-42::42"


def test_register_handlers_runs_additional_handler_hook(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")

    class HookBot(AgentBot):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.hook_ran = False

        def register_additional_handlers(self):
            self.hook_ran = True

    bot = HookBot(
        config=BaseConfig(),
        graph=FakeGraph(()),
        state_store=store,
    )
    bot._dp = Dispatcher()
    bot._bot = object()

    bot._register_handlers()

    assert bot.hook_ran is True
