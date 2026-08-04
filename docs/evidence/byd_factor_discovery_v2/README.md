# BYD canonical factor discovery v2 evidence

## Status

- Data input: sealed `byd_canonical_adjusted_ohlcv_v1`
- Adjusted OHLCV SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Factor count: `72`
- Stable exploratory shortlist: `17`
- Quarantined open rows excluded from labels: `11`
- Trade ready: `false`
- Fresh untouched holdout available: `false`

This is a factor map, not a promoted BYD model. The 2025–2026-08-03 period has already been observed and is used only as a retrospective stability block.

## Evaluation blocks

- Development A: 2012–2015
- Development B: 2016–2019
- Confirmation A: 2020–2022
- Confirmation B: 2023–2024
- Retrospective stability: 2025–2026-08-03

The forward label is the return from the next eligible open to the open ten sessions later. If either open is quarantined, the label is missing.

A factor enters the exploratory shortlist only when:

- sign consistency is at least 80% across the five blocks;
- median oriented Spearman IC is at least 0.02;
- worst-block oriented IC is no worse than -0.01.

## Stable shortlist

| Rank | Factor | Orientation | Sign consistency | Median oriented IC | Worst oriented IC | Interpretation |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | `drawdown_252` | negative | 100% | 0.1065 | 0.0179 | deeper long drawdown is more constructive |
| 2 | `mom_120` | negative | 100% | 0.0883 | 0.0455 | long-horizon reversal rather than continuation |
| 3 | `open_return_autocorr_20` | positive | 100% | 0.0778 | 0.0664 | recent open-return serial structure contains information |
| 4 | `short_continuation_long_reversal` | positive | 100% | 0.0884 | 0.0347 | short continuation is strongest when long momentum is weak |
| 5 | `open_mom_120` | negative | 100% | 0.0836 | 0.0357 | open-price long-horizon reversal |
| 6 | `momentum_accel_20_60` | positive | 100% | 0.0704 | 0.0485 | medium momentum improvement matters more than level alone |
| 7 | `skip_recent_20_60` | negative | 100% | 0.0678 | 0.0462 | prior medium trend tends to reverse |
| 8 | `drawdown120_x_rebound20` | positive | 100% | 0.0724 | 0.0293 | rebound strength is more useful after a meaningful drawdown |
| 9 | `intraday_range` | positive | 100% | 0.0666 | 0.0277 | wider daily range has a stable but state-dependent relation |
| 10 | `trend_slope_120` | negative | 100% | 0.0571 | 0.0432 | weak long slope precedes stronger medium-frequency returns |
| 11 | `drawdown252_x_rebound60` | positive | 100% | 0.0577 | 0.0155 | long drawdown plus medium recovery interaction |
| 12 | `distance_from_low_20` | positive | 100% | 0.0492 | 0.0202 | confirmed short recovery from a recent low |
| 13 | `skip_recent_20_120` | negative | 80% | 0.0958 | -0.0090 | long trend excluding recent month tends to reverse |
| 14 | `skip_recent_10_40` | negative | 80% | 0.0698 | -0.0039 | shorter skip-recent reversal |
| 15 | `momentum_accel_10_40` | positive | 80% | 0.0696 | -0.0056 | short-to-medium acceleration |
| 16 | `range_position_252` | negative | 80% | 0.0347 | -0.0026 | lower long-range position is more constructive |
| 17 | `distance_from_low_120` | negative | 80% | 0.0355 | -0.0051 | extended distance from the medium low may mean reversion risk |

## Main finding

BYD's more persistent ten-session information is not a simple trend-following effect. It is better described as four related states:

1. **Long-horizon reversal** — `drawdown_252`, reverse `mom_120`, reverse `open_mom_120`, and reverse `trend_slope_120`.
2. **Recovery confirmation** — `distance_from_low_20`, `drawdown120_x_rebound20`, and `drawdown252_x_rebound60`.
3. **Momentum transition** — `momentum_accel_20_60`, `momentum_accel_10_40`, and the short-continuation/long-reversal interaction.
4. **Open-market structure** — `open_return_autocorr_20`, which is one of the most stable candidates but requires further causality and execution checks.

The strongest next hypothesis is therefore a state-conditioned recovery/reversal model, not a broader XGBoost parameter search over generic momentum factors.

## Important limitations

- IC magnitudes are useful but not large enough to establish a tradable factor by themselves.
- Quintile monotonicity and direction-hit rates are not uniformly strong for every shortlisted factor.
- Several factors are strongly correlated and must be clustered before entering a model.
- The same history was used for discovery; a new promotion contract must reserve future prospective evidence.
- The shortlist does not authorize BYD V1.2 or any current target position.

## Workflow evidence

- Workflow run: `30884533786`
- Artifact ID: `8882573557`
- Artifact ZIP SHA-256: `c8a67f30c0fc98edeafa7d9bbfe22fedf5dc648dbd331117ce31b97efd08bc7e`

Recommended next research contract:

- cluster the 17 factors into reversal, recovery, transition, and market-structure groups;
- freeze one compact state-conditioned model family before training;
- use the canonical data SHA in every run;
- avoid retuning against the already-observed 2025+ block;
- require prospective confirmation before any model promotion.
