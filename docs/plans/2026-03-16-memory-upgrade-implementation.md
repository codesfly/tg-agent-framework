# Memory Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce stable runtime and long-term memory interfaces plus a default SQLite long-term memory implementation without breaking current agents.

**Architecture:** Keep runtime state and long-term memory as separate planes. `RuntimeStateStore` continues as the SQLite runtime backend, while a new SQLite memory store handles `MemoryRecord` data behind a richer `BaseMemory`/`LongTermMemoryStore` API. Existing bot/checkpointer flows remain intact.

**Tech Stack:** Python 3.11+, SQLite, dataclasses, pytest, ruff, mypy

---

### Task 1: Memory Types And Interfaces

**Files:**
- Create: `tg_agent_framework/memory/types.py`
- Create: `tg_agent_framework/memory/runtime_backend.py`
- Modify: `tg_agent_framework/memory/base.py`
- Modify: `tg_agent_framework/memory/null.py`
- Test: `tests/test_long_term_memory.py`

**Step 1: Write the failing tests**

Add tests for:
- `MemoryScope` normalization for `global`, `user`, and `thread`
- `NullMemory` supporting the richer API with safe empty results

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_long_term_memory.py -v`
Expected: FAIL because types/interfaces do not exist yet

**Step 3: Write minimal implementation**

Implement:
- `MemoryScopeType`
- `MemoryKind`
- `MemoryScope`
- `MemoryRecord`
- `RuntimeStateBackend` protocol
- richer concrete methods on `BaseMemory`
- `NullMemory` no-op implementations for the richer API

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_long_term_memory.py -v`
Expected: PASS

### Task 2: SQLite Long-Term Memory

**Files:**
- Create: `tg_agent_framework/memory/sqlite_memory.py`
- Modify: `tg_agent_framework/__init__.py`
- Test: `tests/test_sqlite_long_term_memory.py`

**Step 1: Write the failing tests**

Add tests for:
- `upsert_memory`
- `list_memories`
- `delete_memory`
- `summarize_scope`
- namespace isolation
- `record_event` compatibility

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sqlite_long_term_memory.py -v`
Expected: FAIL because SQLite memory implementation does not exist

**Step 3: Write minimal implementation**

Implement `SqliteLongTermMemory` with:
- `memory_store.sqlite3`
- `init_schema()`
- namespaced CRUD
- `record_event()` writing `kind="event"`
- `get_recent_events()` adapting stored records back to dicts

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sqlite_long_term_memory.py -v`
Expected: PASS

### Task 3: Runtime Backend Abstraction

**Files:**
- Modify: `tg_agent_framework/memory/runtime_store.py`
- Modify: `tg_agent_framework/memory/checkpointer.py`
- Modify: `tg_agent_framework/graph.py`
- Modify: `tg_agent_framework/bot/agent_bot.py`
- Test: `tests/test_runtime_backend_contract.py`

**Step 1: Write the failing tests**

Add tests proving:
- `RuntimeStateStore` satisfies the runtime backend contract
- `PersistentMemorySaver` accepts the abstract backend type

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runtime_backend_contract.py -v`
Expected: FAIL because concrete types are still hard-coded

**Step 3: Write minimal implementation**

Update type annotations and imports so:
- `RuntimeStateStore` implements `RuntimeStateBackend`
- `checkpointer`, `graph`, and `AgentBot` consume the interface

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runtime_backend_contract.py -v`
Expected: PASS

### Task 4: Public API And Docs Surface

**Files:**
- Modify: `README.md`
- Modify: `tg_agent_framework/cli/init.py`
- Modify: `tests/test_public_api.py`

**Step 1: Write the failing tests**

Add tests covering public exports for:
- `MemoryScope`
- `MemoryRecord`
- `RuntimeStateBackend`
- `SqliteLongTermMemory`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_public_api.py -v`
Expected: FAIL because the new API is not exported

**Step 3: Write minimal implementation**

Update exports and scaffold/readme examples to expose the new memory layer cleanly.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_public_api.py -v`
Expected: PASS

### Task 5: Full Verification

**Files:**
- Test: `tests/test_agent_bot.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_config.py`
- Test: `tests/test_graph_trimming.py`
- Test: `tests/test_long_term_memory.py`
- Test: `tests/test_memory_hardening.py`
- Test: `tests/test_model_switch.py`
- Test: `tests/test_public_api.py`
- Test: `tests/test_runtime_backend_contract.py`
- Test: `tests/test_runtime_store.py`
- Test: `tests/test_security.py`
- Test: `tests/test_sqlite_long_term_memory.py`

**Step 1: Run the full test suite**

Run: `pytest`
Expected: PASS

**Step 2: Run quality gates**

Run:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`
- `python -m compileall tg_agent_framework tests`

Expected: PASS

**Step 3: Review resulting diff**

Run: `git status --short`
Expected: source changes only; local docs remain unstaged
