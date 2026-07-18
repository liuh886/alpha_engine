# Data and Model Trust Index

> Last updated: 2026-07-18

This document is a **short trust index** — it does not reproduce evidence or gate
results. It points to the authoritative sources that define, prove, and gate research
trustworthiness. All contradictory 2026-06 numbers, PASS claims, and deployment status
from prior versions of this document are superseded by the sources below.

---

## 1. Research Paradigm Specs

The fixed-10D contract is the single source of truth for what each research run
promises. Any run that does not match its declared spec is not comparable.

| Market | Spec | Identity |
|--------|------|----------|
| CN | `configs/research_paradigms/cn_10d_csi300_baseline.yaml` | Contract SHA-256 embedded in evidence manifest |
| US | `configs/research_paradigms/us_10d_qqq_baseline.yaml` | Contract SHA-256 embedded in evidence manifest |

## 2. Latest Evidence

The most recent real-market evidence is at `docs/evidence/issue-124-current-2026-07-16/`.
Both CN and US are **diagnostic-only** (`diagnostic_only=true`, `promotion_eligible=false`,
`trade_ready=false`). No model is trade-ready.

- [Evidence README](../evidence/issue-124-current-2026-07-16/README.md)

Prior evidence packages (`docs/evidence/issue-124/`, `docs/evidence/post-150-current-2026-07-13/`,
`docs/evidence/post-160-cn-verification-2026-07-13/`) remain on disk but are superseded by the
2026-07-16 run.

## 3. ADR Chain

The current research methodology is defined by three sequential ADRs:

| ADR | Status | What it establishes |
|-----|--------|---------------------|
| [ADR-0005](../adr/0005-promotion-decision-single-interface.md) | Accepted | `PromotionDecision` is the single promotion interface; fail-closed on missing evidence |
| [ADR-0006](../adr/0006-spec-bound-default-workflow-runtime.md) | Accepted | Spec-bound execution is the default `ResearchWorkflow` runtime |
| [ADR-0007](../adr/0007-retire-legacy-research-runtime.md) | Accepted | Legacy research runtime (`workflow_legacy.py`, `pipeline.py`) is retired |

## 4. Reproducible Gates

Research trustworthiness is checked by these gates and scripts:

| Gate | Location | What it verifies |
|------|----------|------------------|
| Release gate | `scripts/release_gate.py` | DataSnapshot identity, ModelArtifact checksums, required metrics |
| Promotion gate | `src/research/promotion_decision.py` | Execution identity, data readiness, walk-forward stability |
| Arch contract tests | `tests/test_architecture_contract.py` | Core architecture invariants |
| WF contract tests | `tests/test_research_workflow_contract.py` | ResearchWorkflow step ordering, failure propagation, promotion validation |
| Spec-bound runtime tests | `tests/test_spec_bound_workflow_runtime.py` | Spec resolution, evidence gating, contract identity |
| API contract tests | `tests/test_api_contract.py` | API endpoint behavior, validation, and failure modes |

## 5. Artifact Modules

Immutable, content-addressed artifact modules that underpin trust:

| Module | Purpose |
|--------|---------|
| `src/data/snapshot.py` | `DataSnapshot` — content-addressed, immutable market data |
| `src/models/artifact.py` | `ModelArtifact` — self-contained model bundle with provenance manifest |
| `src/models/metric_contract.py` | `MetricContract` — versioned canonical metric schema (v1) |
| `src/research/promotion_decision.py` | `PromotionDecision` — evidence-gated promotion |
| `src/research/evidence.py` | `EvidenceLedger` — read-only provenance aggregation |

## 6. Current Trust Status

- **Paradigm**: Fixed 10D horizon, spec-bound execution (ADR-0006/0007)
- **Evidence**: Diagnostic-only as of 2026-07-16; promotion was not evaluated by that run
- **Gates**: Fail-closed — missing evidence prevents any promotion
- **Trading**: **Not trade-ready** — no canonical current decision is `trade_guidance_candidate`
- **Deployment**: Research platform only; not deployed for live trading
