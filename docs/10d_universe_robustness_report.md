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
`6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407`.
Its complete source/alias/unavailable lineage is copied into the evidence as
`provider_backfill_lineage.json` and bound to that provider identity.

The first 2026 holdout attempt exposed a mixed adjusted/unadjusted `KLAC`
history around its 10-for-1 split. It created an impossible +943% canonical
10D return and was discarded before interpretation. The provider builder now
scans every seeded CSV for one-session adjusted-close ratios outside
`[1/3, 3]`, refreshes an affected symbol from adjusted Yahoo history, records
both source hashes and the anomaly dates, and fails closed if a refreshed
series remains discontinuous. `KLAC` was the only affected symbol; a full
166-file rescan found no remaining adjustment discontinuity.

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
| Portfolio total return | 372.61% | 36.82% | 3.84% |
| QQQ total return | 70.81% | 70.81% | 70.81% |
| Compounded relative excess | 176.68% | -19.90% | -39.21% |
| Mean Sharpe | 1.51 | .627 | .054 |
| Worst drawdown | -22.39% | -21.01% | -29.64% |
| Mean ICIR | .223 | .190 | .110 |
| Mean Rank ICIR | .155 | .155 | .133 |
| Positive excess windows | 4/4 | 1/4 | 0/4 |

The final per-window evidence is:

| Window | Train symbols | Test/official | Relative excess | Sharpe | Max drawdown | ICIR | Rank ICIR |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024H1 | 114 | 98/101 | -30.50% | -1.36 | -17.73% | -.111 | -.045 |
| 2024H2 | 120 | 100/102 | -3.06% | .56 | -12.91% | .070 | -.008 |
| 2025H1 | 123 | 100/101 | -7.23% | .30 | -29.64% | .124 | .099 |
| 2025H2 | 127 | 100/101 | -2.73% | .71 | -17.26% | .358 | .486 |

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
  --last-test-year 2026
```

### Cross-sectional factor and Top-3 diagnosis

The fixed-hypothesis diagnostic is now complete. It reloads the seven frozen
ranker inputs for the same four OOS windows and 98-100 OOS symbols, freezes
Top-K/Bottom-K from each factor before checking raw-return availability, and
measures both broad daily IC and the exact 13 rebalance dates per window. It
does not train a model, search a parameter, or select a deployable orientation.

The candidate's broad daily Rank ICIR is positive at .133 and its daily
Top-20%-minus-Bottom-20% spread is +.231%. That information does not survive
portfolio concentration:

- exact rebalance Top-3-minus-Bottom-3 spread: +.093%;
- positive Top-3 spread periods: 48.1%;
- selected Top-3 mean realized percentile: .492; and
- compounded relative excess versus QQQ: -39.21%.

The seven frozen inputs show the same instability. The orientation below is
the descriptively better direction on these already-observed OOS windows, so
it is not a deployable choice.

| Frozen input | Descriptive orientation | Mean daily Rank IC | Mean Rank ICIR | Top-3 spread | Positive Top-3 windows | Positive Top-3 periods | All consistency checks |
|---|---|---:|---:|---:|---:|---:|---|
| 5D momentum | inverted | .0164 | .0745 | -.092% | 1/4 | 46.2% | fail |
| 10D momentum | inverted | .0041 | .0108 | .521% | 2/4 | 51.9% | fail |
| 20D momentum | original | .0208 | .1361 | 1.065% | 2/4 | 51.9% | fail |
| 10D volatility | original | .0278 | .1303 | 1.062% | 3/4 | 44.2% | fail |
| 20D volatility | original | .0275 | .1182 | .550% | 2/4 | 50.0% | fail |
| 10D volume momentum | original | .0001 | -.0022 | .195% | 3/4 | 57.7% | fail |
| Volume / 20D mean | inverted | .0045 | .0534 | -1.354% | 1/4 | 40.4% | fail |

No factor passes the predeclared broad-direction, cross-window, broad-tail, and
Top-3 period-consistency checks together. The apparently highest Top-3 spread,
20D momentum, is positive in only two of four windows. The 10D volume factor
is positive in three windows but has effectively zero Rank IC and a negative
broad spread. Neither is a stronger research candidate.

The diagnosis also identifies a structural target/portfolio mismatch:

- the processed target has five gain bins, so a roughly 100-name cross-section
  assigns about 20 names to the highest gain label while the portfolio buys
  only three; and
- the frozen model does not set `lambdarank_truncation_level`, so LightGBM uses
  its default of 30, ten times the portfolio cutoff. LightGBM documents this
  parameter as the number of top results emphasized by LambdaRank and advises
  relating it to the desired NDCG cutoff in its
  [ranking parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html#lambdarank_truncation_level).

This explains how the model can learn a weak broad ordering without learning
the Top-3 tail it is asked to trade. It was a structural hypothesis, not
permission to grid-search gain bins or Top-K on the same evidence.

Reproduction:

```bash
uv run python scripts/run_candidate_v2_ndx_factor_diagnostics.py \
  --data-root D:/Documents/GitHub/alpha_engine_ndx_backfill_data
```

Evidence is under
`artifacts/evidence/candidate_v2_ndx_factor_diagnostics/`.
`promotion_eligible=false` and `trade_ready=false`.

### Predeclared Top-3-aligned holdout

One structural variant was declared before viewing the 2026H1 result:

- binary daily relevance with exactly three positive labels per date;
- LambdaRank `label_gain=[0, 1]`, `eval_at=[3]`, and
  `lambdarank_truncation_level=6`;
- the same features, trees, rounds, 50/50 inverted-momentum blend, Top-3
  portfolio, 20 bps cost, embargo, and benchmark regime control as the frozen
  model.

The isolated provider retained all 101 official NDX members at the 2026-01-02
snapshot. Canonical 10D returns restricted the partial holdout to 109 sessions
from 2026-01-02 through 2026-06-09 and 11 non-overlapping rebalance periods.
This is a single-window falsification test and cannot promote a model.

| Metric | Frozen gain-5 model | Top-3-aligned model | Aligned minus frozen |
|---|---:|---:|---:|
| Portfolio return | -22.87% | -16.66% | +6.21 pp |
| QQQ return | 16.98% | 16.98% | — |
| Relative excess | -34.07% | -28.76% | +5.31 pp |
| Sharpe | -1.24 | -.74 | +.51 |
| Max drawdown | -24.64% | -23.37% | +1.28 pp |
| ICIR | -.134 | -.003 | +.132 |
| Rank ICIR | -.171 | -.080 | +.091 |
| Daily 20% spread | -.854% | -.126% | +.728 pp |
| Exact Top-3 spread | -4.165% | -5.015% | -.849 pp |
| Positive Top-3 periods | 3/11 | 3/11 | unchanged |
| Selected realized percentile | .423 | .456 | +.034 |

The aligned model reduced the loss and improved broad diagnostics, but the
actual selection tail worsened: Top-3 spread became more negative, only 3/11
periods were positive, drawdown remained above the -15% floor, and both
variants materially underperformed QQQ. The predeclared checks therefore
produce `top3_alignment_not_supported_on_holdout`.

This refutes further gain-bin, truncation, or Top-K objective tuning within
this model family. Any next model experiment must change the economic
information set or label hypothesis and receive new independent evidence.
`promotion_eligible=false` and `trade_ready=false`.

Reproduction:

```bash
uv run python scripts/run_candidate_v2_top3_holdout_evidence.py \
  --data-root D:/Documents/GitHub/alpha_engine_ndx_backfill_data \
  --provider-lineage-path \
    D:/Documents/GitHub/alpha_engine_ndx_backfill_data/data/provider_backfill_lineage.json
```

Evidence is under `artifacts/evidence/candidate_v2_top3_holdout/`.

### QQQ-residual trend-quality diagnosis

The first post-ranker hypothesis changes the economic information set rather
than another LightGBM or blend parameter. For every stock and signal date it:

- uses 126 historical daily returns while skipping the most recent 10
  sessions;
- estimates rolling beta to QQQ;
- divides the beta-residual mean return by residual volatility; and
- keeps the predeclared orientation that higher residual trend quality is
  better.

It uses no future return, neutral fill, orientation search, winsorization, or
parameter grid. Portfolio construction remains the frozen Top-3, 20 bps cost,
and 50% exposure when QQQ's prior 20D trend is negative.

The 2024H1--2025H2 windows had already been observed before this hypothesis,
so the run is diagnostic and cannot promote a signal. Compared with the frozen
candidate:

| Complete-window metric | Frozen candidate_v2 | Residual trend quality |
|---|---:|---:|
| Portfolio total return | 3.84% | 19.17% |
| QQQ total return | 70.81% | 70.81% |
| Compounded relative excess | -39.21% | -30.23% |
| Positive excess windows | 0/4 | 1/4 |
| Mean Sharpe | .054 | .333 |
| Worst drawdown | -29.64% | -27.55% |
| Mean ICIR | .110 | .054 |
| Mean Rank ICIR | .133 | .032 |
| Daily 20% spread | .231% | .397% |
| Exact Top-3 spread | .093% | 1.202% |
| Positive Top-3 periods | 48.1% | 55.8% |

The 2026H1 partial stress result was much stronger: +17.58% relative excess,
-18.92% drawdown, +7.37% exact Top-3 spread, and positive spread in 8/11
periods. All partial-stress comparisons beat the frozen model.

That improvement is not cross-window stable. Both 2024 halves and 2025H2
still underperform QQQ, 2025H1 draws down 27.55%, and the average ICIR falls
below the frozen model. Selected beta also changes regime: approximately .23
in 2024H2, 1.23 in 2025H1, and 1.75 in 2026H1. The factor is not a consistent
low-beta or drawdown-control signal.

Decision: `residual_trend_quality_not_supported`. The improved Top-3 tail is
useful evidence that medium-term benchmark-residual information is richer than
the rejected short-horizon ranker inputs, but it is not permission to blend or
tune on these same windows. It may be challenged once on an independent market
or future window with the 126/10 contract unchanged.
`promotion_eligible=false` and `trade_ready=false`.

Reproduction:

```bash
uv run python scripts/run_ndx_residual_trend_evidence.py \
  --data-root D:/Documents/GitHub/alpha_engine_ndx_backfill_data
```

Evidence is under `artifacts/evidence/ndx_residual_trend_quality/`.

#### Independent CN challenge

The unchanged 126/10 residual-trend formula was then challenged on the
canonical CN spec with CSI300 as benchmark. Market-specific portfolio semantics
use Top-15, while the 20 bps cost, 10-session cadence, and negative-benchmark
trend exposure remain fixed. An isolated provider retained 201/223 curated
stocks plus CSI300.

| CN metric (2024H1--2025H2) | Result |
|---|---:|
| Portfolio total return | 25.10% |
| CSI300 total return | 39.13% |
| Compounded relative excess | -10.08% |
| Positive excess windows | 2/4 |
| Mean Sharpe | .998 |
| Worst drawdown | -15.08% |
| Mean ICIR | .056 |
| Mean Rank ICIR | -.006 |
| Daily 20% spread | .038% |
| Exact Top-15 spread | .073% |
| Positive Top-15 periods | 54.0% |

2024H1 and 2025H2 are positive, while 2024H2 and 2025H1 underperform. The
drawdown floor misses by eight basis points and the 55% period-consistency gate
misses by one percentage point, but the more important failures are negative
compounded excess and only two positive windows. These thresholds were not
relaxed after observation.

The CN universe is static current membership as of 2026-07-11 and carries
explicit survivorship bias, so even a pass would have remained research-only.
The observed result instead confirms
`cn_residual_trend_quality_not_supported`. The 126/10 hypothesis is now stopped
across both markets; no lookback, skip, orientation, or Top-K tuning is
approved. `promotion_eligible=false` and `trade_ready=false`.

Evidence is under `artifacts/evidence/cn_residual_trend_quality/`.

A higher-grade delisted-price source can close the remaining 1-3 OOS names,
but the current economic failure is already too large to support promotion.
