# Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden tg-agent-framework memory recovery, runtime stability, and engineering quality gates without introducing a new memory backend.

**Architecture:** Keep the current SQLite + LangGraph design, but add versioned runtime metadata, bounded message history, checkpoint quarantine on corruption, and stricter runtime guards around approval/recovery flows. Quality gates are added through local tool config and a single GitHub Actions workflow.

**Tech Stack:** Python 3.11+, LangGraph, aiogram, pytest, ruff, mypy, GitHub Actions

---

### Task 1: Design Artifacts

**Files:**
- Create: `docs/plans/2026-03-16-hardening-design.md`
- Create: `docs/plans/2026-03-16-hardening-implementation.md`

**Step 1: Save the approved design**

Write the validated hardening design to `docs/plans/2026-03-16-hardening-design.md`.

**Step 2: Save the implementation plan**

Write this plan to `docs/plans/2026-03-16-hardening-implementation.md`.

**Step 3: Verify files exist**

Run: `rg --files docs/plans`
Expected: both hardening plan files appear

### Task 2: Runtime Metadata And Corruption Recovery

**Files:**
- Modify: `tg_agent_framework/memory/runtime_store.py`
- Modify: `tg_agent_framework/memory/checkpointer.py`
- Test: `tests/test_memory_hardening.py`

**Step 1: Write the failing tests**

Add tests for:
- schema metadata/version bootstrapping
- corrupted checkpoint payload quarantine + empty restore

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_hardening.py -v`
Expected: FAIL because metadata/quarantine helpers do not exist yet

**Step 3: Write minimal implementation**

Implement:
- metadata table and schema version management
- checkpoint envelope with checksum
- corruption quarantine path in restore

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_hardening.py -v`
Expected: PASS

### Task 3: Message Trimming

**Files:**
- Modify: `tg_agent_framework/config.py`
- Modify: `tg_agent_framework/graph.py`
- Test: `tests/test_graph_trimming.py`

**Step 1: Write the failing tests**

Add tests for:
- prompt-side trimming before LLM invocation
- persisted-state trimming via `RemoveMessage`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_trimming.py -v`
Expected: FAIL because trimming is not implemented

**Step 3: Write minimal implementation**

Add `max_history_messages` config and trim helpers in graph execution.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_graph_trimming.py -v`
Expected: PASS

### Task 4: Foreground Operation Hardening

**Files:**
- Modify: `tg_agent_framework/memory/runtime_store.py`
- Modify: `tg_agent_framework/bot/agent_bot.py`
- Test: `tests/test_agent_runtime.py`

**Step 1: Write the failing tests**

Add tests for:
- persisted foreground-operation statuses
- stale approval click rejection
- duplicate approval/rejection idempotency
- recovery marking interrupted operations

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_runtime.py -v`
Expected: FAIL because status/guard logic is incomplete

**Step 3: Write minimal implementation**

Implement:
- status/thread persistence
- recovery transition to interrupted
- approval/rejection guards against stale graph state

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_runtime.py -v`
Expected: PASS

### Task 5: Lint And Type Check Configuration

**Files:**
- Modify: `pyproject.toml`

**Step 1: Write the failing validation commands**

Choose target commands:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`

**Step 2: Run validation to verify current config is incomplete**

Run each command after adding the test/dev dependencies but before final fixes.
Expected: tool config missing or code issues reported

**Step 3: Write minimal configuration**

Add:
- dev dependencies for `ruff` and `mypy`
- `[tool.ruff]`
- `[tool.mypy]`

**Step 4: Run validation to verify it passes**

Run:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`
Expected: PASS

### Task 6: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Write the failing expectation**

Define a workflow that must run lint, format check, type check, and tests on GitHub pushes and PRs.

**Step 2: Add minimal workflow**

Implement a Python workflow that installs the package with dev dependencies and runs:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`
- `pytest`

**Step 3: Verify workflow file shape**

Run: `sed -n '1,240p' .github/workflows/ci.yml`
Expected: workflow contains all four jobs/steps in one pipeline

### Task 7: Full Verification

**Files:**
- Test: `tests/test_public_api.py`
- Test: `tests/test_config.py`
- Test: `tests/test_agent_bot.py`
- Test: `tests/test_runtime_store.py`
- Test: `tests/test_model_switch.py`
- Test: `tests/test_security.py`
- Test: `tests/test_memory_hardening.py`
- Test: `tests/test_graph_trimming.py`
- Test: `tests/test_agent_runtime.py`

**Step 1: Run full test suite**

Run: `pytest`
Expected: PASS

**Step 2: Run full quality gate locally**

Run:
- `ruff check .`
- `ruff format --check .`
- `mypy tg_agent_framework`
- `python -m compileall tg_agent_framework tests`
Expected: PASS

**Step 3: Review resulting diff**

Run: `git status --short`
Expected: only intended local changes
