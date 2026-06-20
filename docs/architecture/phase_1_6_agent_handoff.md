# Phase 1-6 Agent Handoff

Status: architecture convergence complete, hardening sprint done
Date: 2026-06-19

This document is the next-step operating map for agents continuing the Alpha Engine architecture convergence work. It is intentionally prescriptive: later agents should use it as the default rule set unless a newer ADR supersedes it.

## Current Direction

Alpha Engine is converging toward a small set of domain seams:

- Research work enters through `src.research.workflow*`.
- Evidence and promotion readiness enter through `src.research.evidence`.
- Strategy execution enters through `src.execution`.
- Legacy Qlib, MLflow, subprocess, and orchestrator behavior stays behind adapters.
- UI, MCP, API, assistant services, and system tools are adapters. They should not own research semantics or assemble divergent workflow commands.

The near-term goal is not to delete the legacy runtime. The goal is to make every caller go through a stable intent-shaped interface before reaching legacy execution.

## Already Established

- Domain language and accepted decisions:
  - `CONTEXT.md`
  - `docs/adr/0001-domain-and-evidence-first-architecture.md`
  - `docs/adr/0002-adapters-must-not-own-research-semantics.md`
  - `docs/adr/0003-single-user-local-quant-research-platform.md`
- Research workflow interface:
  - `src/research/workflow_types.py`
  - `src/research/workflow.py`
  - `src/research/workflow_store.py`
  - `src/research/workflow_runtime.py`
  - `src/research/workflow_legacy.py`
- Evidence interface:
  - `src/research/evidence.py`
  - `src/api/routers/evidence.py`
- Strategy execution interface:
  - `src/execution/models.py`
  - `src/execution/engine.py`
  - `src/execution/adapter.py`
- Shared workflow command envelope:
  - `src/workflows/commands.py`

## Non-Negotiable Rules

1. Do not reintroduce direct workflow command construction in UI/API/service callers. Use `src.workflows.commands`.
2. Do not import Qlib, MLflow, FastAPI, `src.api`, `src.workflows.hooks`, or `src.agents.research_loop` from the research core modules.
3. Do not import Qlib from `src.execution`.
4. Assistant services must not import dashboard job command builders (`src.dashboard.backtest_job`, `src.dashboard.backtest_runner`).
5. New adapters may depend on legacy runtime code. Core modules may not.
6. Keep legacy behavior compatible until there is a golden-output test proving a safe replacement.
7. Every moved entry point needs a contract test before or with the migration.
8. Do not broaden a refactor across unrelated dirty files. This repo currently has many parallel edits.

## Current Verification Gates

Run these before claiming a slice is complete:

```powershell
uv run ruff check src tests api_server.py
uv run pytest -q
cd qlib-dashboard
npm run lint
npm run build
```

Targeted tests that guard the new seams:

```powershell
uv run pytest tests/test_architecture_contract.py -q
uv run pytest tests/test_research_workflow_contract.py tests/test_research_api_adapter.py tests/test_workflow_api_adapter.py -q
uv run pytest tests/test_evidence_ledger.py tests/test_evidence_api_contract.py tests/test_model_promotion_evidence.py -q
uv run pytest tests/test_strategy_execution_contract.py tests/test_strategy_execution_adapter.py -q
uv run pytest tests/test_dashboard_backtest_runner.py tests/test_backtest_service.py tests/test_mcp_server_contract.py -q
```

## Next Development Slices

### Slice 1: Legacy Workflow Runtime Adapter Cleanup

Write scope:

- `src/workflows/hooks.py`
- `src/research/workflow_legacy.py`
- tests around workflow hooks and research workflow

Goal:

- Keep Qlib/MLflow details in `src/workflows/hooks.py` or a dedicated legacy adapter.
- Make `src/research/workflow_legacy.py` the only research workflow bridge into hooks.
- Add tests proving canonical step results are preserved when the legacy hook succeeds or fails.

Do not:

- Change API/router behavior in the same slice.
- Rewrite the full Qlib training pipeline.

### Slice 2: System Router Command Registry

Write scope:

- `src/api/routers/system.py`
- `src/workflows/commands.py`
- tests for system router runtime endpoints

Goal:

- Replace `SAFE_COMMANDS` hardcoded orchestrator lists for train/backtest with the shared workflow command envelope.
- Keep non-workflow commands (`data_update`, `arena_settle`) as explicit safe commands unless a better command registry is introduced.

Do not:

- Add shell string execution.
- Remove the current allowlist behavior.

### Slice 3: Agent Tool Orchestrator Adapter

Write scope:

- `src/agents/tools/orchestrator_tools.py`
- possibly `src/workflows/commands.py`
- related tests

Goal:

- Route agent-triggered train/backtest command construction through `src.workflows.commands`.
- Preserve subprocess execution only as an adapter behavior.

Do not:

- Import agent tools from research core.
- Move research semantics into tool wrappers.

### Slice 4: Research Pipeline Hook Dependency

Write scope:

- `src/research/pipeline.py`
- `src/research/workflow_legacy.py`
- tests for pipeline/workflow behavior

Goal:

- Decide whether `src/research/pipeline.py` is still core research or a legacy runtime adapter.
- If it is core, remove its direct dependency on `src.workflows.hooks`.
- If it is legacy, move or document it as adapter-owned.

Do not:

- Mix this with factor scanner, registry, or dashboard work.

### Slice 5: Job Execution Envelope Persistence

Write scope:

- `src/assistant/job_service.py`
- `src/workflows/commands.py`
- job service persistence/resilience tests

Goal:

- Treat persisted `command_envelopes` as first-class job intent.
- Keep `commands` as rendered compatibility output until all callers are migrated.
- Add tests proving old jobs with only `commands` still run.

Do not:

- Break existing job database records.

### Slice 6: Execution Adapter Integration

Write scope:

- `src/execution`
- strategy adapter tests
- only touch `src/strategies/*` after golden-output tests exist

Goal:

- Expand `StrategyExecutionAdapter` from request construction to a real comparison harness for existing Qlib strategies.
- Add golden tests proving vectorized and non-vectorized strategy outputs are equivalent for representative inputs.

Do not:

- Import Qlib into `src/execution`.
- Replace live strategy behavior without golden tests.

## Recommended Agent Assignments

Use one worker per slice. Do not let two workers edit the same slice.

Prompt template:

```text
You are working in D:\Documents\GitHub\alpha_engine.
Read docs/architecture/phase_1_6_agent_handoff.md first.
You are not alone in the codebase. Do not revert unrelated changes.
Own only Slice <N>: <slice title>.
Stay within the listed write scope unless you find a hard blocker.
Add or update contract tests before claiming completion.
Run targeted tests, then report changed files and verification results.
```

## Completion Definition

A slice is complete only when:

- the caller uses the intended seam,
- old behavior is preserved or deliberately documented as changed,
- a contract test prevents regression,
- targeted tests pass,
- full backend ruff/pytest pass if the slice touched Python runtime code,
- dashboard lint/build pass if frontend or static artifact behavior changed.

## Known Remaining Risk

The codebase still contains direct subprocess and orchestrator references. Some are legitimate legacy adapters; others should be migrated through the slices above. Use this scan as the starting point:

```powershell
rg -n "src\.agents\.research_loop|src\.workflows\.hooks|subprocess\.run|subprocess\.Popen|src\.orchestrator" src
```

## Release Readiness Checklist

Run this before any release or handoff:

```powershell
# 1. Backend quality gates
uv run ruff check src tests api_server.py
uv run pytest -q

# 2. Dashboard quality gates
cd qlib-dashboard
npm run lint
npm run build
cd ..

# 3. Architecture contract tests
uv run pytest tests/test_architecture_contract.py -q
uv run pytest tests/test_research_workflow_contract.py -q
uv run pytest tests/test_strategy_execution_contract.py -q
uv run pytest tests/test_evidence_ledger.py -q
uv run pytest tests/test_api_contract.py -q
```

### Sprint Completion Status (2026-06-19)

- H1 Command Intent Integrity: DONE
  - `WorkflowCommandEnvelope.to_argv()` now splits multi-word interpreters into separate argv tokens
  - Agent tools use envelope; handwritten fallback removed
  - System router uses envelope for train/backtest
- H2 Job Intent Persistence: DONE
  - `JobService` stores `command_envelope_json` (list of envelopes)
  - Accepts both singular and plural forms for backward compat
  - Always exposes `command_envelopes` (list) in decoded rows
- H3 Legacy Runtime Boundary: DONE
  - `pipeline.py` documented as legacy adapter bridge
  - Canonical path through `workflow_legacy.py` injects `_train_fn`
  - Test verifies canonical path imports hooks directly, not through pipeline fallback
- H4 Execution Golden Harness: DONE
  - 5 golden tests with deterministic fixtures (scores, positions, tradability, risk)
  - Tests cover: topk selection, sell unscored, tradability blocking, determinism, JSON roundtrip
  - `src/execution` remains Qlib-free
- H5 Runtime Observability: DONE
  - Evidence bundles expose `subject_type`, `subject_id`, `generated_at` for tracing
  - Missing evidence returns explicit `missing_artifact` status
  - Tests verify provenance fields and missing-evidence behavior
- H6 Release Readiness Gate: DONE
  - Checklist documented above
  - Handoff document updated from skeleton to current status
