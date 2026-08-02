# Yahoo adjustment-mode audit — 2026-08-02

## Decision

**`bounded_subset_reproducible`**

The controlled ten-symbol subset was downloaded twice under three Yahoo/yfinance modes. All six snapshots per symbol were retained. Within this bounded run, raw bars, Adj Close, automatic adjustment and repair behavior were reproducible.

- workflow: `30741674075`;
- artifact: `8831499091`;
- artifact digest: `sha256:7e46de8dd9943e805cc4a4ac7fb99d096ecdc9a38f10624f64201925240c83e1`;
- symbols: AAPL, ASML, AVGO, GOOGL, META, MSFT, NVDA, QQQ, TSM and VRT;
- period: 2021-01-01 through 2026-07-31;
- research only; `trade_ready=false`.

## Controlled modes

Each symbol was fetched twice under:

1. `auto_adjust=True`, `repair=True`;
2. `auto_adjust=True`, `repair=False`;
3. `auto_adjust=False`, `repair=False`.

Raw mode retained Open, High, Low, Close, Adj Close and Volume.

## Reproducibility result

| Mode | Exact A/B matches | Material matches at 1e-8 | Maximum relative difference |
|---|---:|---:|---:|
| Adjusted with repair | 10/10 | 10/10 | 0 |
| Adjusted without repair | 10/10 | 10/10 | 0 |
| Raw OHLCV + Adj Close without repair | 10/10 | 10/10 | 0 |

For all ten symbols:

- raw OHLCV was byte-identical between passes A and B;
- Adj Close was byte-identical between passes A and B;
- adjusted OHLC was byte-identical between passes A and B;
- row calendars and volumes were identical.

## Repair effect

`adjusted_repair` and `adjusted_no_repair` were exactly identical for all ten symbols in both passes.

Therefore the audit provides no evidence that `repair=True` caused or amplified the previously observed same-day full-refresh drift.

This does not prove that repair can never change a Yahoo series. It establishes that repair was inactive or deterministic for this bounded symbol/date set at the audit time.

## Deterministic adjustment check

Adjusted OHLC was independently reconstructed from raw OHLC and the ratio:

`Adj Close / raw Close`

The reconstructed frame matched yfinance automatic adjustment materially for all ten symbols in both passes.

- nine symbols matched exactly;
- TSM differed only in a small number of close values at approximately `1.19×10⁻¹⁶` relative magnitude;
- no difference exceeded the `1e-8` material tolerance;
- no economic return or rank difference can reasonably be attributed to this machine-scale arithmetic order effect.

This confirms that yfinance automatic adjustment is deterministic when the underlying raw OHLC and Adj Close snapshot is fixed.

## Relationship to the full US87 audit

PR #384 previously built two complete sequential US87 refreshes and found:

- 41 symbols identical;
- 47 symbols with proportional adjusted-OHLC changes over hundreds of historical dates;
- identical dates, rows, volumes and factors;
- sub-ppm price differences;
- near-unique ratios by date rather than piecewise corporate-action factors.

The bounded mode audit did not reproduce those changes. The two findings are compatible:

1. local auto-adjust and repair computations are deterministic on a fixed response;
2. Yahoo-adjusted source snapshots can still change between longer or separately timed retrieval batches.

The remaining likely layer is upstream historical adjustment response timing, caching or revision—not the Qlib provider builder and not a deterministic local `repair` transformation.

## Accepted learning

- Raw OHLCV and Adj Close can be reproducible within a bounded same-run audit.
- `repair=True` is not supported as the root cause of the observed US87 drift.
- Automatic OHLC adjustment matches a transparent raw-plus-Adj-Close derivation within material tolerance.
- The project can remove dependence on opaque auto-adjust execution by storing raw OHLCV and Adj Close and deriving adjusted OHLC deterministically.
- Exact research replay still requires immutable source/provider snapshots because an upstream response may revise later.

## Rejected learning

- The bounded result does not close Issue #358.
- It does not prove Yahoo historical data is stable across hours, jobs or future dates.
- It does not authorize replacing the canonical US x1.1 provider.
- It does not justify coarse price rounding.
- It does not support a US x1.2 model candidate.

## Engineering direction

The next data-contract implementation should:

1. store raw OHLCV and Adj Close as separate immutable source evidence;
2. derive adjusted OHLC through an explicit, versioned formula;
3. record the adjustment ratio and arithmetic implementation identity;
4. use append-only refresh by default for frozen research history;
5. require an explicit evidence revision when historical raw or Adj Close values change;
6. retain the complete source and Qlib provider snapshot with every accepted experiment;
7. compare any refreshed history against the prior frozen snapshot before model execution.

## Current gate

Issue #358 remains open with the governed status:

**`unexplained_provider_drift_blocking`**, narrowed to upstream adjustment-snapshot timing or revision.

The next implementation should establish the raw-plus-adjustment source contract and prove that rebuilding twice from the same frozen raw snapshot produces an identical provider identity and identical US x1.1 scores.
