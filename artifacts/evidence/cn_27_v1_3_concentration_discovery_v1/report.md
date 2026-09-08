# CN_27 V1.3 concentration-governance discovery

- Decision: `no_concentration_governed_candidate_passed_frozen_gate`
- Selected recipe: `None`
- Frozen V1.2 signal and V1.4 covariance family retained: `true`
- Fresh historical holdout: `false`
- Research only: `true`; trade ready: `false`

## Frozen-gate leader

- Recipe: `g0_unconstrained_control`
- Full-window Sharpe: 1.2428
- Maximum drawdown: -19.20%
- Bootstrap Sharpe p05: 0.3333
- Worst timing Sharpe: 0.9626
- Maximum post-drift sector share: 65.63%
- Median effective names: 7.17
- Leave-one-sector minimum Sharpe: 1.1196

## Interpretation boundary

This fourth-order retrospective test uses fully consumed history. Passing its frozen
gate can nominate a formal research-only V1.3 candidate, but cannot create fresh
validation, authorize promotion, or support live trading.
