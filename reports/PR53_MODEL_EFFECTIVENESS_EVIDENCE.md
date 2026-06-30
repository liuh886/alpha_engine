# PR53 Model Effectiveness Evidence

Date: 2026-06-29
Branch: `fix/training-effectiveness`
PR: #53

## Decision

The original training-effectiveness objective is now met locally by the current US
excess candidate. **PR53 is still not ready to merge remotely** because these local
changes and reports are not pushed, and GitHub still reports the old backend/frontend
checks as failed (`UNSTABLE`).

## Validated Candidate

Artifact: `cc7a0c9accde4934bda6a105b83a302a`

Protocol:

- target: stock 20-session forward return minus same-date QQQ forward return
- features: 10 predeclared momentum, volatility, drawdown, and volume expressions
- model: deterministic LightGBM LambdaRank, depth 3, 7 leaves
- selection: stable train/validation IC only; no test input and no monotone constraint
- production train/valid: 2021-01-01 through 2024-12-31 with 20-session purges
- historical WF: source begins 2018-01-01; actual fit history must be at least 36 months
- execution: top 15, 20-session non-overlapping rebalance, 20 bps costs

Historical walk-forward:

| Metric | Result | Gate |
|---|---:|---:|
| Successful splits | 11 | >= 8 |
| Failed / skipped | 0 / 5 | reported, not hidden |
| Mean daily CS IC | **+0.03626** | > 0 |
| ICIR | **0.6136** | > 0.30 |
| Positive consistency | **63.64%** | >= 60% |

Current-code 2025-2026 holdout:

| Metric | Vectorized | Grade/regime |
|---|---:|---:|
| Total return | +36.64% | +41.21% |
| QQQ return | +9.41% | +9.41% |
| Excess return | **+27.23%** | **+31.80%** |
| Sharpe | 0.767 | 0.910 |
| Max drawdown | -22.19% | -18.94% |
| Mean IC | +0.1026 | +0.1026 |
| ICIR | 0.3474 | 0.3474 |
| Positive IC ratio | 69.08% | 69.08% |
| Non-overlapping periods | 19 | 19 |

The candidate passes every predeclared effectiveness gate. The competing absolute
20-day model has a stronger recent holdout but fails historical WF (mean IC -0.0148,
ICIR -0.228, consistency 38.46%), so governance excludes it from the Best selection.

## Falsified Alternatives

- Alpha158 regression, including monotone constraints: strong recent holdout but
  negative historical WF.
- Alpha158 LambdaRank with 10-day target: mean IC -0.0050, ICIR -0.111,
  consistency 50%.
- At least 36 months of expanding history alone: mean IC -0.0084, ICIR -0.169.
- 36-month rolling history: mean IC -0.0088, ICIR -0.185.
- Signed linear feature ensemble: mean IC -0.0165, consistency 25%.
- Curated 10-day model: positive mean IC but failed ICIR/consistency gates.

These results isolate the improvement to the combination of a predeclared compact
feature family and a lower-noise 20-session target/execution horizon, not merely a new
objective or post-hoc recent-period filter.

## Correctness Controls

- Forward labels are not sign-inverted.
- Train/validation/test use observed-session horizon purges at both boundaries.
- Data is aligned by `(datetime, instrument)`, never array position.
- IC is mean daily cross-sectional IC.
- Non-finite ranking labels are removed before relevance grouping.
- Artifacts persist exact backtest predictions/returns and complete inference metadata.
- Registration and Best selection require >=8 successful splits, mean IC > 0,
  ICIR > 0.3, consistency >=0.6, and positive holdout excess.

## Quality Gates

- Backend: 1281 passed, 15 skipped.
- Frontend: 156 passed; production build passed.
- Ruff: passed.
- mypy release/metric contracts: passed.
- Python sdist/wheel build: passed.
- CN workflow config restored to the exact `HEAD` hash after generated-test drift.

## Remote Merge Gate

Before merging PR53:

1. Review and commit the intended local changes (excluding user PNGs and unrelated
   `AGENTS.md` changes).
2. Push `fix/training-effectiveness`.
3. Rerun GitHub backend/frontend required checks and require green status.
4. Confirm PR53 still targets the reviewed commit and has no new review blockers.
