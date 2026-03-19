# Starter Lifecycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a framework-owned starter and lifecycle layer to `tg-agent-framework` so newly built agents have a complete bootstrap path by default while preserving compatibility with existing manually assembled agents.

**Architecture:** Introduce a small `AgentApplication` orchestration layer plus an `AgentAppSpec` and `AgentAppContext`. Keep Telegram delivery in `AgentBot`, keep graph creation in `build_graph()`, and normalize optional memory, startup checks, scheduler ownership, and recovery into a single lifecycle path. Upgrade the scaffold and tests so the recommended path is also the verified path.

**Tech Stack:** Python 3.11+, aiogram, LangGraph, SQLite runtime state, pytest, mypy, ruff

---

### Task 1: Save Design Artifacts

**Files:**
- Create: `docs/plans/2026-03-18-starter-lifecycle-design.md`
- Create: `docs/plans/2026-03-18-starter-lifecycle-implementation.md`

**Step 1: Save the approved design**

Write the validated design to `docs/plans/2026-03-18-starter-lifecycle-design.md`.

**Step 2: Save the implementation plan**

Write this plan to `docs/plans/2026-03-18-starter-lifecycle-implementation.md`.

**Step 3: Verify files exist**

Run: `rg --files docs/plans`
Expected: both starter lifecycle plan files appear

### Task 2: Add Lifecycle Types And Tests First

**Files:**
- Create: `tg_agent_framework/app.py`
- Test: `tests/test_agent_application.py`

**Step 1: Write the failing tests**

Add tests for:
- lifecycle initialization order
- startup check `warn` vs `fail`
- sync memory factory support
- async memory factory support
- graph return normalization for `graph` and `(graph, checkpointer)`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_application.py -v`
Expected: FAIL because `AgentApplication`, `AgentAppSpec`, and related types do not exist yet

**Step 3: Write minimal implementation**

Implement in `tg_agent_framework/app.py`:
- `StartupCheckResult`
- `AgentAppContext`
- `AgentAppSpec`
- `AgentApplication`

Keep the first implementation small and lifecycle-only.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_application.py -v`
Expected: PASS

### Task 3: Integrate Existing Runtime Primitives

**Files:**
- Modify: `tg_agent_framework/app.py`
- Modify: `tg_agent_framework/__init__.py`
- Test: `tests/test_agent_application.py`
- Test: `tests/test_agent_runtime.py`

**Step 1: Write the failing integration tests**

Extend tests for:
- `RuntimeStateStore.from_config()` being the default state-store path
- `NullMemory` fallback when no memory factory is provided
- interrupted foreground-operation recovery running before polling

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_application.py tests/test_agent_runtime.py -v`
Expected: FAIL because the lifecycle does not wire current primitives together yet

**Step 3: Write minimal integration implementation**

Update `AgentApplication` to:
- create the runtime store from config
- initialize runtime schema
- normalize optional memory creation and `init_schema()`
- create the bot with shared context
- run recovery before the polling path
- export the new application types from `tg_agent_framework.__init__`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_application.py tests/test_agent_runtime.py -v`
Expected: PASS

### Task 4: Add Optional Scheduler Ownership

**Files:**
- Modify: `tg_agent_framework/app.py`
- Modify: `tg_agent_framework/scheduler.py`
- Test: `tests/test_agent_application.py`

**Step 1: Write the failing scheduler tests**

Add tests for:
- scheduler omitted path
- scheduler created path
- scheduler start during app run
- scheduler stop during shutdown even on exceptions

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_application.py -v`
Expected: FAIL because scheduler ownership is not implemented

**Step 3: Write minimal scheduler integration**

Teach `AgentApplication` to:
- create an optional scheduler from context
- start it before bot polling
- stop it in `finally`

Avoid leaking Telegram internals into the scheduler API.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_application.py -v`
Expected: PASS

### Task 5: Upgrade Scaffold To Use The New Starter

**Files:**
- Modify: `tg_agent_framework/cli/init.py`
- Test: `tests/test_cli_init.py`

**Step 1: Write the failing scaffold tests**

Add tests for generated files:
- `app.py` exists
- `main.py` only runs the application
- scaffold imports `AgentApplication` and `AgentAppSpec`
- generated graph and bot factories are wired through the application spec

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_init.py -v`
Expected: FAIL because the current scaffold still generates a hand-built `main.py`

**Step 3: Write minimal scaffold changes**

Update templates so generated projects:
- define `build_app()` or `create_app_spec()` in `app.py`
- keep `config.py`, `prompts.py`, `tools/`
- use `main.py` only as a thin entrypoint

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_init.py -v`
Expected: PASS

### Task 6: Refresh Docs And Public Usage

**Files:**
- Modify: `README.md`
- Modify: `tg_agent_framework/__init__.py`

**Step 1: Write the failing documentation expectation**

Define the new recommended developer path:
- scaffold a project
- configure factories in `app.py`
- run the application

**Step 2: Update docs and exports**

Document `AgentApplication` and `AgentAppSpec` as the recommended bootstrap path while preserving the existing manual path as a compatibility option.

**Step 3: Verify documentation references**

Run: `rg -n "AgentApplication|AgentAppSpec|build_app|create_app_spec" README.md tg_agent_framework/__init__.py`
Expected: the new starter path is visible in docs and exports

### Task 7: Full Verification

**Files:**
- Test: `tests/test_agent_application.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_cli_init.py`
- Test: `tests/test_public_api.py`
- Test: `tests/test_config.py`
- Test: `tests/test_runtime_store.py`
- Test: `tests/test_model_switch.py`
- Test: `tests/test_sqlite_long_term_memory.py`

**Step 1: Run targeted tests**

Run:
- `pytest tests/test_agent_application.py -v`
- `pytest tests/test_cli_init.py -v`

Expected: PASS

**Step 2: Run full test suite**

Run: `pytest`
Expected: PASS

**Step 3: Run quality gates**

Run:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`
- `python -m compileall tg_agent_framework tests`

Expected: PASS

**Step 4: Review final diff**

Run: `git status --short`
Expected: only intended framework, test, and local docs changes
