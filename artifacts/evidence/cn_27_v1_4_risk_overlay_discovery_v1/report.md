# CN_27 V1.4 risk-overlay retrospective discovery

- Decision: `retrospective_risk_overlay_candidate_identified`
- Selected recipe: `p3_shrink_minimum_variance_reference`
- Signal and pool unchanged from frozen V1.2: `true`
- Fresh historical holdout: `false`
- Research only: `true`; trade ready: `false`

## Frozen-gate leader

- Recipe: `p3_shrink_minimum_variance_reference`
- Full-window Sharpe: 1.2428
- Maximum drawdown: -19.20%
- Bootstrap Sharpe p05: 0.3492
- P(Sharpe > 1): 67.50%
- Parameter-neighborhood minimum Sharpe: 1.1489

## Interpretation boundary

This is a third-order retrospective portfolio-construction test on fully consumed
history. It may reject risk overlays or nominate one for prospective observation,
but it cannot refresh the holdout, authorize promotion, or support live trading.
