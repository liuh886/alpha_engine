# Technical Indicator Quality Decision (2026-07-29)

## Decision

No Bollinger, MACD, RSI, or close-location candidate is approved for the
active factor libraries. No current AlphaEngine model is trade-ready.

The strongest local clue is the fixed 10-session RSI-strength factor in CN:
mean ICIR `0.0986`, mean Rank IC `0.0136`, worst drawdown `-12.95%`, and
`+9.99%` compounded relative excess versus CSI300. It nevertheless beats the
benchmark in only `2/4` windows, has `ready_ratio=0`, uses a static
survivorship-biased CN universe, and fails completely in US. The result is a
market-specific research clue, not a trading signal.

The authoritative repaired-provider evidence is under
`artifacts/evidence/technical_indicator_factor_quality_repaired_cn/`.

## Frozen experiment contract

- Four complete OOS windows: 2024H1, 2024H2, 2025H1, and 2025H2.
- US: repaired provider, window-start NDX membership, Top-3, QQQ benchmark.
- CN: manifest-pinned curated static universe, Top-15, CSI300 benchmark, with
  survivorship bias declared.
- Economic returns: raw `Ref($close, -10) / $close - 1`.
- Candidate inputs: historical close, plus same-day high/low for the fixed
  close-location-pressure factor.
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
| Bollinger reversion z20 | CN | -0.0392 | -0.0000 | 1/4 | -13.21% | 1/4 | -22.65% |
| MACD histogram 12/26/9 | US | 0.0163 | -0.0066 | 3/4 | -33.86% | 1/4 | -34.76% |
| MACD histogram 12/26/9 | CN | 0.0365 | 0.0121 | 3/4 | -19.87% | 2/4 | 2.45% |
| RSI strength 10 | US | 0.0421 | 0.0100 | 3/4 | -14.77% | 0/4 | -46.90% |
| RSI strength 10 | CN | 0.0986 | 0.0136 | 3/4 | -12.95% | 2/4 | 9.99% |
| Close location pressure 10 | US | -0.0096 | -0.0028 | 2/4 | -14.61% | 2/4 | -17.04% |
| Close location pressure 10 | CN | 0.0200 | 0.0115 | 3/4 | -13.45% | 2/4 | -9.34% |

The existing broad stability rule labels CN MACD and CN RSI as stable research
rows because their IC and spread signs are consistent. The stricter decision
correctly rejects both: neither is economically reliable across both markets,
and neither has a nonzero ready ratio.

The high/low-derived close-location candidate is also rejected. It has
negative mean ICIR in US and negative compounded relative excess in both
markets. The restored high/low data enabled a valid falsification; it did not
create alpha.

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
| CN, original | 212 | 270,694 | 0 | 0 | 0 | 46 | yes | no |
| CN, isolated repair | 212 | 270,617 | 0 | 0 | 0 | 0 | yes | yes |

The original CN defects were concentrated on 2024-03-29. A live probe proved
that Yahoo's raw and auto-adjusted payloads were both internally inconsistent
on those rows; scaling Adj Close alone could not repair them. The isolated
runner copied all 212 manifest-pinned files, replaced only the 46 invalid
histories through EFinance's qfq endpoint, required at least 95% date overlap,
and rebuilt provider identity
`6f556a5952b220b0a92545046ffc1a738227d3b4fb216303a5b0f08762cd50f4`.
All replacements used EFinance, minimum date overlap was `0.991304`, and the
new provider has zero invalid OHLC rows. The original provider remains
untouched.

The broader data foundation is not trade-grade:

- historic NDX coverage is near-complete, not complete; unavailable
  acquired/delisted names remain;
- CN membership is a static current snapshot and therefore survivorship-biased;
- both providers contain OHLCV/amount only, with no point-in-time fundamentals,
  earnings revisions, sector history, corporate-action reference tables,
  borrow data, or richer liquidity/microstructure fields.

It is sufficient for OHLCV exploratory evidence, not for an unbiased claim
that a strategy can guide trading.

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

Stop tuning Bollinger windows, MACD spans, RSI windows, close-location
windows, blend weights, or LightGBM leaves on the observed windows. Improve
the information set and data contract first:

1. acquire point-in-time CN membership and complete delisted US history;
2. add corporate-action reference data and point-in-time non-price features;
3. add only economically distinct, predeclared factor families;
4. challenge any new hypothesis on the same cost-aware OOS economic gates.
