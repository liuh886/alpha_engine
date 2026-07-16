# ADR-0005: PromotionDecision Is the Single Promotion Interface

**Date:** 2026-07-16
**Status:** Accepted
**Module:** `src.research.promotion_decision`
**Interface:** `PromotionDecision`

## Context

The legacy research pipeline (`src.research.pipeline.py`) contained a
promotion gate that emitted `DEPLOY` whenever `mean_ic > 0.1`.  This gate
lived **inside** the pipeline's promote step, owned no evidence references,
and was invisible to downstream consumers (EvidenceLedger, dashboard, agents,
registry).

A richer, evidence-gated promotion decision module was added later
(`promotion_decision.py`) that evaluates execution identity, data readiness,
walk-forward stability, and multiple metric thresholds before declaring
`trade_ready`.  However, the legacy `mean_ic` gate was never revoked — two
parallel promotion authorities existed.

## Decision

**The `PromotionDecision` dataclass and its `build_promotion_decision` /
`build_promotion_decision_from_run` / `finalize_promotion_decision`
functions are the single canonical Interface for promotion semantics.**

- The legacy pipeline's promote step **must not** declare `DEPLOY` (or any
  deployment recommendation) from any single metric, including `mean_ic`.
- The promote step **must** delegate to `finalize_promotion_decision`
  and fail closed as `MISSING_EVIDENCE` when the required evidence files
  (`execution_identity.json`, `data_readiness.json`,
  `walk_forward_stability.json`) are absent.
- `EvidenceLedger.from_research_run` **must not** treat a legacy top-level
  `recommendation` string (`"deploy"`, `"promote"`, `"DEPLOY"`) as
  authoritative. It must validate the run-scoped
  `research_runs/{run_id}/promotion_decision.json`, verify its subject identity,
  or return an explicit non-promoted status.
- `ResearchWorkflow` exposes the canonical `promotion_decision` payload as a
  top-level field.  Invalid legacy payloads such as
  `{"recommendation": "DEPLOY"}` fail the workflow and cannot leave it
  completed.
- All consumer views (`promotion_consumers.py`) validate the canonical
  payload before rendering — they never recompute gates.

## Seams and Adapters

| Layer | Role |
|---|---|
| `promotion_decision.py` | **Module** — gates, status enum, frozen `PromotionDecision` |
| `promotion_consumers.py` | **Adapter** — renders canonical decision into consumer-specific views (frontend, registry, agents, model decision pack) |
| `pipeline.py` promote step | **Adapter** — finalizes a run-scoped canonical artifact and emits its decision dict |
| `workflow.py` PROMOTE step | **Adapter** — validates step output via `validate_promotion_payload` before storing in result |
| `evidence.py` EvidenceLedger | **Adapter** — reads `promotion_decision.json` when available; never promotes from legacy strings |
| `mcp_server.py` research tools | **Adapter** — reports workflow execution separately from promotion status and `trade_ready` |

## Consequences

### Leverage
- Single source of truth for promotion decisions.
- Migrated consumer views (frontend payload, registry, agents, MCP) receive
  the same validated decision rather than recomputing gates.
- Evidence references and contract hashes are always included in the
  decision payload for audit trails.

### Locality
- Gate logic lives in one Module (`promotion_decision.py`).
- Adapters do not own or duplicate promotion semantics.
- Test contracts are small and Qlib-free: the `PromotionDecision`
  constructor and `build_promotion_decision` take plain dicts.

### Risks
- Existing runs without evidence files always receive `MISSING_EVIDENCE`
  — this is the intended fail-closed behavior, but it means that the
  canonical promotion path requires the evidence pipeline to be run first.
- Legacy consumers that read `run.recommendation` directly must migrate.
