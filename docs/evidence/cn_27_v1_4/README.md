# CN_27 V1.4 risk-overlay discovery

This experiment keeps the frozen CN_27 V1.2 factor signal, candidate pool,
rebalance schedule, execution delay, trade-lock retry policy, and asymmetric
costs unchanged. It tests only portfolio weighting and equity-risk budgeting.

The pre-screen contract is
`configs/research_experiments/cn_27_v1_4_risk_overlay_discovery_v1.yaml`.
The manifest-bound evidence is in
`artifacts/evidence/cn_27_v1_4_risk_overlay_discovery_v1`.

## Result

The frozen gate selected `p3_shrink_minimum_variance_reference`:

- full-window Sharpe: 1.2428;
- maximum drawdown: -19.20%;
- annual one-way turnover: 1.7652x;
- double-cost Sharpe: 1.2331;
- worst timing-perturbation Sharpe: 0.9626;
- circular block-bootstrap Sharpe p05: 0.3492;
- conditional probability of Sharpe above one: 67.5%;
- parameter-neighborhood minimum Sharpe: 1.1489.

The V1.2 control had Sharpe 1.1183, maximum drawdown -21.17%, annual one-way
turnover 1.5747x, bootstrap Sharpe p05 0.2461, and conditional probability of
Sharpe above one 58.9%.

## Important limitations

This is a third-order retrospective test on fully consumed history. The weakest
of the six chronological folds has Sharpe 0.1164. The high-shrinkage neighbor
has maximum drawdown -21.46%, so the drawdown improvement is not uniform across
the complete parameter neighborhood even though every predeclared parameter
gate passes.

A post-screen diagnostic also found that the selected minimum-variance path has
a lower median effective stock count than V1.2 (7.2 versus 10.1) and a higher
maximum industry share of the equity sleeve (65.6% versus 47.2%) after market
drift. Positive return attribution is less concentrated: the largest stock and
industry account for 11.08% and 31.61% of positive stock contribution. This
diagnostic is not part of the frozen selection gate and must not be used to
retroactively change that gate.

The result can nominate an unchanged risk overlay for prospective observation.
It does not create a fresh holdout, authorize model promotion, satisfy the
selected-pool readiness program, or support live trading. All outputs remain
`research_only=true` and `trade_ready=false`.

## Reproduction

Run `python scripts/run_cn_27_v1_4_discovery.py` from the repository root. The
runner verifies the model contract, both predecessor manifests, all predecessor
output hashes, the pool, and source prices before executing the frozen matrix.
