# ADR-0007: Retire the Legacy Research Runtime

**Date:** 2026-07-18
**Status:** Accepted
**Supersedes:** ADR-0006 § "Consequences" item 3 (legacy compatibility clause)

## Context

ADR-0006 made `SpecBoundResearchWorkflowExecutor` the default `ResearchWorkflow`
runtime. It preserved a compatibility escape hatch — `create_legacy_research_workflow()`
— so callers could temporarily fall back to `LegacyResearchPipelineExecutor` backed by
`src/research/pipeline.py`.

A production caller audit confirmed that no production code calls
`create_legacy_research_workflow()`, `LegacyResearchPipelineExecutor`, or
`run_research_pipeline()` directly. The only references to these symbols lived in:

- Their own unit/contract tests (`test_pipeline_contract.py`,
  `TestLegacyPipelineExecutor` in `test_research_workflow_contract.py`,
  `TestPipelineFailureRecording` in `test_api_contract.py`,
  `TestResearchPipeline` in `test_financial_logic.py`)
- The `test_legacy_factory_still_available` test in
  `test_spec_bound_workflow_runtime.py`
- Stale architecture docs and ADR-0006's own compatibility clause

No API router, MCP tool, agent default, or script imports the legacy adapter.
Every production invocation goes through `create_research_workflow()` →
`SpecBoundResearchWorkflowExecutor` → the identity-proven spec-bound path.

## Decision

**The legacy research runtime is retired.** Specifically:

- `src/research/workflow_legacy.py` and `src/research/pipeline.py` are deleted.
- `create_legacy_research_workflow()` is removed from `workflow_runtime.py`.
- All docstring references claiming the legacy adapter remains available are
  removed.
- Pipeline-only tests that exercised the retired `ResearchRun`/`Step`/`StepStatus`
  dataclasses are removed from `test_research_workflow_contract.py`,
  `test_api_contract.py`, `test_financial_logic.py`, and
  `test_spec_bound_workflow_runtime.py`.
- `tests/test_pipeline_contract.py` is retired. Two unique contracts that
  exercise the surviving orchestration layer (`run_training_pipeline` in
  `src.workflows.hooks` and `ResearchService.run_training_pipeline`) are
  preserved in `tests/test_training_pipeline_contract.py`.

## Why canonical PromotionDecision / ResearchWorkflow tests remain

The following test suites are **not** affected by this retirement and continue
to provide full coverage:

| Suite | What it covers | Why it survives |
|---|---|---|
| `test_promotion_decision.py` | `PromotionDecision` dataclass, `build_promotion_decision`, gate logic | ADR-0005 canonical interface |
| `test_promotion_consumers.py` | Consumer views (frontend, registry, agents, MCP) | ADR-0005 adapter contracts |
| `test_research_workflow_contract.py` | `ResearchWorkflow.run()`, step ordering, failure propagation, store roundtrip, promotion validation | ADR-0006 canonical workflow |
| `test_spec_bound_workflow_runtime.py` | `SpecBoundResearchWorkflowExecutor`, spec resolution, evidence gating, contract identity | ADR-0006 default runtime |
| `test_workflow_status_audit.py` | Terminal statuses including `_pipeline_gate_outcome` | Gate outcome contract (survives pipeline retirement) |
| `test_training_pipeline_contract.py` | Snapshot propagation and single-artifact emission | Orchestration layer (preserved from retired suite) |

## Consequences

1. The legacy `ResearchRun`/`Step`/`StepStatus` dataclasses and
   `run_research_pipeline()` function are gone. No compatibility adapter exists.
2. `create_research_workflow()` is the sole factory. Every research invocation
   goes through the identity-proven spec-bound path.
3. ADR-0006's compatibility clause (Consequence item 3) is superseded.
4. Historical ADR-0005 context — including its table listing `pipeline.py` as an
   adapter — remains intact as a record of the migration path.
5. The two preserved orchestration-layer contracts ensure that
   `run_training_pipeline` (hooks) and `ResearchService.run_training_pipeline`
   continue to be covered after the pipeline dataclasses are removed.
