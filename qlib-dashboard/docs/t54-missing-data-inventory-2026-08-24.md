# T54 — Frontend Missing-Data Inventory and Disposition

Date: 2026-08-24 · Scope: strategy console fallback surfaces · research_only=true, trade_ready=false

## Method

Audited every console surface that renders fallback placeholders (`—`, `N/A`,
`Unknown`, `Unavailable`) against the payloads published by
`export_repository_research_data` and the model-run bundle v2 builders.

## Findings and disposition

| # | Surface | Missing input | Disposition |
|---|---------|---------------|-------------|
| 1 | Holdings/positions names (`PositionsTable.tsx`) | CN numeric symbols with no display-name artifact in the bundle | **Fixed (T53)** — `export_repository_research_data` now publishes `name_map.json` from the governed registry `configs/name_map.yaml`; `useNameMap` already resolves it and falls back to the raw ticker only for unknown symbols. |
| 2 | Attribution rows (`AttributionEvidence.tsx`, `AttributionInterpretation.tsx`) | `semantics` context absent on some bundles; `value` null rows excluded from charts; `turnover` absent | Builder-level population required per model family; tracked as follow-up for new publications. Legacy bundles keep explicit `Unknown` labels — no fabricated values. |
| 3 | Core metric cards | Legacy (pre-T48) bundles lack derived IR / Max Drawdown fields | Cards must keep showing `Unavailable` for legacy models; new models publish the full metric contract (`src/models/metric_contract.py`). Backfilling legacy evidence is forbidden without re-publication through governed pipelines. |
| 4 | Model provenance metadata | Pre-T48 models lack `DataSnapshot ID`, `latest_completed_session`, digest signatures | Same policy as (3): identity fields are populated at registration time since T48; legacy rows stay visibly incomplete rather than silently backfilled. |

## Rules applied

- No frontend domain scoring or silent value fabrication; fallbacks remain literal.
- New data enters only through governed builders/exporters with research boundary flags.
- Legacy-model gaps are displayed honestly; closing them requires governed re-publication.
