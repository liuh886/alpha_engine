# A-Share Pool Provider Contract

Date: 2026-07-30  
Parent issue: #220

## Purpose

Define and test the source-neutral data contract required before the frozen `cn_small_pool_v1` pool can enter observed-performance validation.

This stage validates identities, adjustment declarations, point-in-time status logic, the China trading calendar, file hashes, and the reserved-evidence cutoff. It does not certify that any fixture or externally supplied CSV is factually authoritative.

## Existing adapter assessment

The repository already contains AkShare, BaoStock, and EFinance adapters for China daily bars.

- AkShare supplies forward-adjusted A-share OHLCV and unadjusted index OHLCV. This change adds explicit ChiNext `399006` index support alongside CSI 300 `000300`.
- BaoStock currently supplies daily OHLCV through its existing adapter contract.
- EFinance currently supplies forward-adjusted daily OHLCV.

None of the existing daily-bar adapters exposes the complete point-in-time status set required by the frozen research contract:

- listed and first eligible date;
- suspension;
- ST status;
- delisting status;
- limit-up or limit-down state at the assumed execution open;
- executable-at-open state.

Therefore, daily bars alone cannot be promoted into authoritative A-share validation evidence.

## Composite evidence contract

The provider artifact may combine separately declared source roles:

1. one candidate-bar provider using one adjustment convention;
2. one reference-index bar provider;
3. one point-in-time status provider;
4. one China trading-calendar provider.

Every row records its source role. The normalizer rejects mixed candidate providers, mixed reference providers, mixed status providers, mixed calendars, and mixed adjustment conventions.

## Fail-closed checks

The builder rejects:

- duplicate date/symbol rows;
- missing frozen identities;
- unconfigured identities;
- non-positive or internally inconsistent OHLC;
- negative volume;
- bars without matching point-in-time status;
- bars on unlisted, suspended, or delisted sessions;
- a tradable flag while unlisted, suspended, or delisted;
- simultaneous limit-up and limit-down;
- dates outside the declared open trading calendar;
- any downstream row dated 2026-07-01 or later.

Six-digit provider symbols are read as strings before exchange-aware canonical normalization, preserving leading zeros.

## Outputs

A successful contract input produces:

- `cn_pool_bars.csv`;
- `cn_pool_status.csv`;
- `cn_trading_calendar.csv`;
- `provider_manifest.json`;
- `data_quality_report.json`;
- `decision.json`.

Input, contract, frozen membership, and output hashes are recorded.

## Authority boundary

The contract test decision is `cn_provider_contract_ready`, but it also records:

- `provider_contract_passed=true`;
- `live_provider_run_completed=false`;
- `source_attestation_verified=false`;
- `authoritative_provider_artifact=false`;
- `performance_evaluated=false`;
- `reserved_performance_opened=false`.

Issue #220 remains open after this contract foundation merges. It may close only after a real source-bound run supplies and verifies the required point-in-time status evidence through 2026-06-30.

## Next step

Select and implement the live source combination, record provider and library/API versions, generate the complete frozen-pool artifacts, and review the data-quality report before Issue #221 is allowed to calculate any strategy return.
