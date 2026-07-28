# Fixed LightGBM vs XGBRanker 10D Comparison

## Decision

The fixed LightGBM LambdaRank and XGBoost `rank:ndcg` candidates both show
materially stronger cross-sectional signal and QQQ-relative performance than
the historical-momentum baseline. XGBoost has the stronger portfolio result;
LightGBM has slightly stronger IC diagnostics. Neither is a stable research
candidate because its worst OOS drawdown exceeds 25%. The post-identity
promotion decision is `rejected` and `trade_ready=false`.

No parameter search was performed. The next valid challenge is the same frozen
comparison on window-start point-in-time membership, followed by diagnosis of
the 2025H1 drawdown. It is not another tree, gain-bin, feature, or Top-K grid.

## Locked comparison contract

- Market/provider: US manifest-bound provider
  `66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8`
- Universe: 126 retained symbols after automatic common-coverage alignment
- Limitation: static curated membership with explicit survivorship bias
- Aligned training start: 2021-04-05
- OOS windows: 2024H1, 2024H2, 2025H1, 2025H2
- Target: processed daily cross-sectional rank target
- Economic returns: raw `Ref($close, -10) / $close - 1`
- Benchmark: raw QQQ 10D returns on the same evaluation dates
- Holding/rebalance: fixed 10 trading sessions
- Portfolio: Top-15 equal weight, 20 bps cost
- Features: fixed momentum + volatility + volume group
- Calibration: five gains, 100 boosting rounds, learning rate 0.05
- Both models receive identical features, target, daily groups, embargo, and
  OOS evaluation dates

## Four-window results

| Candidate | Mean ICIR | Mean Rank IC | Mean Top-Bottom spread | Positive excess windows | Compounded total | QQQ | Relative excess | Worst drawdown | Ready ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | 0.3587 | 0.0488 | 2.08% | 3/4 | 156.14% | 55.20% | 65.04% | -27.34% | 0.50 |
| XGBoost rank:ndcg | 0.3497 | 0.0406 | 1.86% | 4/4 | 164.37% | 55.20% | 70.35% | -25.63% | 0.50 |
| Historical momentum | 0.0506 | 0.0029 | 0.48% | 2/4 | 68.41% | 55.20% | 8.51% | -23.51% | 0.25 |

Compounded values chain the four non-overlapping half-year OOS reports.
Relative excess is `(1 + strategy) / (1 + benchmark) - 1`, not strategy return
minus a zero benchmark.

## Interpretation

The algorithm-family difference is small in signal quality. LightGBM leads
XGBoost by 0.0090 mean ICIR and 0.0082 mean Rank IC. XGBoost leads in economic
outcome: 5.31 percentage points more compounded relative excess, positive
excess in every window, and a 1.71-point smaller worst drawdown.

The Top-Bottom diagnostic is directionally useful: both true rankers have a
positive spread in all four windows, while the momentum baseline is much
weaker. This supports the original score orientation and falsifies score
inversion. It does not establish deployability.

The blocking result is 2025H1. LightGBM loses 7.07 points relative to QQQ and
draws down 27.34%; XGBoost still beats QQQ by 8.49 points but draws down
25.63%. Both fail the 15% trade-guidance drawdown floor and the 75% ready-ratio
gate. Static future membership also prevents these returns from supporting a
trading claim.

## Pipeline corrections made during the comparison

- XGBoost is evaluated as a true daily query-group `rank:ndcg` model, never as
  a regression score rank transform.
- Candidate evidence uses the distinct `xgb_rank_ndcg` identity.
- The canonical executor now loads complete benchmark returns per OOS window
  and fails closed on missing dates instead of reporting a zero benchmark.
- Walk-forward stability now records compounded strategy, benchmark, relative
  excess, and positive-excess ratio; stable status requires positive
  cross-window benchmark economics.
- Relative output directories resolve once against the repository root, which
  prevents duplicated evidence paths.

## Reproduction

```bash
uv run python scripts/run_us_feature_quality_validation.py \
  --spec configs/research_paradigms/us_10d_lgbm_xgb_ranker_comparison.yaml \
  --output-dir artifacts/evidence/lgbm_xgb_ranker_comparison_economic \
  --provider-uri <manifest-bound-us-provider>
```

The authoritative local output is:

```text
artifacts/evidence/lgbm_xgb_ranker_comparison_economic/
  us_10d_lgbm_xgb_ranker_comparison/
```
