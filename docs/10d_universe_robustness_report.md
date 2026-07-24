# Candidate v2 10D Universe Robustness

## Decision

The frozen `candidate_v2` does **not** remain robust when the tradable universe
expands from 10 to 50 and 100 US symbols.

- `research_only=true`
- `promotion_eligible=false`
- `trade_ready=false`
- decision: `candidate_v2_not_robust_across_expanded_universes`

This replaces the July 7 coverage-only result. The earlier run incorrectly
required data from 2021-01-01 even though the local provider's common US history
starts on 2021-04-05. The current runner aligns each cohort to its real common
start, then requires the same four complete OOS windows.

## Frozen experiment

No model or portfolio parameter was searched.

| Component | Frozen value |
|---|---|
| Score | 50/50 daily LambdaRank score + inverted historical 10D momentum |
| Ranker features | `momentum_volatility_volume` |
| Ranker calibration | gain5, round100, leaves31, leaf10, lr0.05 |
| Portfolio | Top-3 equal weight |
| Risk control | 50% gross when QQQ historical 20D return is negative |
| Returns | raw forward 10D: `Ref($close, -10) / $close - 1` |
| Cost | 20 bps, cash-inclusive one-way turnover |
| Windows | 2024H1, 2024H2, 2025H1, 2025H2 |
| Training | expanding history, model refit per window, 10-session embargo |

The 10/50/100 cohorts are exact, nested, US-only, and exclude QQQ, SPY, and
index symbols. All three retain full coverage from 2021-04-05 through the
evaluation end. Membership comes from the current local provider snapshot, so
the result has survivorship bias and is diagnostic rather than a point-in-time
index backtest.

## OOS result

| Cohort | Windows | Relative excess vs QQQ | Mean Sharpe | Worst drawdown | Pearson ICIR | Rank ICIR | Mean Top-Bottom spread | Positive excess windows | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10 symbols | 4 | 40.61% | 2.09 | -14.27% | 0.245 | 0.217 | 1.10% | 4 / 4 | pass |
| 50 symbols | 4 | 72.32% | 1.33 | -25.48% | 0.198 | 0.131 | 1.01% | 2 / 4 | fail |
| 100 symbols | 4 | 28.24% | 0.96 | -24.95% | 0.204 | 0.162 | 1.04% | 3 / 4 | fail |

The Top-Bottom spread is a daily cross-sectional diagnostic using raw 10D
forward returns; it is not an independently executable long-short strategy
return. The portfolio result is the non-overlapping, cost-aware Top-3 test.

The frozen gate requires every cohort to have:

- exactly four complete OOS windows;
- at least three positive-excess windows;
- more than 30% compounded relative excess;
- worst drawdown no worse than -15%;
- positive Pearson ICIR, Rank ICIR, and Top-Bottom spread.

The 50-symbol cohort fails window consistency and drawdown. The 100-symbol
cohort fails relative excess and drawdown. Positive IC diagnostics therefore do
not establish portfolio robustness.

## Interpretation

The model has genuine research-level cross-sectional information: all cohorts
show positive Pearson ICIR, Rank ICIR, and Top-Bottom spread. It can rank stocks
better than chance in this sample, and the canonical 10-symbol Top-3 backtest
has strong benchmark-relative performance.

It does not yet have reliable trade-guidance ability. Performance is sensitive
to universe composition, expanded cohorts breach the drawdown gate, and the
current-member universe can overstate historical efficacy. The evidence rejects
further claims that `candidate_v2` is broadly stable or trade-ready.

## Reproduction

```bash
uv run python scripts/run_candidate_v2_universe_robustness.py \
  --data-root D:/Documents/GitHub/alpha_engine \
  --first-test-year 2024 \
  --last-test-year 2026
```

Evidence is stored under:

```text
artifacts/evidence/candidate_v2_universe_robustness/
```

The next model-quality step should diagnose why 2025H1 and expanded-universe
selection degrade before introducing new hyperparameters. Risk controls can
limit exposure, but they cannot repair weak or universe-sensitive alpha.
