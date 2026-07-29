# Why the Static-Universe Alpha Collapsed under PIT NDX Membership

## Decision

The strong result recorded by the fixed LightGBM/XGBoost comparison on the
static curated US universe is not evidence of robust Nasdaq-100 alpha. The same
models, features, calibration, horizon, cost, and benchmark fail after the
universe contract is changed to window-start point-in-time Nasdaq-100
membership.

The most important correction is conceptual: the static experiment and the PIT
experiment do not differ only by a few missing tickers. They define different
cross-sectional learning problems.

- Static result: an as-of-2026 curated list of 126 US equities, automatically
  aligned to common data coverage from 2021-04-05.
- PIT result: the official Nasdaq-100 membership at each OOS half-year start,
  with each training row restricted to the latest semiannual membership known
  on that date.

The authoritative status remains:

- `stable_research_candidate=false`
- `promotion_eligible=false`
- `trade_ready=false`

## Observed result

| Candidate | Universe | Mean ICIR | Positive excess windows | Relative excess vs QQQ | Worst drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | Static curated | 0.3587 | 3/4 | +65.04% | -27.34% |
| LightGBM LambdaRank | Window-start PIT NDX | 0.0966 | 1/4 | -20.49% | -26.11% |
| XGBoost `rank:ndcg` | Static curated | 0.3497 | 4/4 | +70.35% | -25.63% |
| XGBoost `rank:ndcg` | Window-start PIT NDX | 0.1149 | 1/4 | -34.08% | -25.59% |

The benchmark is the same raw QQQ 10D return in both experiments. The collapse
therefore cannot be explained by a benchmark substitution.

## Confirmed structural causes

### 1. The static list is a retrospective curated universe, not a historical NDX universe

`us_curated_equities_v1.yaml` is explicitly an as-of-2026 static list. It mixes
large Nasdaq names with other Nasdaq/NYSE equities and includes later winners or
research-watchlist names that were not members of the Nasdaq-100 in the tested
historical windows.

Examples include small or later-added growth names such as `AEHR`, `POET`,
`BE`, `HIMS`, `IREN`, `CRDO`, `ALAB`, and `PLTR`, alongside current large-cap
constituents. Their presence is not proof that any individual name caused the
full return gap, but it confirms that the static experiment was run on a
retrospectively selected opportunity set rather than the investable NDX set
known at each historical date.

This introduces universe-selection bias before model training begins.

### 2. Static membership leaks future survival and future entry information

The static list applies the same 2026 membership backward to 2021--2025. It
therefore:

- includes companies that became important or entered the relevant opportunity
  set only later;
- excludes companies that were historical constituents but subsequently left,
  were acquired, deteriorated, or became unavailable;
- lets the model learn only from names known in 2026 to have survived the full
  research period.

The PIT contract instead uses the latest membership snapshot available on each
training date. A future OOS constituent cannot be inserted into earlier
training rows merely because it is known to be important later.

### 3. Common-coverage alignment adds another selection filter

The static comparison retained 126 symbols after automatic common-coverage
alignment. Requiring a common history from 2021-04-05 favors securities with
clean, continuous, currently available data and tends to remove delisted,
acquired, renamed, or shorter-history names.

The PIT provider handles historical membership intervals explicitly and reports
missing names instead of replacing them with current constituents or filling
returns with zero. Coverage is near-complete but not perfect: 98/101, 100/102,
100/101, and 100/101 names are retained in the four OOS windows.

### 4. A ranker is trained relative to its daily peer group

The processed target is a same-date cross-sectional rank. Changing the universe
therefore changes more than portfolio eligibility:

- each stock's relevance label can change because its percentile rank is
  computed against a different peer set;
- LightGBM/XGBoost query groups contain different securities;
- feature distributions, gain-bin boundaries, and learned tree splits change;
- the Top-15 portfolio is selected from a different score distribution.

The PIT run is therefore a retraining of the same model contract on the
historically correct information set, not a simple post-processing filter on
#183 predictions.

### 5. The static result supplied return uplift without solving tail risk

Worst drawdown barely changes between static and PIT experiments:

- XGBoost: -25.63% to -25.59%
- LightGBM: -27.34% to -26.11%

What disappears is benchmark-relative return and cross-window consistency. This
pattern is more consistent with a favorable retrospective opportunity set than
with a genuinely robust risk-adjusted ranking mechanism.

## What is not yet proven

The committed evidence establishes that universe validity is the dominant
problem, but it does not yet quantify how much of the return gap comes from:

1. static-only stocks;
2. historical NDX exits absent from the static list;
3. changed training labels and fitted models;
4. changed OOS Top-15 selections;
5. contribution concentration in a small number of securities or windows.

No precise percentage attribution should be claimed until the decomposition
below is run.

## Next approved experiment: static-to-PIT alpha decomposition

The next model-effectiveness task is an explanatory experiment, not another
parameter search.

### Frozen contract

Keep unchanged:

- LightGBM LambdaRank and XGBoost `rank:ndcg`;
- momentum + volatility + volume features;
- five relevance gains, 100 rounds, learning rate 0.05;
- expanding half-year windows and 10-session embargo;
- raw 10D economic returns;
- Top-15 equal weight, Bottom-15 diagnostic, 20 bps cost;
- QQQ as a non-tradable reference benchmark.

### Four-cell training/execution decomposition

For every OOS window, evaluate:

| Cell | Training membership | OOS tradable membership | Purpose |
| --- | --- | --- | --- |
| S/S | Static curated | Static curated | Reproduce #183 |
| S/P | Static curated | PIT NDX | Isolate OOS opportunity-set effect |
| P/S | PIT as-of | Static curated | Isolate training/label effect |
| P/P | PIT as-of | PIT NDX | Reproduce the authoritative PIT result |

The mixed cells are diagnostic counterfactuals only. They are not candidates for
promotion.

### Required attribution outputs

- selection overlap between S/S and P/P by rebalance date;
- rank correlation and score migration on common names;
- label-bin migration on common training rows;
- portfolio contribution from common, static-only, PIT-only, entrant, and exit
  groups;
- per-window decomposition of the relative-return gap;
- concentration of positive and negative contribution by security;
- sensitivity of results to the common intersection universe, with no parameter
  tuning;
- explicit residual term when training and execution effects interact.

### Stop rule

This experiment explains the failed result. It must not be used to choose a
more favorable universe, Top-K, tree calibration, factor orientation, or blend
weight. After the decomposition, the existing OHLCV ranker family is either:

- stopped; or
- challenged only with a genuinely new economic information set and untouched
  evidence.

## References

- `docs/research/lgbm_xgb_ranker_comparison_2026-07-29.md`
- `docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md`
- `configs/research_universes/us_curated_equities_v1.yaml`
- `configs/research_universes/ndx_window_start_membership.json`
- `configs/research_paradigms/us_10d_lgbm_xgb_ranker_comparison.yaml`
- `configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml`
