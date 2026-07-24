# Candidate v2 10D Universe Robustness

## Decision

The frozen `candidate_v2` does **not** remain robust when the tradable universe
expands from 10 to 50 and 100 US symbols.

- `research_only=true`
- `promotion_eligible=false`
- `trade_ready=false`
- decision: `candidate_v2_not_robust_across_expanded_universes`

This report also supersedes the first 10/50/100 result. That run used the mixed
CN+US `data/watchlist` provider. Its union calendar could make a US
`Ref($close, -10)` label land on a CN-only session; the old portfolio evaluator
then treated a missing selected return as zero. The corrected runner:

- verifies and uses only `data/providers/us`;
- binds the evidence to provider identity
  `66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8`;
- computes the canonical expression on consecutive US market sessions; and
- fails closed when a selected holding or QQQ benchmark has no finite raw return.

For example, the mixed calendar advanced from 2025-04-04 to the US holiday
2025-04-18 in ten union sessions, producing a missing META return. The US-only
calendar advances to 2025-04-21 and produces a finite raw 10D return.

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

| Cohort | Windows | Portfolio return | QQQ return | Relative excess vs QQQ | Mean Sharpe | Worst drawdown | Pearson ICIR | Rank ICIR | Mean 20% spread | Exact Top-3 minus Bottom-3 | Positive excess windows | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10 symbols | 4 | 126.77% | 70.81% | 32.76% | 2.10 | -16.15% | 0.321 | 0.269 | 1.69% | 0.70% | 4 / 4 | fail |
| 50 symbols | 4 | 492.46% | 70.81% | 246.85% | 1.93 | -24.71% | 0.255 | 0.124 | 1.38% | 4.59% | 4 / 4 | fail |
| 100 symbols | 4 | 372.61% | 70.81% | 176.68% | 1.51 | -22.39% | 0.223 | 0.155 | 0.94% | 4.10% | 4 / 4 | fail |

Returns compound 52 non-overlapping 10-session rebalance periods across the
four OOS windows. Relative excess is multiplicative, not the arithmetic
difference between the first two return columns.

The 20% spread is the broad daily cross-sectional diagnostic. The exact
Top-3/Bottom-3 diagnostic uses the same rebalance dates and canonical raw 10D
returns as the portfolio. Its positive-spread ratios are 55.8%, 67.3%, and
59.6% for the 10/50/100 cohorts. The Bottom-3 leg is diagnostic only; it is not
an executable short portfolio. The portfolio result is the cost-aware Top-3
long test with the frozen benchmark-trend exposure rule.

The frozen gate requires every cohort to have:

- exactly four complete OOS windows;
- at least three positive-excess windows;
- more than 30% compounded relative excess;
- worst drawdown no worse than -15%;
- positive Pearson ICIR, Rank ICIR, and Top-Bottom spread.

All three cohorts pass the return, window-consistency, ICIR, Rank ICIR, and
spread conditions. All three fail the drawdown gate.

## Interpretation

The frozen blend has genuine research-level cross-sectional information in this
sample: every cohort has positive Pearson ICIR, Rank ICIR, broad spread, exact
Top-3/Bottom-3 spread, and positive relative excess in all four windows. The
50-symbol cohort is the strongest return result, not the strongest risk result.

It does not yet have reliable trade-guidance ability. Performance is sensitive
to universe composition, every cohort breaches the drawdown gate, and the
current-member universe can overstate historical efficacy. Positive
contributions are also concentrated: the top three names explain about 76.8%,
59.4%, and 53.6% of positive gross contribution in the 10/50/100 cohorts. In
the 50-symbol cohort those leaders are POET, AEHR, and BE. The 2024H2 50-symbol
window alone returns 117.0%, while its 2025H2 window falls to 24.4% total return
and reaches a -24.7% drawdown. This is a strong research candidate with a
tail-risk and concentration problem, not a trade-ready model.

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

The next model-quality step is point-in-time universe validation plus fixed
concentration and adverse-regime diagnostics. It is not another blend-weight or
LightGBM parameter search. Risk controls can limit exposure, but they cannot
turn a survivorship-biased, drawdown-breaching result into trade guidance.

## Portfolio-risk overlay

The [candidate_v2 risk-hypotheses
evaluator](../scripts/run_candidate_v2_risk_hypotheses.py) reconstructs the
evidence from the committed per-window JSON files and evaluates four fixed
portfolio-construction variants without re-training, re-scoring, or tuning:

| Variant | Description |
|---|---|
| `frozen_baseline` | Top-3 equal weight with 50% gross exposure when QQQ 20D trend < 0 |
| `top3_max20pct_per_name` | Each name capped at 20% of gross exposure before trend scaling |
| `top3_positive_20d_return_only` | Baseline weight only when selected stock backward 20D return > 0 |
| `top3_inverse_vol20_normalized` | Weight ∝ 1/vol20, normalised to baseline gross exposure |

All four use the **same Top-3 selection** from the frozen score and the
canonical raw 10D returns already recorded in evidence. Only the weighting
scheme changes.

The frozen gate (4 windows, ≥3 positive excess, >30% compounded relative
excess, ≥-15% worst drawdown, all three cohorts pass) is applied per variant.
Output is under `artifacts/evidence/candidate_v2_risk_hypotheses/`.

Reproduction:

```bash
uv run python scripts/run_candidate_v2_risk_hypotheses.py \
  --data-root D:/Documents/GitHub/alpha_engine
```

### Decision

The real-data run used the verified US-only provider
`66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8`.
Every row below contains four half-year OOS windows and reports compounded
multiplicative relative excess, worst window drawdown, positive relative-excess
windows, and the frozen gate result.

| Variant | Cohort | Relative excess | Worst drawdown | Positive windows | Gate |
|---|---:|---:|---:|---:|---:|
| frozen baseline | 10 | 32.76% | -16.15% | 4/4 | fail |
| frozen baseline | 50 | 246.85% | -24.71% | 4/4 | fail |
| frozen baseline | 100 | 176.68% | -22.39% | 4/4 | fail |
| 20% per-name cap | 10 | -2.85% | -9.79% | 2/4 | fail |
| 20% per-name cap | 50 | 81.19% | -15.33% | 4/4 | fail |
| 20% per-name cap | 100 | 60.49% | -13.51% | 3/4 | pass |
| positive 20D stock trend | 10 | -25.72% | -8.52% | 1/4 | fail |
| positive 20D stock trend | 50 | -18.38% | -14.09% | 2/4 | fail |
| positive 20D stock trend | 100 | -52.04% | -26.77% | 1/4 | fail |
| inverse 20D volatility | 10 | 25.39% | -15.18% | 4/4 | fail |
| inverse 20D volatility | 50 | 208.58% | -14.85% | 3/4 | pass |
| inverse 20D volatility | 100 | 208.69% | -20.08% | 4/4 | fail |

No overlay passes all three cohorts. The 20% cap controls drawdown in the
100-symbol cohort but destroys the 10-symbol excess; inverse volatility fixes
the 50-symbol drawdown but misses both the 10-symbol return/drawdown gates and
the 100-symbol drawdown gate. The positive-stock-trend filter is decisively
refuted and is directionally inconsistent with the frozen blend's inverted
momentum component.

The underlying selection-tail risk cannot be repaired by further portfolio
weight tuning while retaining the same Top-3 selection and static-current-
member cohorts. The next evidence step remains point-in-time universe
validation, not another overlay or LightGBM parameter search.

- `research_only=true`
- `promotion_eligible=false`
- `trade_ready=false`
- decision: `candidate_v2_no_robust_overlay`
