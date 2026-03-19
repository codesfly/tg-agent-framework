# tg-agent-framework Memory Upgrade Design

**Date:** 2026-03-16

**Scope:** Second-stage memory/runtime architecture upgrade after first-stage hardening.

## Goals

- Separate runtime state from long-term memory semantics.
- Introduce stable interfaces so future backends can replace SQLite without rewriting bot/checkpointer logic.
- Add a default SQLite long-term memory implementation that works with current agents and preserves the existing `BaseMemory` event API.

## Non-Goals

- No Redis/Postgres backend in this phase.
- No vector search, embedding retrieval, or automatic LLM summarization in this phase.
- No mandatory agent behavior change that requires existing bots to start using long-term memory immediately.

## Architecture

### 1. Two Memory Planes

- **Runtime plane**
  - Holds thread ids, foreground operations, checkpoint blobs, and related metadata.
  - Exposed through a new `RuntimeStateBackend` interface.
  - `RuntimeStateStore` remains the default SQLite implementation.

- **Long-term memory plane**
  - Holds durable user/thread/global memory records.
  - Exposed through a new `LongTermMemoryStore` interface.
  - `SqliteLongTermMemory` becomes the default first-party implementation.

This separation keeps restart/recovery concerns isolated from memory retrieval concerns.

### 2. Long-Term Memory Model

- `MemoryScope`
  - `scope_type`: `global`, `user`, or `thread`
  - `scope_id`: string identifier, empty for `global`

- `MemoryRecord`
  - `memory_id`
  - `scope`
  - `kind`: `event`, `fact`, `preference`, `summary`
  - `content`
  - `metadata`
  - `created_at`
  - `updated_at`

The initial implementation uses one SQLite table with namespace-aware filtering and simple indexed lookups.

### 3. Compatibility Strategy

- Keep `AgentBot(memory=...)` unchanged.
- Keep `BaseMemory.record_event()` and `BaseMemory.get_recent_events()` available.
- Add concrete default methods to `BaseMemory` for the richer long-term memory API so older subclasses do not break at import time.
- `NullMemory` implements the richer API as no-op / empty-return behavior.

### 4. SQLite Layout

- Runtime state remains in `runtime_state.sqlite3`.
- Long-term memory lives in `memory_store.sqlite3`.
- New `memories` table:
  - `memory_id`
  - `namespace`
  - `scope_type`
  - `scope_id`
  - `kind`
  - `content`
  - `metadata_json`
  - `created_at`
  - `updated_at`
- Index:
  - `(namespace, scope_type, scope_id, kind, updated_at DESC)`

### 5. API Surface

- New interface: `RuntimeStateBackend`
- New interface: `LongTermMemoryStore`
- New default implementation: `SqliteLongTermMemory`
- `PersistentMemorySaver`, `build_graph()`, and `AgentBot` depend on `RuntimeStateBackend` instead of the concrete SQLite class.

### 6. Testing Strategy

- Add unit tests for memory types and SQLite long-term memory CRUD.
- Add namespace/scope isolation tests.
- Add compatibility tests showing:
  - `record_event()` persists an `event` record.
  - `get_recent_events()` still returns the expected dict-shaped payload.
  - `NullMemory` remains safe to inject into `AgentBot`.
- Keep all existing runtime/checkpointer/bot tests green.

## Risks And Mitigations

- **Risk:** Over-abstracting too early.
  - **Mitigation:** Keep interfaces minimal and aligned with currently used operations.
- **Risk:** Breaking existing custom `BaseMemory` subclasses.
  - **Mitigation:** New methods on `BaseMemory` are concrete defaults, not new abstract requirements.
- **Risk:** Scope semantics drift later.
  - **Mitigation:** Define `MemoryScope`/`MemoryRecord` now and centralize scope normalization.

## Follow-Up Phase

- Add Redis/Postgres implementations behind the same interfaces.
- Add automatic summary refresh and retrieval policies.
- Add optional search/ranking for long-term memory retrieval.
