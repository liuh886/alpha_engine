# Factor Knowledge System Roadmap

Parent charter: `docs/research/factor_knowledge_system_charter_2026-07-31.md`

## Workstream 1 — Registry v2

Goal: make every factor record evidence-complete and fail-closed.

Deliverables:

- versioned factor identity and factor-family taxonomy;
- authoritative versus legacy evidence status;
- provider, universe, benchmark, horizon, cost, and evidence-manifest identities;
- economic and risk metrics including return, drawdown, turnover, holding duration, downside capture, and concentration;
- explicit failed gates, failure class, and lessons learned;
- registry migration preserving all existing rows;
- removal of the rule that missing metrics are treated as non-failing;
- no current `Active` label survives automatically without current-contract evidence.

## Workstream 2 — Historical factor backfill

Goal: reconstruct a searchable record of every material factor family already tested.

Deliverables:

- deterministic import from maintained reports, specs, manifests, and the legacy SQLite registry;
- canonical factor cards for legacy technical scans, residual trend, Bollinger, MACD, RSI, close-location, tree-model OHLCV families, hierarchical basket/security components, and state-machine components;
- evidence-completeness report;
- invalid or non-PIT results classified as `legacy_unverified`, not deleted;
- factor family conclusions and lessons learned.

## Workstream 3 — Factor relationship map

Goal: understand complementarity before constructing combinations.

Deliverables:

- aligned factor score series;
- factor portfolio-return series;
- score correlation, return correlation, selection overlap, and churn matrices;
- redundancy clusters by market and basket;
- regime and market-specific behavior;
- turnover and concentration contribution by factor;
- add-one and leave-one-out diagnostics.

## Workstream 4 — Low-turnover multi-factor experiment

Goal: evaluate one frozen, simple multi-factor candidate selected from distinct information families.

Initial admissible families:

- growth acceleration;
- quality/profitability improvement;
- valuation or cash-flow yield;
- medium-term relative trend;
- low-risk/downside resilience;
- revisions/events after point-in-time data become available.

Contract:

- choose a small predeclared candidate set using the completed factor map;
- at most one primary factor from each highly correlated cluster;
- equal weights before any learned weights;
- monthly evaluation;
- entry/retention buffers;
- minimum holding period;
- bounded replacements per rebalance;
- strict turnover and holding-duration gates;
- compare with every standalone member, equal-weight pool, and benchmark;
- require positive incremental or risk-reduction contribution from each included factor;
- one observed run, no post-result search.

## Workstream 5 — Market learning report

Goal: convert experiments into cumulative understanding.

Each cycle updates:

- robust findings;
- market-specific clues;
- disproven hypotheses;
- factor redundancies and useful combinations;
- data limitations;
- unresolved questions;
- the next experiment justified by the accumulated record.

## Relationship to Issue #225

Issue #225 becomes the first new-standard factor card and data-pipeline test. It does not by itself define the final strategy. Its standalone evidence will later be considered alongside other distinct factor families for the first frozen multi-factor experiment.
