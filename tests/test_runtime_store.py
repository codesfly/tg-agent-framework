import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.memory.runtime_store import (
    PersistedForegroundOperation,
    RuntimeStateStore,
)


def test_runtime_state_is_namespaced_per_bot(tmp_path):
    shared_state_dir = tmp_path / "shared-state"
    store_a = RuntimeStateStore(shared_state_dir, namespace="bot-a")
    store_b = RuntimeStateStore(shared_state_dir, namespace="bot-b")
    store_a.init_schema()
    store_b.init_schema()

    store_a.set_thread_id(1001, "thread-a")
    store_b.set_thread_id(1001, "thread-b")
    store_a.save_blob("graph_checkpointer_v2", b"a")
    store_b.save_blob("graph_checkpointer_v2", b"b")
    store_a.save_foreground_operation(
        PersistedForegroundOperation(
            user_id="1001",
            action_label="op-a",
            chat_id=1,
            message_id=11,
            started_at="2026-03-16T10:00:00",
        )
    )

    assert store_a.get_thread_id(1001) == "thread-a"
    assert store_b.get_thread_id(1001) == "thread-b"
    assert store_a.load_blob("graph_checkpointer_v2") == b"a"
    assert store_b.load_blob("graph_checkpointer_v2") == b"b"
    assert [operation.action_label for operation in store_a.load_foreground_operations()] == [
        "op-a"
    ]
    assert store_b.load_foreground_operations() == []
