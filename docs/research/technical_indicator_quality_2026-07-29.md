# Technical Indicator Quality Decision (2026-07-29)

## Decision

No Bollinger, MACD, or RSI candidate is approved for the active factor
libraries. No current AlphaEngine model is trade-ready.

The strongest local clue is the fixed 10-session RSI-strength factor in CN:
mean ICIR `0.0986`, mean Rank IC `0.0133`, worst drawdown `-12.20%`, and
`+10.52%` compounded relative excess versus CSI300. It nevertheless beats the
benchmark in only `2/4` windows, has `ready_ratio=0`, uses a static
survivorship-biased CN universe, and fails completely in US. The result is a
market-specific research clue, not a trading signal.

The durable evidence is under
`artifacts/evidence/technical_indicator_factor_quality/`.

## Frozen experiment contract

- Four complete OOS windows: 2024H1, 2024H2, 2025H1, and 2025H2.
- US: repaired provider, window-start NDX membership, Top-3, QQQ benchmark.
- CN: manifest-pinned curated static universe, Top-15, CSI300 benchmark, with
  survivorship bias declared.
- Economic returns: raw `Ref($close, -10) / $close - 1`.
- Candidate inputs: historical close only.
- Candidate parameters and economic orientations were declared before the
  run. Inverted rows are diagnostics, not an orientation search.
- No grid search, fill, clipping, future return, model fit, or blend tuning.
- Every window is `research_only=true`, `promotion_eligible=false`, and
  `trade_ready=false`.

## Cross-market results

The table reports the declared original orientation. Relative excess is
compounded across four windows.

| Candidate | Market | Mean ICIR | Mean Rank IC | Positive spread windows | Worst drawdown | Positive excess windows | Relative excess |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bollinger reversion z20 | US | -0.0446 | -0.0060 | 1/4 | -22.97% | 1/4 | -27.45% |
| Bollinger reversion z20 | CN | -0.0383 | 0.0006 | 1/4 | -13.03% | 1/4 | -23.10% |
| MACD histogram 12/26/9 | US | 0.0163 | -0.0066 | 3/4 | -33.86% | 1/4 | -34.76% |
| MACD histogram 12/26/9 | CN | 0.0402 | 0.0122 | 3/4 | -19.74% | 2/4 | -2.46% |
| RSI strength 10 | US | 0.0421 | 0.0100 | 3/4 | -14.77% | 0/4 | -46.90% |
| RSI strength 10 | CN | 0.0986 | 0.0133 | 3/4 | -12.20% | 2/4 | 10.52% |

The existing broad stability rule labels CN MACD and CN RSI as stable research
rows because their IC and spread signs are consistent. The stricter decision
correctly rejects both: neither is economically reliable across both markets,
and neither has a nonzero ready ratio.

The factor pool also contained a formula-precedence defect in four
`technical_rsi_proxy_*` expressions. The positive-day indicator multiplied
only the price ratio before the subtraction, making negative sessions
approximately `-1`. The definitions now measure positive return magnitude
divided by absolute return magnitude. This correction repairs the candidate
contract; it does not promote RSI into an active market library.

## Top-K and Bottom-K backtest capability

AlphaEngine can verify selection quality through three related paths:

1. `run_10d_experiment(...)` evaluates cost-aware, non-overlapping Top-K
   portfolios against a benchmark and reports raw IC, Rank IC, spread, return,
   drawdown, and promotion gates.
2. `src/research/benchmark_aware_topk.py` evaluates aligned Top-K and Bottom-K
   long-only legs and derives a diagnostic Top-K-minus-Bottom-K net spread.
3. The current evidence records both Top-K economic returns and
   cross-sectional spread stability for every candidate and window.

So the capability exists, but the result is negative: no tested technical
factor produced strong and robust benchmark excess. A positive Top-minus-
Bottom spread alone is insufficient when the investable Top-K leg loses to the
benchmark.

## Data-quality boundary

The runner verifies every CSV against its provider-manifest hash and writes
`source_data_quality.json`.

| Market | Files | Rows | Close duplicates | Nonpositive close | Split-like close jumps | Invalid OHLC | Close-only eligible | High/low eligible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| US | 166 | 212,076 | 0 | 0 | 0 | 0 | yes | yes |
| CN | 212 | 270,694 | 0 | 0 | 0 | 46 | yes | no |

The CN OHLC defects are concentrated on 2024-03-29 and are consistent with a
stored adjusted-close versus OHLC alignment problem. This experiment uses only
close, so it remains eligible. Any future range, ATR, candlestick, or other
high/low factor must fail closed until the source is rebuilt and the report
passes.

The broader data foundation is not trade-grade:

- historic NDX coverage is near-complete, not complete; unavailable
  acquired/delisted names remain;
- CN membership is a static current snapshot and therefore survivorship-biased;
- both providers contain OHLCV/amount only, with no point-in-time fundamentals,
  earnings revisions, sector history, corporate-action reference tables,
  borrow data, or richer liquidity/microstructure fields.

It is sufficient for close-only exploratory evidence, not for an unbiased
claim that a strategy can guide trading.

## LightGBM versus XGBoost

The libraries are related but not interchangeable. Both provide histogram
gradient-boosted trees and learning-to-rank objectives. LightGBM normally grows
leaf-wise; XGBoost defaults to depth-wise growth and can use loss-guided growth.

More importantly, AlphaEngine does not currently have a fair model comparison:
the maintained LightGBM path is a true daily LambdaRank model with daily groups
and processed relevance gains, while the present XGBoost workflow is a legacy
RMSE regressor. There is no comparable rolling `XGBRanker` evidence. Therefore:

- the project has not demonstrated that LightGBM and XGBoost perform the same;
- replacing the model family is not justified by current evidence;
- weak cross-market factor information is the larger bottleneck;
- if tried later, XGBoost must use the same target, groups, windows, embargo,
  raw-return evaluation, and fixed parameters—not another grid search.

References:
[LightGBM features](https://lightgbm.readthedocs.io/en/v4.2.0/Features.html),
[LightGBM parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html),
[XGBoost learning to rank](https://xgboost.readthedocs.io/en/release_3.2.0/tutorials/learning_to_rank.html),
and [XGBoost tree methods](https://xgboost.readthedocs.io/en/release_3.2.0/treemethod.html).

## Backtest efficiency

A synthetic 504-session by 200-symbol Top-5/10D benchmark measured:

| Path | Runtime | Data fetches | Peak memory |
| --- | ---: | ---: | ---: |
| Ordinary cold | 466.7 ms | 51 | 4.33 MiB |
| Vectorized cold | 299.1 ms | 1 | 6.18 MiB |
| Vectorized warm | 302.8 ms | 0 | 5.40 MiB |

The portfolio calculation is already sub-second at this scale. Batch loading
is about `1.56x` faster and removes repeated fetches. By contrast, full-market
Qlib expression scans exceeded 120 seconds locally. The next performance work
should target provider I/O, expression materialization, and repeated
rolling-window feature loads—not rewrite Top-K arithmetic.

## Next approved research step

Stop tuning Bollinger windows, MACD spans, RSI windows, blend weights, or
LightGBM leaves on the observed windows. Improve the information set and data
contract first:

1. repair and re-version CN OHLC before using high/low features;
2. acquire point-in-time universe and corporate-action coverage;
3. add economically distinct, predeclared factor families;
4. challenge any new hypothesis on the same cost-aware OOS economic gates.
