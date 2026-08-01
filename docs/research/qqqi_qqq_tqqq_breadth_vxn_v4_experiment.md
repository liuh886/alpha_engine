# QQQI / QQQ / TQQQ breadth and VXN v4 experiment

## Research question

Can information that is not already contained in QQQ price repair and broad-market VIX improve the 75% TQQQ recovery switch?

This contract tests two additions separately:

1. **Nasdaq-100 market breadth** using the adjusted-close ratio `QQQE / QQQ`;
2. **Nasdaq-specific implied volatility** using Cboe VXN (`^VXN`).

The experiment is research-only and does not authorize live trading.

## Why QQQE / QQQ

QQQE tracks an equal-weighted Nasdaq-100 portfolio. Relative strength against cap-weighted QQQ tests whether recovery is broadening beyond the largest constituents. It also avoids a misleading historical reconstruction based on today's Nasdaq-100 membership.

The frozen confirmation rule is intentionally simple:

- `QQQE / QQQ` is above its 20-session moving average; and
- its five-session change is positive.

Breadth gates only the transition from QQQ to the 75% TQQQ state. It does not alter the initial QQQ repair entry or the existing VIX/MA20 exits.

## Why VXN

VIX is derived from S&P 500 option prices, while VXN reflects Nasdaq-100 expected volatility. VXN is not assumed to be better. The experiment tests:

- **VXN replacement:** apply the same rolling quantile, spike, easing and normalization definitions to VXN instead of VIX;
- **VIX + VXN confirmation:** require both indices to ease/normalize, while either can force risk reduction.

No VXN-specific threshold is selected from the observed sample.

## Frozen baseline

The baseline is `qqqi_qqq_tqqq_vix_v3_aggressive`:

- QQQ close signal at session `t`;
- execution at next session open `t+1`;
- adjusted open-to-open returns;
- 75% TQQQ / 25% QQQ in the partial-leverage state;
- 10 bps per turnover unit;
- VIX v2 price and volatility rules unchanged.

## Compared strategies

| Key | Description |
|---|---|
| `buy_hold_QQQ` | QQQ buy and hold |
| `rotation_vix_v3_75` | frozen VIX v3 baseline |
| `rotation_breadth_v4_75` | baseline plus QQQE/QQQ breadth gate |
| `rotation_vxn_only_v4_75` | VXN replaces VIX |
| `rotation_vix_vxn_confirm_v4_75` | VIX and VXN dual confirmation |

Breadth and VXN are not combined in the first validation round. A joint strategy would be a separate contract after each factor's independent contribution is understood.

## Required evidence

The runner exports:

- common data coverage;
- strategy metrics and chronological splits;
- complete daily and trade traces;
- breadth and VXN feature frame;
- VIX/VXN overlap diagnostics;
- state reachability and leveraged-state contribution;
- every baseline leverage entry blocked by each challenger and subsequent 5/10/20/40-session outcomes;
- contract and output hashes;
- a persistent `StrategyExperimentJournal` run record.

## Decision discipline

A factor is useful only if it improves the recovery switch for an economically clear reason.

- Breadth should reduce narrow, mega-cap-led false starts without removing most successful recovery participation.
- VXN should show incremental Nasdaq-specific risk information rather than merely duplicating VIX.
- Higher CAGR alone is insufficient; drawdown, Calmar, turnover, blocked entries and lost recovery participation must be reviewed.
- Thresholds and lookbacks may not be tuned in place after results are observed.
- The common QQQI history starts in 2024, so no variant can be marked trade-ready from this evidence.
