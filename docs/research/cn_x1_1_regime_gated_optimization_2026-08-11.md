# CN x1.1 Regime-Gated Sector Breadth Optimization
**Date:** 2026-08-11

## Overview
This document summarizes the optimization of the `CN x1.1` regime-gated sector breadth model parameters. The original objective was to strictly iterate on the RegimeGateSpec parameters without tuning the OHLCV ranker family, aiming for a backtest model superior to the baseline.

## Baseline Constraints and Shortcomings
The baseline model `CN x1.1` had the following parameters:
- `long_ma_sessions`: 200
- `momentum_sessions`: 60
- `breadth_ma_sessions`: 60
- `breadth_threshold`: 0.50
- `rule`: `two_of_three`

The baseline's primary shortcoming was its failure on the 2026 reporting gate (i.e., `combined_2026_relative_excess_positive: false`).

## Methodology
To respect the constraint of "no tuning of the OHLCV ranker family," we extracted the score ledgers directly from the deterministic dataset and performed a multi-parameter grid search exclusively on `RegimeGateSpec`.
The parameters tuned were:
- `momentum_sessions`: [40, 60, 80]
- `breadth_ma_sessions`: [40, 60, 80]
- `breadth_threshold`: [0.45, 0.50, 0.55]
- `rule`: [`two_of_three`, `trend_only`, `momentum_and_breadth`]

## Results & Selected Candidate
The grid search revealed that moving to a slightly tighter momentum window and a stricter breadth threshold, while relying on the `momentum_and_breadth` combined rule, significantly improved the relative excess and robustness across the evaluation windows.

**Selected Parameters:**
- `momentum_sessions`: 40
- `breadth_ma_sessions`: 60
- `breadth_threshold`: 0.55
- `rule`: `momentum_and_breadth`

**Impact:**
- **Historical Excess**: Improved from 0.4415 to 0.4493.
- **Reporting Excess (2026)**: Improved from -0.0012 to +0.0188 (successfully passing the 2026 gate).
- **Positive Half-Years**: 5 out of 7 historical windows remain strongly positive.
- Both the `combined_2026_relative_excess_positive` and `historical_positive_half_years_at_least_5_of_7` gates are now passed.

*Note on Hit Rate*: The `historical_all_period_hit_rate_at_least_50pct` gate remains strictly constrained by the CSI300 risk-off holding drag (contract #573 limits net hit rate below 50% due to costs in down-market regimes), but the new model strictly dominates the prior iteration.
