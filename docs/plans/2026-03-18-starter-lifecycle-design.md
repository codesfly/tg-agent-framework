# tg-agent-framework Starter Lifecycle Design

**Date:** 2026-03-18

**Scope:** Upstream the reusable bootstrap and lifecycle patterns proven in `ops-agent` into `tg-agent-framework`, so newly scaffolded agents start with a complete, production-shaped runtime skeleton instead of a hand-assembled `main.py`.

## Goals

- Standardize agent startup and shutdown around a framework-owned lifecycle.
- Make startup validation, runtime-store initialization, memory initialization, graph creation, bot creation, recovery, and optional scheduler startup consistent across agents.
- Keep `AgentBot`, `build_graph()`, runtime state, and memory primitives reusable without forcing existing agents to rewrite immediately.
- Upgrade the project scaffold so new agents are complete by default and easier to test.

## Non-Goals

- No plugin-discovery system, dependency injection container, or module autoloading.
- No multi-agent handoff, orchestration mesh, or cross-agent message bus in this phase.
- No agent-specific operational summaries or service-health logic from `ops-agent`.
- No new transport adapter beyond Telegram in this phase, though the runtime boundary should not preclude future adapters.

## External References

- OpenHands: separate core runtime from delivery surfaces and keep application assembly explicit.
- LangGraph: durable execution, checkpoint-backed resume, and human-in-the-loop as core runtime semantics.
- OpenAI Agents SDK: sessions, guardrails, and tracing as first-class lifecycle concepts.
- Mastra: starter quality matters; generated projects should feel production-shaped rather than illustrative.
- PydanticAI: ergonomic application assembly with a small amount of user code.

## Design

### 1. Core Architecture

- Add a lightweight `AgentApplication` that orchestrates the startup lifecycle for a single agent runtime.
- Add an `AgentAppSpec[ConfigT]` that describes how to assemble one agent application:
  - `load_config`
  - `build_graph`
  - `create_bot`
  - optional `create_memory`
  - optional `create_scheduler`
  - optional `startup_checks`
- Add an `AgentAppContext[ConfigT]` dataclass to hold shared runtime objects:
  - `config`
  - `state_store`
  - `memory`
  - `graph`
  - `checkpointer`
  - `event_bus`
- Keep the existing Telegram-facing `AgentBot` as the delivery adapter for this phase; `AgentApplication` owns lifecycle, while `AgentBot` owns Telegram I/O.

### 2. Lifecycle Semantics

`AgentApplication` should standardize this sequence:

1. `load_config`
2. `validate_config`
3. `build_app_context`
4. `run_startup_checks`
5. `init_state_store`
6. `init_memory`
7. `build_graph`
8. `create_bot`
9. `create_scheduler`
10. `start`
11. `graceful_shutdown`

Details:

- Validation errors fail fast before any runtime side effects.
- Startup checks return `StartupCheckResult` items with `pass`, `warn`, or `fail`.
- `fail` blocks startup; `warn` logs but does not block.
- Interrupted foreground-operation recovery remains framework-owned and runs before polling starts.
- Scheduler startup and shutdown become framework-managed instead of each agent manually reaching into `bot._bot` or `bot._dp`.

### 3. Public API

- Add `StartupCheckResult`:
  - `name`
  - `status: Literal["pass", "warn", "fail"]`
  - `detail`
- Add `AgentApplication` with public methods:
  - `initialize()`
  - `run()`
  - `shutdown()`
- Make `create_memory` support:
  - sync return
  - async return
  - `None`
- Make `build_graph` accept either:
  - compiled graph only
  - `(compiled_graph, checkpointer)` tuple
- Preserve compatibility:
  - `AgentBot` remains valid on its own
  - `build_graph()` remains a public helper
  - `RuntimeStateStore.from_config()` and `SqliteLongTermMemory.from_config()` remain supported
  - old hand-written `main.py` entrypoints keep working

### 4. Starter And Template Changes

- Change `tg-agent init` templates to generate:
  - `config.py`
  - `app.py` or `bootstrap.py`
  - `main.py` that only runs the application
  - `tools/`
  - `prompts.py`
- The scaffold should show a complete default path:
  - `load_config`
  - runtime state setup
  - optional long-term memory
  - graph factory
  - bot factory
  - application run
- Keep direct-action bot hooks in the template as an extension point, but do not generate agent-specific shortcut logic by default.

### 5. Testing Strategy

- Unit coverage:
  - lifecycle ordering in `AgentApplication`
  - sync and async memory factory handling
  - startup check warning/failure semantics
  - graph/checkpointer normalization
- Integration coverage:
  - minimal app boot path with bot + runtime store + memory
  - interrupted-operation recovery still works under `AgentApplication`
  - optional scheduler path starts and stops correctly
- Scaffold smoke coverage:
  - generated project imports cleanly
  - generated project can build an application without custom edits

### 6. Migration Strategy

- New scaffold uses `AgentApplication` by default.
- Existing agents may migrate gradually by replacing manual `main.py` orchestration with an `AgentAppSpec`.
- `ops-agent` can adopt the new lifecycle later without moving its business-specific tools or summaries into the framework.
- README should present `AgentApplication` as the recommended path and retain manual assembly as a compatibility escape hatch.

## Risks And Mitigations

- A new lifecycle abstraction can become another thin wrapper that leaks internals.
  - Mitigation: keep the spec surface small and use existing public primitives wherever possible.
- Scheduler integration can overfit Telegram-specific startup details.
  - Mitigation: keep scheduler creation optional and context-driven; do not expose `_bot` or `_dp` in the lifecycle API.
- Template upgrades can drift away from the actual framework APIs.
  - Mitigation: add scaffold smoke tests and keep generated code minimal.

## Follow-Up Phase

- Add a transport adapter abstraction so the same lifecycle can back Telegram, CLI, or webhook entrypoints.
- Introduce structured runtime logging/metrics around lifecycle stages.
- Revisit plugin/module composition only if multiple agents demonstrate repeated assembly patterns that cannot be expressed cleanly with `AgentAppSpec`.
