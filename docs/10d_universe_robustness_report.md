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

## Nasdaq-100 window-start PIT universe evidence

The [NDX window-start
runner](../scripts/run_candidate_v2_ndx_window_start_evidence.py) evaluates the
frozen candidate_v2 against four half-year OOS windows where **each window
freezes the official Nasdaq-100 membership known at that window start** from
the committed snapshot under
`configs/research_universes/ndx_window_start_membership.json`.  The snapshots
use the official Nasdaq endpoint
(`https://indexes.nasdaqomx.com/Index/WeightingData?id=NDX&...`) used by
Microsoft Qlib for index constituent data.  Required snapshot dates are exactly
the ten half-year starts from 2021-01-04 through 2025-07-01.

### Method

- **Membership**: Committed NDX window-start snapshot per OOS test window,
  intersected with the actually-covered US provider symbol set.  Each window
  freezes the official NDX membership known at its start date.
- **Training**: The frozen candidate_v2 ranker is retrained on expanding
  history. Each training row uses the latest committed semiannual NDX snapshot
  on or before that row's date; the future OOS-window snapshot is never applied
  backwards to the whole training history. The existing 10D embargo is applied.
- **Evaluation**: Identical to the static-cohort experiment: Top-3 equal-weight
  portfolio, 20 bps cash-inclusive one-way turnover, 50% gross exposure when
  QQQ 20D trend is negative, raw test-period 10D returns.
- **Bias**: `oos_membership_point_in_time=true`,
  `training_membership_asof_semiannual=true`,
  `training_uses_future_oos_snapshot=false`,
  `full_daily_point_in_time=false`,
  and provider coverage remains incomplete.
- **Reuse**: All model/blend/portfolio functions and constants are reused from
  `scripts/run_candidate_v2_universe_robustness.py` — no duplication.

### OOS result

The evidence is written under
`artifacts/evidence/candidate_v2_ndx_window_start/`.

| Metric | Static-100 cohort | NDX PIT window-start | Delta |
|---|---|---|---|
| Compounded relative excess vs QQQ | 176.68% | -19.90% | -196.58 pp |
| Mean Sharpe | 1.51 | .627 | -.883 |
| Worst drawdown | -22.39% | -21.01% | +1.38 pp |
| Mean ICIR | .223 | .190 | -.033 |
| Mean Rank ICIR | .155 | .155 | +.0005 |
| Positive excess windows | 4/4 | 1/4 | -3 windows |

The four individual windows were:

| Window | Aligned train start | Train symbols | Test/official | Relative excess | Sharpe | Max drawdown | ICIR | Rank ICIR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2024H1 | 2021-04-05 | 81 | 86/101 | -19.51% | .186 | -5.07% | .032 | .031 |
| 2024H2 | 2021-04-05 | 85 | 88/102 | -2.23% | .632 | -6.26% | .174 | .022 |
| 2025H1 | 2021-04-05 | 86 | 92/101 | 18.99% | 1.674 | -16.53% | .255 | .117 |
| 2025H2 | 2021-04-05 | 90 | 93/101 | -14.46% | .018 | -21.01% | .299 | .452 |

As a methodology ablation, replacing the future-OOS-snapshot training set with
semiannual as-of membership improved compounded relative excess from -56.34%
to -19.90%, mean ICIR from .125 to .190, and worst drawdown from -31.95% to
-21.01%. Removing that look-ahead-like universe selection debt materially
improves the evidence, but it does not make the strategy economically robust.

The comparison is informational only.  The static-100 cohort uses current Qlib
instrument listings (survivorship-biased, approximately 100 tickers from the
US provider), while the NDX cohort uses committed Nasdaq-100 membership at
each window start (~100 tickers per date from the official index).  Differences
reflect both membership composition and point-in-time methodology.

The static-100 uplift therefore does **not** replicate under official
window-start membership. The as-of runner now uses the same 2021-04-05 aligned
training start across all windows, so the remaining gap is not explained by a
single late IPO truncating history. Universe composition and provider omissions
remain confounders. The evidence rejects the claim that the existing static-100
result is robust trade guidance.

### Frozen gate result

The existing frozen gate is applied without lowering:
- Exactly 4 OOS windows required
- >= 3 positive relative-excess windows
- Compounded relative excess > 30%
- Worst drawdown >= -15%
- Mean ICIR, Rank ICIR, and top-bottom spread positive

A model-gate pass with **incomplete coverage** (any official NDX symbol
missing from the provider) is labelled `promising-but-incomplete` and is never
promoted.  `promotion_eligible=false`, `trade_ready=false`.

The actual run fails three frozen gates:

- positive relative-excess windows: 1/4, below the required 3/4;
- compounded relative excess: -19.90%, below the required +30%;
- worst drawdown: -21.01%, worse than the -15% floor.

Mean ICIR, mean Rank ICIR, and mean top-bottom spread remain slightly positive,
but they do not compensate for negative economic performance.  Decision:
`ndx_window_start_gate_failed`; no promotion and no trade-ready claim.

### Limitations

1. **Semiannual, not daily, membership**: Training uses the latest half-year
   snapshot on or before each row. This removes use of the future OOS snapshot,
   but intra-half membership changes and delistings are not represented.
2. **Provider coverage**: The US market-specific provider may not cover all
   NDX constituents at every snapshot date. Coverage rises from 68/102 in 2021
   to 93/101 in 2025; missing symbols are dropped and create a selection channel.
3. **OOS membership is window-start frozen**: The test membership does not
   change within each half-year. Daily PIT would require daily Nasdaq records.
4. **Single-index focus**: NDX is one large-cap universe.  Results on
   mid/small-cap or non-Nasdaq universes are not tested here.
5. **No hyperparameter tuning**: The frozen ranker calibration, blend weight,
   Top-K, and gate thresholds are carried over unchanged from the original
   candidate_v2 experiment.  No model or portfolio parameter was searched.

The provider-backfill step described above has now been completed. The section
below is the authoritative current evidence and supersedes the limited-provider
metrics in this subsection.

### Provider-backfilled result (authoritative current evidence)

An isolated provider was built with
`scripts/build_ndx_window_start_provider.py`. It copied and hash-verified the
132 source CSVs behind the operational provider, then recovered 34 of the 43
missing NDX identities:

- 33 symbols were downloaded directly with adjusted daily Yahoo data;
- historical `FB` was sourced only from the same-company `META` series and
  capped at 2022-06-30, before the committed snapshots switch to `META`;
- the current Yahoo `FB` instrument was never downloaded because that ticker
  has been recycled for an unrelated ETF;
- nine acquired or delisted identities remained unavailable and failed closed:
  `ALXN`, `ANSS`, `ATVI`, `CERN`, `MXIM`, `SGEN`, `SPLK`, `WBA`, and `XLNX`.

The operational provider was not mutated. The isolated provider identity is
`9e4705965df9ee428947ed4bb917d2bdc9ffdba9add82fbea0728ae5aadeaeea`.
Its complete source/alias/unavailable lineage is copied into the evidence as
`provider_backfill_lineage.json` and bound to that provider identity.

Training coverage also now follows the actual semiannual membership interval
for each symbol. A constituent that leaves NDX before `train_end` needs data
only through its last active snapshot interval. It is no longer dropped for
lacking future bars, and future bars cannot make an incomplete historical
interval pass.

OOS coverage rose to 98/101, 100/102, 100/101, and 100/101 symbols. Training
coverage rose from 81-90 names to 114-127 names. The unchanged frozen model
then produced:

| Metric | Static-100 cohort | Initial NDX provider | Backfilled NDX provider |
|---|---:|---:|---:|
| Portfolio total return | 372.61% | 36.82% | -9.76% |
| QQQ total return | 70.81% | 70.81% | 70.81% |
| Compounded relative excess | 176.68% | -19.90% | -47.17% |
| Mean Sharpe | 1.51 | .627 | -.291 |
| Worst drawdown | -22.39% | -21.01% | -23.67% |
| Mean ICIR | .223 | .190 | .103 |
| Mean Rank ICIR | .155 | .155 | .126 |
| Positive excess windows | 4/4 | 1/4 | 0/4 |

The final per-window evidence is:

| Window | Train symbols | Test/official | Relative excess | Sharpe | Max drawdown | ICIR | Rank ICIR |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024H1 | 114 | 98/101 | -34.70% | -2.33 | -21.10% | -.094 | -.025 |
| 2024H2 | 120 | 100/102 | -3.06% | .56 | -12.91% | .070 | -.008 |
| 2025H1 | 123 | 100/101 | -10.10% | .10 | -23.67% | .106 | .081 |
| 2025H2 | 127 | 100/101 | -7.17% | .50 | -18.04% | .328 | .456 |

All economic gates fail except the three average score diagnostics, which stay
slightly positive. Positive ICIR does not translate into Top-3 excess return:
the broader cross-section changes both fitted ranks and selected names, and all
four cost-aware OOS portfolios underperform QQQ.

This is stronger evidence than the survivor-heavy static cohorts. It rejects
the claim that candidate_v2 currently has reliable trade-guidance ability.
`promotion_eligible=false` and `trade_ready=false` remain mandatory.

Reproduction:

```bash
uv run python scripts/build_ndx_window_start_provider.py \
  --base-data-root D:/Documents/GitHub/alpha_engine \
  --output-data-root D:/Documents/GitHub/alpha_engine_ndx_backfill_data \
  --start 2021-04-05 \
  --end 2026-06-24

uv run python scripts/run_candidate_v2_ndx_window_start_evidence.py \
  --data-root D:/Documents/GitHub/alpha_engine_ndx_backfill_data \
  --provider-lineage-path \
    D:/Documents/GitHub/alpha_engine_ndx_backfill_data/data/provider_backfill_lineage.json \
  --first-test-year 2024 \
  --last-test-year 2025
```

The next model-quality step is cross-sectional factor and label diagnosis on
this broader point-in-time-like universe. It is not another search over blend
weights, LightGBM leaves, Top-K, or risk overlays. A higher-grade delisted-price
source can close the remaining 1-3 OOS names, but the current economic failure
is already too large to support promotion.
