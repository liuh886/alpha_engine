# Formal Backtest Frontend v1

## Purpose

This contract connects accepted Alpha Engine model backtests to the static Research Artifact Studio. It is intentionally narrower than the research workspace: the frontend publishes named formal baselines, not exploratory experiments.

The publication set is:

- QQQ Rotation v4.2;
- US x1.1;
- CN x1.0;
- BYD Dividend Sleeve V1.0.

## Authority boundary

The durable source is:

```text
data/research/formal_backtests/
├── catalog.json
├── qqqi_qqq_tqqq_v4_2.json
├── us_x1_1.json
├── cn_x1_0.json
└── byd_dividend_sleeve_v1_0.json
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

An explicit user-directed promotion may place a historically supported model in the formal catalog when the registry policy permits it. Such promotion changes publication identity, not evidence semantics: missing fresh holdout evidence must remain disclosed and cannot be converted into `trade_ready=true`.

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
- workflow run, artifact ID and digest where applicable;
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

### BYD Dividend Sleeve V1.0

- source strategy: `v1_dividend_75_25`;
- trace: exact daily adjusted common-open-to-common-open path from the immutable BYD and 515180 artifacts;
- portfolio: 100% BYD in the canonical V1.0 risk-on state; 75% BYD plus 25% 515180.SH in the V1.0 defensive state;
- positions: exact daily BYD, 515180.SH and cash weights;
- transactions: exact next-common-open weight changes with costs allocated across all changed legs;
- attribution: arithmetic daily BYD and 515180 contribution less allocated transition cost;
- benchmark: canonical BYD V1.0 with the defensive 25% left in cash;
- primary cost: 20 bps per absolute weight-change unit; 40 bps remains retained stress evidence;
- historical data cutoff: 2026-08-03;
- operational freshness: append-only paired observations from Issue #529 may advance the formal evidence cutoff and latest target metadata without rewriting the historical performance path;
- promotion authority: explicit user direction in Issue #557;
- fresh historical holdout: unavailable and explicitly disclosed.

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
2. Update the deterministic formal-package builder only when the source evidence contract changes.
3. Regenerate the formal package from immutable source artifacts.
4. Review the generated package, SHA-256 and completeness declaration in a pull request.
5. Merge the repository-backed package.
6. The path-filtered Pages build copies and publishes the new accepted evidence.

Successful CI or a higher metric does not automatically promote a model into this catalog.
