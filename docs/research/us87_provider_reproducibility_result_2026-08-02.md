# US87 provider reproducibility audit — 2026-08-02

## Preliminary decision

**`unexplained_provider_drift_blocking`**, narrowed to adjusted-price floating recomputation.

Two complete US87 full refreshes were built sequentially under identical code, environment, date boundaries and Yahoo adapter settings. Both were promotion-eligible, but their provider identities differed.

- workflow: `30741031977`;
- artifact: `8831306221`;
- artifact digest: `sha256:ffaf90e12703a917553970bf0f1d9876afeac7e5143b822b487cec13079eaa64`;
- refresh A provider: `cfd029a153a747d4d630f7111e267887080acaec1f4234559100882d28e9a719`;
- refresh B provider: `a1c4b2188dddf87d5b5bc79c123277433a890cc27853205b0eb339063d9c4ba8`.

The artifact retains both complete source CSV directories and both Qlib provider snapshots.

## Result

| Classification | Symbols |
|---|---:|
| Identical | 41 |
| Historical adjusted-price revision candidate | 47 |
| Serialization-only | 0 |
| Floating-point-only at 1e-8 tolerance | 0 |
| Latest-row-only | 0 |
| Row/calendar revision | 0 |
| Unexplained non-proportional numeric revision | 0 |

All 88 symbols retained identical date rows and ordering. The only changed fields were:

- open;
- high;
- low;
- close;
- synthetic amount derived from close × volume.

Volume and factor were exactly identical for all 88 symbols.

## Magnitude and date distribution

Across the 47 changed symbols:

- changed dates per symbol: 241–927, median 837;
- first changed date ranged from 2021-01-04 to 2022-12-16;
- last changed date ranged from 2023-05-08 to 2026-04-30;
- maximum relative OHLC difference per symbol: `2.19×10⁻⁷` to `7.69×10⁻⁷`, median `5.12×10⁻⁷`;
- maximum absolute OHLC difference per symbol: about `0.00000195` to `0.00036909`.

The differences are numerically tiny but affect hundreds of historical observations per symbol.

## Structural pattern

Every changed symbol had the same structure:

1. volume was unchanged on every changed row;
2. open, high, low and close moved by the same proportional factor within each date;
3. the within-date OHLC ratio spread was at machine precision, generally below `9×10⁻¹⁶`;
4. synthetic amount moved only because close changed;
5. date rows and lifecycle intervals did not change.

This proves the drift originates upstream in adjusted OHLC values, not in the provider builder, calendar, instrument set, volume, row ordering or CSV serialization.

## Why this is not yet classified as a legitimate corporate-action revision

A normal corporate-action adjustment update should usually produce piecewise-constant ratio changes over historical segments. Instead:

- the median changed symbol had 837 changed dates and about 820 distinct close ratios rounded to 12 decimals;
- ratios oscillated around 1 at approximately sub-parts-per-million scale;
- examples such as AAPL, ASML, QQQ and NVDA had hundreds of near-unique daily ratios.

That pattern is more consistent with repeated floating recomputation of adjusted prices than with a newly published split or dividend factor.

The current production adapter uses:

- `auto_adjust=True`;
- `repair=True`.

A controlled mode experiment is still required before attributing the behavior specifically to Yahoo adjustment or yfinance repair logic.

## Quantization check

Simple decimal rounding is not an acceptable fix.

- rounding to 8, 7, 6, 5 or 4 decimal places left all 47 symbols different;
- rounding to 3 decimal places still left 45 symbols different;
- rounding to 2 decimal places left 40 symbols different and introduced maximum 10-session return error of roughly 0.73%;
- reducing to four significant digits improved byte agreement but introduced return error around 0.11% and still did not fully stabilize the sources.

Therefore the project must not hide drift through coarse source-price rounding.

## Consequence for US x1.1

The native-grid experiment proved that tiny source revisions can materially alter XGBoost tree paths and aggregate backtest results even when economic price differences are sub-ppm.

This means two separate contracts are required:

1. immutable raw/provider snapshot identity for exact experiment replay;
2. deterministic model-input contract for deciding whether economically negligible source noise should affect ranks, labels and tree splits.

Until both contracts are explicit, no US x1.2 candidate may be promoted.

## Accepted learning

- Provider build mechanics are deterministic given fixed source CSVs.
- Same-day Yahoo-adjusted source retrieval is not byte- or value-reproducible for 47/88 symbols.
- The changes are proportional OHLC recomputations with unchanged volume and rows.
- The pattern is not explained by serialization, calendar changes or latest-row updates.
- Coarse price rounding is not an acceptable stabilization method.
- Full source and provider snapshots must accompany accepted model evidence.

## Next controlled experiment

For a bounded high-impact subset including AAPL, ASML, AVGO, GOOGL, META, MSFT, NVDA, QQQ, TSM and VRT, repeat two downloads under:

1. `auto_adjust=True`, `repair=True`;
2. `auto_adjust=True`, `repair=False`;
3. `auto_adjust=False`, `repair=False`, retaining adjusted close and corporate-action evidence.

The experiment must determine whether:

- raw OHLC is reproducible while adjusted OHLC is not;
- `repair=True` introduces or amplifies the variation;
- adjustment factors can be stored separately and applied deterministically;
- model features and labels require tolerance-aware quantization after economic transformations rather than source-price rounding.

## Governance outcome

Issue #358 remains blocking. The current decision is not yet upgraded to `legitimate_historical_revision_explained` or `pipeline_nondeterminism_fixed`.
