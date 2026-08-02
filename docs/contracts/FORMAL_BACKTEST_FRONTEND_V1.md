# Formal Backtest Frontend v1

## Purpose

This contract connects accepted Alpha Engine model backtests to the static Research Artifact Studio. It is intentionally narrower than the research workspace: the frontend publishes named formal baselines, not exploratory experiments.

The initial publication set is:

- QQQ Rotation v4.2;
- US x1.1;
- CN x1.0.

## Authority boundary

The durable source is:

```text
data/research/formal_backtests/
├── catalog.json
├── qqqi_qqq_tqqq_v4_2.json
├── us_x1_1.json
└── cn_x1_0.json
```

`catalog.json` is the publication allow-list. A notebook, workflow artifact, candidate result or research report is not visible in the model selector merely because it exists elsewhere in the repository.

The static build runs `qlib-dashboard/scripts/sync-formal-backtests.mjs`. It validates the catalog, every package SHA-256, the record type, publication status and research boundary before copying the accepted packages into the Pages bundle.

## Eligibility

A frontend package must declare:

```json
{
  "schema_version": "1.0.0",
  "record_type": "formal_model_backtest",
  "publication_status": "accepted_formal_baseline",
  "model_id": "...",
  "research_only": true,
  "trade_ready": false
}
```

The publication gate rejects:

- exploratory experiments;
- parameter or candidate grids;
- rejected candidates;
- shadow strategies;
- weakened research boundaries;
- catalog/package identity mismatches;
- missing or mismatched hashes;
- packages without a retained performance path.

## Package fields

A formal package contains:

- `backtest_id`, `model_id`, display name, market and benchmark;
- generation time, evidence cutoff and date range;
- trace frequency;
- headline metrics;
- frozen portfolio and cost contract;
- retained performance path;
- retained positions, transactions and attribution when available;
- window or chronological summaries;
- workflow run, artifact ID and digest;
- evidence-completeness status;
- interpretation limits;
- hard `research_only=true`, `trade_ready=false` boundaries.

## Trace semantics

The frontend must show the trace frequency next to the backtest identity. Curves with different semantics are not silently described as daily equity curves.

### QQQ Rotation v4.2

- trace: exact daily adjusted open-to-open path;
- positions: exact daily QQQI, QQQ and TQQQ weights;
- transactions: exact state-transition weight changes;
- attribution: arithmetic daily instrument contribution less allocated transition cost;
- source artifact: `8820398584`.

### US x1.1

- trace: exact non-overlapping 10-session portfolio periods;
- positions: exact Top-15 equal-weight holdings at every rebalance;
- transactions: complete BUY, SELL, HOLD, INCREASE and DECREASE ledger;
- attribution: retained security, window and regime decomposition;
- source artifact: `8834620874`;
- the accepted package excludes 2026H1.

### CN x1.0

- trace: exact retained half-year window metrics only;
- positions: final Top-15 selection snapshot for each retained window;
- transaction and contribution ledgers: unavailable in the accepted source artifact;
- source artifact: `8828889722`.

The frontend must not infer a daily or rebalance curve for CN x1.0.

## Frontend loading

The browser loads the repository research bundle for shared model metadata, then loads the formal-backtest catalog. The final model array is rebuilt in catalog order, so records not in the formal catalog never enter the selector, Backtests view or comparison pages.

The Backtests workspace exposes:

1. Performance;
2. Holdings;
3. Trades;
4. Attribution;
5. Evidence.

When a component was not retained, the corresponding view shows an explicit unavailable state rather than an empty fabricated table.

## Offline behavior

The service worker caches validated formal-backtest packages after they are requested online. This allows the installed read-only shell to reopen the previously viewed formal evidence offline.

## Updating a formal baseline

1. Produce and validate the complete governed backtest artifact.
2. Update `scripts/build_formal_model_backtests.py` only when the source evidence contract changes.
3. Regenerate the formal package from immutable source artifacts.
4. Review the generated package, SHA-256 and completeness declaration in a pull request.
5. Merge the repository-backed package.
6. The path-filtered Pages build copies and publishes the new accepted evidence.

Successful CI or a higher metric does not automatically promote a model into this catalog.
