# QQQI / QQQ / partial-TQQQ VIX v2 Experiment

## Status

This is a frozen, research-only challenger to the price-only rotation study. It
does not authorize trading and it does not treat spot VIX as a tradable asset.

Completed live-data result:
`docs/research/qqqi_qqq_tqqq_vix_v2_result_2026-07-31.md`.

## Why introduce VIX

The Cboe VIX Index is a forward-looking measure of the S&P 500 market's expected
30-day volatility implied by SPX options. It is non-directional: a high VIX means
that expected volatility is elevated, not that equity prices must fall. The
index itself cannot be held directly.

Primary references:

- [Cboe VIX FAQ](https://www.cboe.com/tradable_products/vix/faqs)
- [Cboe volatility trading overview](https://www.cboe.com/tradable-products/volatility-trading)
- Bekaert and Hoerova, *The VIX, the Variance Premium and Stock Market Volatility*
- Lochstoer and Muir, *Volatility Expectations and Returns*

The design implication is strict: VIX should regulate **risk budget and recovery
confirmation**, not create a standalone directional buy signal.

## Frozen hypothesis

The price-only v1 mixed two ideas that rarely overlapped: the market had to be
in a deep current drawdown and already show a confirmed recovery. V2 separates
those concepts and assigns VIX a different role.

1. **Shock memory**
   - QQQ experienced a drawdown of at least 10% within a fixed 63-session memory.
2. **Early repair: QQQI to QQQ**
   - QQQ shows a 5-day breakout or is above a rising MA20; and
   - VIX is easing through three consecutive declines or a 15% retreat from its
     recent peak.
3. **Medium repair: QQQ to partial TQQQ**
   - QQQ is above MA50;
   - a 20-day breakout or rising MA20 provides secondary confirmation; and
   - VIX has normalized below a rolling threshold or retreated at least 25% from
     its recent peak, while no stress flag remains.
4. **Leveraged risk budget**
   - the leveraged state is 50% QQQ and 50% TQQQ, not 100% TQQQ.
5. **Fast degradation**
   - VIX stress or a confirmed MA20 break removes TQQQ exposure;
   - a buffered MA200 break, or VIX stress combined with price failure, moves the
     portfolio to QQQI.

## Dynamic VIX states

Fixed absolute levels such as 20 or 30 are easy to understand but change meaning
across volatility regimes. This contract therefore combines dynamic and shock
features:

- stress: above the trailing 252-session 80th percentile, a one-day rise of at
  least 20%, or a five-day rise of at least 35%;
- easing: three consecutive declines or a retreat of at least 15% from the
  trailing 20-session peak;
- normalized: below the trailing 252-session 60th percentile or at least 25%
  below the recent peak, below the VIX MA20, and not in stress.

These values are frozen before observing v2 returns. They are not promoted as
optimal thresholds.

## Matched VIX attribution

Comparing VIX v2 only with the old v1 would be misleading because v2 also changes
the price-repair logic and introduces partial TQQQ. The runner therefore includes
`rotation_price_repair_v2`, which uses:

- the same shock memory;
- the same early and medium price-repair gates;
- the same 50% QQQ / 50% TQQQ leveraged state;
- the same execution timing and transaction-cost model;
- no VIX conditions.

The incremental contribution of VIX is measured only against this matched
ablation. Improvements versus old v1 or QQQ describe the complete strategy, not
VIX alone.

## Execution and cost contract

- QQQ and VIX signals are calculated at close `t`.
- State changes execute at the next open `t+1`.
- Returns use adjusted open-to-open prices.
- Portfolio turnover is the sum of absolute weight changes.
- Cost is 10 basis points per turnover unit.
- A full QQQI-to-QQQ switch therefore costs 20 basis points; a QQQ-to-50/50
  QQQ/TQQQ rebalance costs 10 basis points.

## Evidence outputs

The evidence runner writes:

- common-window strategy metrics;
- matched price-repair ablation metrics;
- chronological early/late sample comparison;
- daily portfolio weights, states and costs;
- VIX calm, normal and stress regime comparisons for QQQI and QQQ;
- event studies for VIX stress onset, easing and normalization;
- VIX gate and state-reachability audit;
- evidence manifest and file hashes.

Run:

```bash
uv run python scripts/run_qqqi_qqq_tqqq_vix_v2.py
```

Notebook:

```bash
uv run jupyter lab notebooks/13_qqqi_qqq_tqqq_vix_v2.ipynb
```

## Acceptance discipline

The VIX extension is not accepted merely because it increases CAGR. It must be
judged against QQQ, price-only v1 and the matched price-repair v2 on:

- maximum drawdown and tail behavior during VIX stress;
- Sharpe and Calmar, not total return alone;
- whether the partial-TQQQ state is actually reached;
- turnover and false-start frequency;
- whether VIX easing and normalization events show economically coherent timing.

The true QQQI common sample still begins in 2024. A positive result therefore
remains provisional until it survives additional regimes or a separate
pre-registered proxy study that is clearly labelled as such.
