# QQQ / QQQI / TQQQ Provider Data v1

Status: active research-data contract  
Parent issues: #296, #309  
Research only: true  
Trade ready: false

## Scope

This implementation completes the highest-value subset of Provider Phase 2. It
adds one credentialed professional US end-of-day provider and applies it first
to the executable ETF basket used by the active QQQI / QQQ / TQQQ rotation
research.

It does not attempt to complete professional coverage for all US 87 equities,
add intraday data, integrate a broker, or implement a second professional source.

## Why the ETF basket needs its own contract

The strategy derives signals at the close and executes at the next open. It
therefore requires adjusted open and close prices on one coherent basis. Close-
only adjustment is insufficient.

The three instruments also have different corporate-action risks:

- QQQ is the benchmark and signal reference;
- QQQI distributes material cash income and has a short history beginning in
  2024;
- TQQQ is leveraged and its split history must not appear as an economic crash.

No QQQI history is synthesized before its first actual provider observation.
The common three-ETF window begins at the latest first observation across QQQ,
QQQI and TQQQ.

## Provider policy

### Tiingo EOD

When `TIINGO_API_TOKEN` is configured, Tiingo is the preferred canonical source.
The adapter retains:

- adjusted open, high, low, close and volume;
- raw open, high, low, close and volume;
- adjustment factor;
- cash distribution;
- split factor;
- exact ticker metadata.

The adapter fails closed on identity mismatch, missing adjusted fields, invalid
splits or incoherent OHLC.

### Yahoo fallback

Yahoo remains an independent research fallback and reconciliation source. Its
synthetic `close * volume` amount is diagnostic only and is not treated as
reported turnover.

A Yahoo-only bundle may set `strategy_data_ready=true` when all three canonical
series are valid. It must set `professional_source_ready=false`.

## Reconciliation

When Tiingo is available, adjusted open-to-open and close-to-close returns are
compared with Yahoo on common sessions. Each instrument receives one status:

- `consensus`;
- `explainable_corporate_action_difference`;
- `provider_missing`;
- `quarantine`.

A quarantined Tiingo series is not selected as canonical. Corporate-action
explanations are permitted only inside a frozen session window around Tiingo's
recorded cash-distribution or split dates.

## Bundle contents

The build command writes:

- `canonical/<symbol>.csv`;
- `sources/tiingo/<symbol>.csv` when credentials are available;
- `sources/yfinance/<symbol>.csv`;
- `corporate_actions/<symbol>.csv`;
- combined coverage, reconciliation and corporate-action tables;
- `bundle_manifest.json` with contract, provider, source and canonical hashes.

Build locally:

```bash
uv run python scripts/data/build_etf_reference_bundle.py \
  --output-root artifacts/data/qqqi_qqq_tqqq_reference_bundle_v1
```

Require professional evidence explicitly:

```bash
uv run python scripts/data/build_etf_reference_bundle.py \
  --output-root artifacts/data/qqqi_qqq_tqqq_reference_bundle_v1 \
  --require-professional
```

## Strategy integration

The v4.1 and v4.2 prospective monitors now accept:

```text
--etf-data-bundle artifacts/data/qqqi_qqq_tqqq_reference_bundle_v1
```

QQQ, QQQI and TQQQ are loaded from the hash-verified canonical bundle. VIX and
VXN remain direct non-executable reference fetches. The bundle identity,
selected providers, reconciliation statuses and readiness fields are written
into the strategy summary, evidence manifest and persistent run record.

This data change does not alter signals, thresholds, allocations, execution
rules, transaction costs or promotion status.

## Deferred Phase 2 work

- Tiingo coverage and reconciliation for the complete US 87 pool;
- Massive/Polygon as a second professional provider;
- exchange-calendar coverage gates;
- long-lived provider reliability scoring;
- complete US symbol-history reconstruction.
