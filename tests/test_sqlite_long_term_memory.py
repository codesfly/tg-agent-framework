import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.memory.sqlite_memory import SqliteLongTermMemory
from tg_agent_framework.memory.types import MemoryRecord, MemoryScope


def test_sqlite_long_term_memory_crud_and_summary(tmp_path):
    async def run():
        memory = SqliteLongTermMemory(tmp_path / "state", namespace="bot-a")
        await memory.init_schema()

        fact = MemoryRecord(
            memory_id="fact-1",
            scope=MemoryScope.user_scope(42),
            kind="fact",
            content="user likes btc",
            metadata={"source": "chat"},
        )
        summary = MemoryRecord(
            memory_id="summary-1",
            scope=MemoryScope.user_scope(42),
            kind="summary",
            content="BTC-focused user",
        )

        fact_id = await memory.upsert_memory(fact)
        await memory.upsert_memory(summary)
        memories = await memory.list_memories(MemoryScope.user_scope(42))
        facts = await memory.list_memories(MemoryScope.user_scope(42), kind="fact")
        summary_text = await memory.summarize_scope(MemoryScope.user_scope(42))
        deleted = await memory.delete_memory(fact_id)
        remaining = await memory.list_memories(MemoryScope.user_scope(42))

        assert fact_id == "fact-1"
        assert [record.memory_id for record in memories] == ["summary-1", "fact-1"]
        assert [record.memory_id for record in facts] == ["fact-1"]
        assert summary_text == "BTC-focused user"
        assert deleted is True
        assert [record.memory_id for record in remaining] == ["summary-1"]

    asyncio.run(run())


def test_sqlite_long_term_memory_is_namespaced_and_record_event_stays_compatible(tmp_path):
    async def run():
        shared_state_dir = tmp_path / "shared-state"
        memory_a = SqliteLongTermMemory(shared_state_dir, namespace="bot-a")
        memory_b = SqliteLongTermMemory(shared_state_dir, namespace="bot-b")
        await memory_a.init_schema()
        await memory_b.init_schema()

        await memory_a.upsert_memory(
            MemoryRecord(
                memory_id="pref-1",
                scope=MemoryScope.thread_scope("tg-42"),
                kind="preference",
                content="prefer concise replies",
            )
        )
        await memory_a.record_event(
            event_type="tool_execution",
            description="confirmed dangerous tool",
            service="telegram",
            triggered_by="42",
            metadata={"tool": "deploy"},
        )

        scope_a = await memory_a.list_memories(MemoryScope.thread_scope("tg-42"))
        scope_b = await memory_b.list_memories(MemoryScope.thread_scope("tg-42"))
        recent_events = await memory_a.get_recent_events()

        assert [record.memory_id for record in scope_a] == ["pref-1"]
        assert scope_b == []
        assert recent_events == [
            {
                "event_type": "tool_execution",
                "description": "confirmed dangerous tool",
                "service": "telegram",
                "triggered_by": "42",
                "metadata": {"tool": "deploy"},
                "created_at": recent_events[0]["created_at"],
                "updated_at": recent_events[0]["updated_at"],
            }
        ]

    asyncio.run(run())
