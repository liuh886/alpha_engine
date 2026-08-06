# Formal Backtest Frontend Contract

## Purpose

This contract connects accepted Alpha Engine model backtests to the static Research Artifact Studio. The frontend publishes named formal baselines only; exploratory experiments, rejected candidates and shadow strategies remain outside the formal selector.

The current accepted publication set is:

1. QQQ Rotation v4.2;
2. US x1.1;
3. CN x1.1;
4. BYD Dividend Sleeve V1.0.

All four remain `research_only=true` and `trade_ready=false`.

## One publication authority, two representations

The accepted-model allow-list is declared by:

```text
data/research/formal_backtests/catalog.json
```

The browser reads the deterministic Model Run Bundle v2 projection:

```text
data/research/formal_model_runs/catalog.json
```

The Bundle v2 catalog is generated from the accepted v1 catalog by `scripts/sync_formal_bundle_v2.py`. It is not a separately curated allow-list. CI requires exact model-ID parity between both catalogs and rejects:

- a missing accepted model;
- an additional unaccepted model;
- duplicate model versions;
- package or manifest hash drift;
- weakened research boundaries.

Frontend code must not maintain another hard-coded list of accepted model IDs.

## Eligibility

A source formal package must declare:

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

Its Bundle v2 manifest must preserve the same model identity, publication status, evidence cutoff and research boundary. Projection may organize retained evidence into sections, but may not rerun a model, reconstruct missing evidence or reopen model selection.

## Bundle v2 evidence sections

A formal run may expose:

- `summary`;
- `performance`;
- `risk`;
- `robustness`;
- `portfolio`;
- `trades`;
- `attribution`;
- `diagnostics`;
- `lineage`.

Unavailable evidence remains explicitly declared. The browser must never infer a daily curve, trade ledger, attribution result or annualized statistic that the accepted source did not retain.

## Trace semantics

### QQQ Rotation v4.2

- exact daily adjusted open-to-open path;
- exact daily QQQI, QQQ and TQQQ weights;
- exact state-transition changes;
- arithmetic instrument contribution less allocated transition cost.

### US x1.1

- exact non-overlapping 10-session portfolio periods;
- exact Top-15 holdings at each rebalance;
- complete retained transaction ledger;
- retained security, window and regime attribution.

### CN x1.1

- promoted regime-gated sector-breadth baseline;
- formal evidence cutoff and reporting range are taken from its accepted source package;
- complete retained performance, risk, robustness, portfolio, trades, attribution, diagnostics and lineage sections;
- CN x1.0 remains superseded evidence and must not re-enter the accepted catalog.

### BYD Dividend Sleeve V1.0

- source strategy: `v1_dividend_75_25`;
- exact daily adjusted common-open-to-common-open path;
- 100% BYD in the canonical risk-on state;
- 75% BYD plus 25% 515180.SH in the defensive state;
- exact daily positions, next-common-open changes and contribution attribution;
- benchmark: canonical BYD V1.0 with the defensive 25% retained as cash;
- historical evidence is projected without recomputation;
- prospective observations may advance operational metadata but may not rewrite the accepted historical path.

## Freshness semantics

Hash validity and historical reproducibility do not mean a package is current.

The formal freshness policy declares the latest completed market session and the next close after which that declaration becomes stale. The scheduled freshness watchdog runs `scripts/verify_formal_backtest_freshness.py --as-of now` and reports one of:

- `current`;
- `stale`;
- `blocked`;
- `unknown` in the browser when no valid operational receipt can be loaded.

A stale package remains readable historical evidence, but must not be presented as current operational output.

## Frontend loading

The browser validates the Bundle v2 catalog, manifest hashes, bundle identities and required summary sections before exposing formal runs. The accepted formal set is derived from the verified catalog at runtime.

The Backtests workspace exposes:

1. Performance;
2. Risk and robustness;
3. Portfolio;
4. Trades;
5. Attribution;
6. Evidence boundary.

Missing sections show an explicit unavailable state.

## Offline behavior

The service worker may cache previously validated formal evidence for offline review. Cached evidence must retain its original cutoff and freshness status; offline availability must not be interpreted as current data.

## Updating a formal baseline

1. Resolve the latest completed trading session for the relevant market.
2. Refresh governed providers and fail closed on incomplete pool or benchmark coverage.
3. Extend only permitted reporting evidence while preserving immutable accepted-history prefixes.
4. Regenerate the accepted v1 package and Bundle v2 projection in the same review branch.
5. Verify catalog parity, hashes, evidence cutoffs and research boundaries.
6. Review and merge the update through a pull request.
7. Publish Pages and verify the live-origin release.

Successful CI, a newer date or a higher metric does not automatically promote or replace a model.
