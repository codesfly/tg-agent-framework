# tg-agent-framework Hardening Design

**Date:** 2026-03-16

**Scope:** First-stage hardening for memory integrity, agent runtime stability, and engineering quality gates.

## Goals

- Make runtime state and checkpoint recovery tolerant to corruption and schema evolution.
- Reduce foreground-operation state drift around approval, cancellation, timeout, and restart.
- Add baseline quality gates expected from a reusable framework: CI, lint, type check, and stronger regression coverage.

## Non-Goals

- No new long-term memory backend in this phase.
- No external metrics backend or tracing system in this phase.
- No release workflow, package publishing pipeline, or coverage threshold gate in this phase.

## Design

### 1. Memory Hardening

- Add explicit runtime metadata in SQLite to record schema version and initialization timestamp.
- Keep migrations local and incremental inside `RuntimeStateStore.init_schema()`.
- Wrap persisted graph checkpoints in a versioned envelope with checksum.
- On restore failure:
  - quarantine the bad payload under a timestamped key,
  - clear the active checkpoint key,
  - continue boot with empty graph state instead of failing startup.

### 2. Conversation Trimming

- Add `max_history_messages` to `BaseConfig`.
- Trim messages in two places:
  - before LLM invocation, to limit prompt growth;
  - when the agent node writes back, using `RemoveMessage` so persisted state is also bounded.
- Preserve only the most recent N graph messages; the system prompt stays injected at runtime rather than stored.

### 3. Foreground Operation Stability

- Extend persisted foreground-operation state with:
  - `thread_id`
  - `status`
- Use explicit statuses: `running`, `awaiting_approval`, `cancelling`, `timed_out`, `interrupted`.
- Reject stale or duplicate approval/rejection clicks by checking the current graph state before resuming.
- Mark any leftover persisted operation as interrupted during recovery and notify the user once.

### 4. Quality Gates

- Add `ruff`, `mypy`, and their local configuration in `pyproject.toml`.
- Add a GitHub Actions workflow to run:
  - `ruff check`
  - `ruff format --check`
  - `mypy`
  - `pytest`

### 5. Test Strategy

- Add regression tests for:
  - config resolution by caller/module directory
  - checkpoint corruption fallback
  - runtime schema metadata/version bootstrapping
  - message trimming behavior
  - approval idempotency guard rails
- Keep existing tests for imports, model switch, security, and namespacing.

## Risks And Mitigations

- `RemoveMessage` misuse can corrupt state.
  - Mitigation: cover trimming with targeted tests and keep logic deterministic.
- Stricter lint/type rules may surface many legacy issues.
  - Mitigation: start with a scoped, pragmatic rule set and only tighten once green.
- Recovery logic can regress user-visible Telegram flows.
  - Mitigation: isolate recovery/status formatting and cover with fake graph tests.

## Follow-Up Phase

- Introduce a stable memory backend interface for Redis/Postgres.
- Separate short-term runtime state, conversation memory, and long-term memory explicitly.
- Add structured metrics export / health endpoints / release workflow once runtime semantics are stable.
