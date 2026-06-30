# PR53 CN Model Effectiveness Evidence

Date: 2026-06-29
Branch: `fix/training-effectiveness`
PR: #53

## Protocol

- **Market**: CN A-share; benchmark CSI 300 (`000300`).
- **Candidate selection**: Eight predeclared combinations of Alpha158/curated momentum,
  10/20-session horizon, and regression/LambdaRank. Selection uses historical
  walk-forward evidence only.
- **Walk-forward**: Expanding history from 2018-01-01, 36-month minimum fit,
  six-month test windows, three-month step, and observed-session boundary purges.
- **Production fit**: 2021-01-01 through 2024-12-31, with train/validation/test purges.
- **Holdout**: 2025-01-02 through 2026-06-18, opened once after candidate selection.
- **Execution**: Top 15, horizon-matched rebalance, 20 bps round-trip cost.
- **Registration**: Historical effectiveness, stored-prediction inference, and
  clean-process reconstruction must all pass before STAGING registration.

## Historical Candidate Results

| Candidate | Profile | Horizon | Objective | Mean IC | ICIR | Consistency | Result |
|---|---|---:|---|---:|---:|---:|---|
| a158_10d_reg | Alpha158 | 10 | regression | 0.0001 | 0.0016 | 38.5% | Fail |
| a158_10d_lambda | Alpha158 | 10 | LambdaRank | 0.0059 | 0.1363 | 61.5% | Fail |
| a158_20d_reg | Alpha158 | 20 | regression | -0.0033 | -0.1658 | 30.8% | Fail |
| a158_20d_lambda | Alpha158 | 20 | LambdaRank | 0.0052 | 0.1244 | 69.2% | Fail |
| curated_10d_reg | Curated | 10 | regression | 0.0004 | 0.0128 | 53.8% | Fail |
| curated_10d_lambda | Curated | 10 | LambdaRank | 0.0082 | 0.3118 | 53.8% | Fail |
| curated_20d_reg | Curated | 20 | regression | -0.0039 | -0.0979 | 46.2% | Fail |
| curated_20d_lambda | Curated | 20 | LambdaRank | **0.0176** | **0.5761** | **76.9%** | **Pass** |

The selected model completed 13 of 16 splits; three were skipped and none failed.
Its positive-IC ratio was 76.9%.

## Final Holdout Confirmation

| Metric | Vectorized baseline | Grade/regime execution |
|---|---:|---:|
| Total return | 23.22% | **33.65%** |
| CSI 300 return | 28.99% | 28.99% |
| Excess return | -5.77% | **4.66%** |
| Annual return | 14.85% | **21.21%** |
| Sharpe | 0.8275 | **1.3063** |
| Max drawdown | -12.11% | **-4.54%** |
| Volatility | 18.93% | **15.74%** |
| Mean daily cross-sectional IC | 0.0320 | 0.0320 |
| Holdout ICIR | 0.2869 | 0.2869 |
| Positive IC ratio | 65.69% | 65.69% |

The governance result uses the grade/regime execution path. It exceeded CSI 300
after costs while preserving the single-use holdout protocol.

## Artifact Registration

| Version ID | Artifact ID | Stage |
|---|---|---|
| `cn_model_optimal_alpha158_absret_curated_20d_lambda_20260629` | `9cd7e27bd300453eb706db2bda89645e` | STAGING |

- Inference gate: 500/500 stored predictions matched; correlation 1.0.
- Clean reconstruction: 80,180/80,180 predictions matched; correlation 1.0.
- Effectiveness gate: 13 successful splits, ICIR 0.5761, consistency 76.9%,
  holdout excess 4.66%.

## Falsified Alternatives

- Artifact `00ff24f6` used sign-inverted labels and overlapping boundaries;
  excess return was -438.76%, mean IC -0.0111, and ICIR -0.0655.
- Artifact `6d3a55103a6b4268b022a5b3bbf1dbec` exposed a protocol mismatch:
  candidate selection used depth 3/no monotonic constraints, while final fitting
  used depth 4/negative constraints. It was not registered.
- The final fit uses the exact selected protocol: depth 3, seven leaves, six
  selected features, and no monotonic constraints.

## Correctness Controls

- Labels preserve the forward-return direction.
- Segment boundaries are purged by observed trading sessions.
- Data alignment uses `(datetime, instrument)`, never array position.
- IC is daily cross-sectional IC.
- Feature selection uses train and validation data only.
- The artifact stores the exact normalized inference features, scores, returns,
  selected schema, normalization parameters, snapshot, and costs.
- The frontend exposes total, benchmark and excess return, drawdown, Sharpe,
  mean IC, ICIR, positive-IC ratio, consistency, and split counts.
