# CN_27 V1.2 retrospective robustness discovery

- Decision: `retrospective_candidate_identified`
- Selected recipe: `s1_stable_all7_30_vol_target`
- Fresh historical holdout: `false`
- Research only: `true`; trade ready: `false`

## Frozen-gate leader

- Full-window Sharpe: 1.1183
- Annual one-way turnover: 1.5747x
- Maximum drawdown: -21.17%
- Fold Sharpe 25th percentile: 0.7646
- Worst timing perturbation Sharpe: 0.9570

## Interpretation boundary

All six folds and all robustness variants use already-consumed history. This run can
reject fragile ideas and nominate a retrospective candidate, but cannot create a fresh
holdout or authorize promotion. Any candidate still requires unchanged prospective data.
