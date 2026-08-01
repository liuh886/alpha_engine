# Selected-Pool Price Repair v1

## Problem

The first frozen CN 130 ranker retest did not reach model fitting because the
committed source layer is incomplete:

- 88 candidates are ready;
- 23 selected candidates have no committed CSV;
- 19 selected candidates fail OHLC relationship checks;
- CSI 300 is ready.

The invalid rows are consistent with mixing adjusted close with differently
adjusted OPEN/HIGH/LOW values. The selected pool must not be reduced to bypass
these defects.

US 87 is separately blocked by missing verified Millicom (`TIGO`) coverage.
`TYGO` is Tigo Energy and cannot be substituted.

## Workflow

`refresh_selected_pool_prices.py` creates an isolated build:

1. load the exact active selected pool;
2. audit every candidate and benchmark source;
3. copy already valid source files;
4. fetch only missing or invalid symbols through the auditable provider router;
5. validate canonical OHLCV, amount and factor fields;
6. cap rows at the declared evidence cutoff;
7. write normalized files into a staging directory;
8. build a manifest-bound Qlib provider;
9. write source attempts, provider aliases, hashes and coverage evidence;
10. atomically publish the isolated output only after every required source is
    valid.

The authoritative `data/csv_clean` directory is never modified in place.

## Initial provider order

CN:

1. EFinance;
2. AkShare;
3. BaoStock.

US:

1. Yahoo Finance through the maintained adapter.

Every failed attempt remains visible in the refresh manifest. A later source
adapter may be added, but the workflow cannot silently repair values or change
pool membership.

## Adjustment boundary

The output follows `corporate_action_store_v1`:

- feature and label prices use one consistent adjusted OHLCV contract;
- execution prices remain a separate raw-price concern;
- a declared cutoff prevents later corporate actions from rewriting frozen
  evidence;
- source files, normalized output and Qlib provider files are separate layers.

## Current role

This PR establishes and exercises the reusable repair workflow. A successful CN
live run will prove that all 42 blocked CN sources can be rebuilt into an exact
130-name provider. A successful US run must additionally verify that TIGO is
Millicom and not TYGO.

Only after the isolated source passes all checks should PR #289 consume the same
workflow and execute the frozen ranker experiment.
