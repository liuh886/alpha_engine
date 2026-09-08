# CN_27 V1.2 retrospective robustness discovery

- Decision: `retrospective_candidate_identified`
- Selected recipe: `r9_stable_pullback30_vol_target`
- Fresh historical holdout: `false`
- Research only: `true`; trade ready: `false`

## Frozen-gate leader

- Full-window Sharpe: 1.1795
- Annual one-way turnover: 1.7803x
- Maximum drawdown: -23.68%
- Fold Sharpe 25th percentile: 0.8467
- Worst timing perturbation Sharpe: 1.1388

## Interpretation boundary

All six folds and all robustness variants use already-consumed history. This run can
reject fragile ideas and nominate a retrospective candidate, but cannot create a fresh
holdout or authorize promotion. Any candidate still requires unchanged prospective data.
