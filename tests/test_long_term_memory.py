import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.memory.null import NullMemory
from tg_agent_framework.memory.types import MemoryRecord, MemoryScope


def test_memory_scope_normalizes_global_user_and_thread_scopes():
    assert MemoryScope.global_scope() == MemoryScope(scope_type="global", scope_id="")
    assert MemoryScope(scope_type="global", scope_id="ignored").scope_id == ""
    assert MemoryScope.user_scope(42) == MemoryScope(scope_type="user", scope_id="42")
    assert MemoryScope.thread_scope("tg-42") == MemoryScope(scope_type="thread", scope_id="tg-42")


def test_null_memory_supports_richer_long_term_memory_api():
    async def run():
        memory = NullMemory()
        record = MemoryRecord(
            memory_id="mem-1",
            scope=MemoryScope.user_scope(42),
            kind="fact",
            content="user likes btc",
            metadata={"source": "test"},
        )

        memory_id = await memory.upsert_memory(record)
        memories = await memory.list_memories(MemoryScope.user_scope(42))
        deleted = await memory.delete_memory("mem-1")
        summary = await memory.summarize_scope(MemoryScope.user_scope(42))
        recent_events = await memory.get_recent_events()

        assert memory_id == "mem-1"
        assert memories == []
        assert deleted is False
        assert summary is None
        assert recent_events == []

    asyncio.run(run())
