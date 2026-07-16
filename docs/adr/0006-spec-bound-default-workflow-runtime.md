# ADR-0006: Spec-Bound Execution Is the Default ResearchWorkflow Runtime

**Date:** 2026-07-16
**Status:** Accepted
**Module:** `src.research.spec_bound_workflow_executor`
**Interface:** `SpecBoundResearchWorkflowExecutor` (implements `ResearchWorkflowExecutor` Protocol)

## Context

The canonical `ResearchWorkflow` module (`src/research/workflow.py`) defines a
`ResearchWorkflowExecutor` Protocol — a single `run_step(request, step)` seam —
and delegates all execution semantics to an injected executor. Prior to this ADR,
the runtime factory (`workflow_runtime.py`) defaulted to
`LegacyResearchPipelineExecutor`, which calls the legacy `run_research_pipeline`
entry point with free-text goals, module-level defaults for universe/factors/dates,
and no contract identity verification.

A fully proven, identity-gated spec-bound execution path already exists:

- `ResearchParadigmSpec` — a validated, serializable fixed-10D contract
- `build_spec_bound_execution_plan` — builds the immutable declared contract
- `execute_spec_bound_research` — executes, proves contract identity, finalises promotion
- `CNQlibExecutionAdapter` / `USQlibExecutionAdapter` — market-specific adapters
- `PromotionDecision` — evidence-gated, fail-closed, single canonical interface (ADR-0005)

However, this path was not wired into the `ResearchWorkflow` default runtime.
Two parallel execution authorities existed: the spec-bound path (used by scripts
and tests) and the legacy pipeline (used by API/MCP/Agent). This ADR resolves the
fork by making the spec-bound path the single default runtime.

## Decision

**`SpecBoundResearchWorkflowExecutor` is the default `ResearchWorkflowExecutor`.**

- `create_research_workflow()` instantiates a `ResearchWorkflow` backed by
  `SpecBoundResearchWorkflowExecutor`.
- `LegacyResearchPipelineExecutor` is available only through the explicit
  `create_legacy_research_workflow()` factory. No API/MCP default path
  instantiates it.
- Market `cn` maps to `configs/research_paradigms/cn_10d_csi300_baseline.yaml`
  and `us` to `configs/research_paradigms/us_10d_qqq_baseline.yaml`.
- A `request.metadata['spec_path']` override is permitted only when the resolved
  path lives under `configs/research_paradigms` and the loaded spec's `market`
  matches `request.market`. Path traversal, missing files, market mismatches,
  and unsupported markets all fail before any model or data execution.
- The free-text `goal` is preserved as audit metadata only; it does not change
  what the fixed spec executes.
- The executor runs `execute_spec_bound_research` once per workflow run and
  translates the identity-proven result into the canonical `ResearchStep`
  sequence. Reusing one executor for another run causes a new execution rather
  than reusing cached evidence.
- `TRAIN`, `WALK_FORWARD`, and `BACKTEST` complete only when their required
  evidence references are present. The fixed-10D path has no standalone
  attribution artifact, so `ATTRIBUTION` is explicitly `SKIPPED`. A wholly
  skipped spec execution produces a skipped workflow, not a completed one.
- The `PROMOTE` step carries the canonical `promotion_decision` and nothing
  else. Its subject may be the workflow run ID or a spec experiment ID recorded
  by prior steps; unrelated subjects fail closed.
- Heavy Qlib/data execution is injectable via `spec_bound_runner` so contract
  tests remain deterministic and Qlib/data-free.

### Module / Interface / Seam / Adapter

| Layer | Role |
|---|---|
| `ResearchWorkflowExecutor` Protocol (`workflow.py`) | **Interface** — one `run_step` seam |
| `SpecBoundResearchWorkflowExecutor` (`spec_bound_workflow_executor.py`) | **Module** — default implementation, reuses existing spec-bound path |
| `resolve_spec` (`spec_bound_workflow_executor.py`) | **Seam** — spec resolution with market mapping and safe override |
| `SpecBoundRunner` callable | **Seam** — injectable heavy execution; production uses `_default_runner` → `execute_spec_bound_research` |
| `execute_spec_bound_research` (`spec_bound_execution.py`) | **Module** — contract identity gate + promotion finalisation |
| `CNQlibExecutionAdapter` / `USQlibExecutionAdapter` | **Adapter** — market-specific Qlib execution |
| `LegacyResearchPipelineExecutor` (`workflow_legacy.py`) | **Adapter** — explicit compatibility only |
| `workflow_runtime.py` | **Factory** — wires the default |

### Leverage and Locality

- **Leverage**: Reuses the existing spec-bound execution path without duplication.
  No new runner, alignment, evaluation, or gate logic. The spec-bound path's
  contract identity verification and evidence-gated promotion (ADR-0005) become
  the default for every API, MCP, and Agent research invocation.
- **Locality**: The change is confined to the factory (`workflow_runtime.py`) and
  one new module (`spec_bound_workflow_executor.py`). All existing spec-bound
  modules, adapters, and promotion modules are called as-is. Frontend, broker,
  live trading, order management, and model tuning are untouched.

## Consequences

1. Every `ResearchWorkflow.run()` through the default factory executes the
   identity-proven spec-bound path. Contract identity is verified before
   promotion is finalised.
2. Legacy free-text-goal semantics are retired from the default path. Goal is
   audit metadata only.
3. The legacy pipeline remains reachable via `create_legacy_research_workflow()`
   for migration and backward compatibility.
4. Unsupported markets, path traversal attempts, and spec/market mismatches are
   caught at spec resolution time, before any expensive model or data work.
5. Contract tests can inject a `SpecBoundRunner` and remain deterministic
   without Qlib or real market data.
6. The canonical research run directory remains experiment-scoped. Concurrent
   execution of the same declared experiment is outside this adapter's scope
   and must be serialized by callers until artifact storage gains run-scoped
   isolation.
