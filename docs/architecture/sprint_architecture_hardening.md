# Architecture Hardening Sprint

Status: completed; superseded by release readiness roadmap
Date: 2026-06-19
Depends on: `docs/architecture/phase_1_6_agent_handoff.md`

## Baseline Check

The Phase 1-6 work is broadly in place and the current verification baseline is green:

```powershell
uv run ruff check src tests api_server.py
uv run pytest -q
cd qlib-dashboard
npm run lint
npm run build
```

Latest observed results on 2026-06-19:

- Backend ruff: passed
- Backend pytest: 404 passed, 14 skipped, 9 warnings
- Dashboard lint: passed
- Dashboard build: passed

This sprint has completed its architecture-hardening role. The next roadmap moves the project toward a publishable release candidate.
The next work is to remove hidden execution risks, strengthen contracts, and turn
migration seams into durable product/runtime interfaces.

## Inspection Findings

### F1: System router command argv may be malformed

`src/api/routers/system.py` builds workflow commands via `WorkflowCommandEnvelope`, but
passes `python_exe="uv run python"`. `to_argv()` currently treats `python_exe` as a
single argv item, which is not a valid executable for `subprocess.Popen(list)`.

Risk: `/api/system/exec` can pass tests while failing at runtime for train/backtest.

### F2: JobService stores singular `command_envelope`, callers emit plural `command_envelopes`

`BacktestService`, `TrainingService`, and dashboard jobs emit `command_envelopes`.
`JobService.create_job()` persists only `command_envelope`.

Risk: the claimed first-class job intent is not reliably persisted or recoverable.

### F3: Research pipeline still has a direct fallback import to `src.workflows.hooks`

`src/research/pipeline.py` accepts injected `_train_fn`, but still falls back to
`from src.workflows.hooks import run_training_pipeline` when called directly.

Risk: the canonical workflow seam is bypassable, and future callers may re-couple
research core to legacy runtime.

### F4: Agent orchestrator tool keeps a handwritten command fallback

`src/agents/tools/orchestrator_tools.py` uses `WorkflowCommandEnvelope`, but falls back
to direct `python -m src.orchestrator ...` construction for non-standard modes.

Risk: command behavior diverges across agent tools, system router, MCP, and dashboard.

### F5: Current command registry tests are too shallow

`tests/test_api_contract.py` checks string inclusion, not argv token correctness,
rendered command compatibility, or old-job fallback behavior.

Risk: command envelope regressions can ship with a green suite.

### F6: Execution adapter is not yet proven against live strategy behavior

`src/execution/adapter.py` builds and executes deterministic requests, but current tests
cover contract shape rather than golden equivalence against existing Qlib strategy output.

Risk: the new execution seam can drift from existing live strategy behavior.

## Sprint Goal

Make the Phase 1-6 architecture shippable by proving that all runtime entry points use
stable intent interfaces, all legacy adapters are explicitly contained, and all new seams
have regression tests that fail for realistic runtime breakage.

## Sprint Workstreams

### H1: Command Intent Integrity

Write scope:

- `src/workflows/commands.py`
- `src/api/routers/system.py`
- `src/api/mcp_server.py`
- `src/agents/tools/orchestrator_tools.py`
- command-related tests

Tasks:

1. Change command rendering so an interpreter command can be represented as argv parts,
   not a single string. Prefer `python_args: list[str]` or a helper like
   `render_with_interpreter(["uv", "run", "python"], envelope)`.
2. Remove handwritten orchestrator fallback from agent tools unless it is modeled as a
   named explicit legacy action.
3. Add tests for exact argv tokens for dashboard, MCP, system router, and agent tools.
4. Add a contract that workflow command construction has exactly one implementation
   module: `src.workflows.commands`.

Acceptance:

- No workflow caller hand-assembles `python -m src.orchestrator` outside
  `src/workflows/commands.py` or an explicitly named legacy adapter.
- System router train/backtest commands start with valid argv tokens, e.g.
  `['uv', 'run', 'python', '-m', 'src.orchestrator', ...]`.

### H2: Job Intent Persistence

Write scope:

- `src/assistant/job_service.py`
- `src/assistant/services/backtest_service.py`
- `src/assistant/services/training_service.py`
- job service tests

Tasks:

1. Standardize on `command_envelopes` as a list in job payloads and persistence.
2. Preserve backward compatibility for old rows that only have `commands_json`.
3. If a job has `command_envelopes` and no `commands`, render commands at execution time.
4. Add tests for:
   - storing and loading `command_envelopes`,
   - executing old command-only jobs,
   - rendering envelope-only jobs,
   - preserving dashboard/backtest/training job metadata.

Acceptance:

- JobService returns `command_envelopes` for newly created workflow jobs.
- Old jobs without envelopes still run.
- New envelope-only jobs can run without pre-rendered commands.

### H3: Legacy Runtime Boundary

Write scope:

- `src/research/pipeline.py`
- `src/research/workflow_legacy.py`
- `src/workflows/hooks.py`
- workflow/pipeline tests

Tasks:

1. Decide and encode whether `src/research/pipeline.py` is core research or a legacy
   adapter bridge.
2. If it remains core, remove the direct hooks fallback and require injection.
3. If it is legacy, document that status and exclude it from core import assumptions.
4. Add a test that canonical workflow execution injects the legacy training function and
   direct core modules do not import hooks.

Acceptance:

- There is no ambiguous direct dependency from research core to `src.workflows.hooks`.
- Failure and success paths still produce canonical `ResearchWorkflowResult` steps.

### H4: Execution Golden Harness

Write scope:

- `src/execution`
- strategy execution tests
- narrowly scoped fixtures under tests

Tasks:

1. Create deterministic fixtures for scores, positions, tradability, and risk config.
2. Compare `StrategyExecutionAdapter` output against expected legacy strategy decisions
   for biweekly and vectorized strategy profiles.
3. Add a golden test for vectorized vs non-vectorized equivalence at the execution-plan
   level.
4. Keep Qlib out of `src/execution`; put any live-Qlib fixture setup in tests or a legacy
   adapter module.

Acceptance:

- Execution adapter has golden coverage beyond shape tests.
- `src/execution` remains Qlib-free.

### H5: Runtime Observability and Evidence Wiring

Write scope:

- `src/research/evidence.py`
- model promotion/service code
- job/research workflow summaries
- dashboard/API response tests if touched

Tasks:

1. Ensure research workflow results, model promotion, and job records expose evidence or
   provenance identifiers consistently.
2. Add a minimal job/research run summary contract that answers: what intent ran, what
   artifact was used, what evidence supports promotion.
3. Add tests for missing evidence and partial evidence behavior.

Acceptance:

- A promoted model or completed workflow can be traced back to a durable evidence bundle
  or an explicit missing-evidence status.

### H6: Release Readiness Gate

Write scope:

- tests only unless a gate exposes a defect
- docs if command names or runbooks change

Tasks:

1. Add a single command or documented checklist for backend + dashboard gates.
2. Add targeted smoke tests for:
   - system exec command rendering,
   - MCP backtest command rendering,
   - research workflow API submission,
   - evidence API lookup,
   - dashboard build.
3. Update `docs/architecture/phase_1_6_agent_handoff.md` with final status after this
   sprint lands.

Acceptance:

- A new agent can verify the architecture baseline without reading the whole codebase.

## Recommended Agent Assignment

Use one worker per workstream. H1 and H2 should run first because they affect runtime
command execution and job persistence. H3 and H4 can run in parallel after H1/H2 contracts
are clear. H5 and H6 should be last.

Suggested order:

1. H1 Command Intent Integrity
2. H2 Job Intent Persistence
3. H3 Legacy Runtime Boundary
4. H4 Execution Golden Harness
5. H5 Runtime Observability and Evidence Wiring
6. H6 Release Readiness Gate

## Prompt Template

```text
You are working in D:\Documents\GitHub\alpha_engine.
Read docs/architecture/phase_1_6_agent_handoff.md and docs/architecture/sprint_architecture_hardening.md first.
You are not alone in the codebase. Do not revert unrelated changes.
Own only H<N>: <workstream title>.
Stay inside the listed write scope unless you find a hard blocker.
Add regression tests that would fail on the inspection finding for your workstream.
Run targeted tests and report changed files plus verification results.
```

## Done Definition

The sprint is complete only when:

- all H1-H6 acceptance criteria are met,
- `uv run ruff check src tests api_server.py` passes,
- `uv run pytest -q` passes,
- `npm run lint` and `npm run build` pass in `qlib-dashboard`,
- the handoff document is updated from active skeleton to current architecture status.

