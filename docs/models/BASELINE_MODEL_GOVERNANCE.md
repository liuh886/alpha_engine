# Baseline model lifecycle: US x1.0 and CN x1.0

## Purpose

Alpha Engine now names its first governed selected-pool model contracts **US x1.0** and **CN x1.0**. A model version is an immutable combination of universe rules, factor group, effective label/model runtime, portfolio conversion, cost convention and evidence lineage. It is not a promise that one backtest percentage is invariant across provider snapshots.

## Canonical baselines

| Model | Universe | Benchmark | Feature group | Effective XGBoost runtime | Status |
|---|---|---|---|---|---|
| US x1.0 | `us_selected_equities_v2` | QQQ | `risk_controlled_momentum` | gain7, 200 rounds, `max_leaves=31`, `learning_rate=0.05`, seed 42 | research baseline |
| CN x1.0 | `cn_selected_equities_v3` | CSI 300 | `cn_balanced_ohlcv` | gain5, 100 rounds, `max_leaves=31`, `learning_rate=0.05`, seed 42 | research baseline; data drift review |

Both use a 10-session label, 10-session holding/rebalance, Top-15 equal weight and 20 bps cost. Both remain `trade_ready=false`.

## Declared calibration versus effective runtime

The frozen research specs inherited calibration fields originally designed around LightGBM. In the current XGBoost path:

- `n_gain_bins` is consumed;
- `num_boost_round` is consumed;
- spec fields `num_leaves`, `min_data_in_leaf` and `learning_rate` are not passed into the XGBoost adapter;
- XGBoost uses its adapter-owned fixed runtime: `max_leaves=31`, `max_depth=0`, `learning_rate=0.05`, `seed=42`.

Accordingly, PR #343 supports the effect of the risk-controlled feature family, seven relevance gains and 200 rounds. It does **not** establish that `learning_rate=0.03` or `min_data_in_leaf=20` improved the US model. PR #344 likewise did not execute a complete XGBoost regularization grid. The model cards and notebooks preserve both the legacy candidate identity and the verified effective runtime.

No future regularization experiment is valid until the XGBoost parameter interface is explicit and identity-bound.

## Version semantics

- **x1.0 is immutable.** New evidence may be attached, but parameters and semantics are never overwritten.
- **x1.1** is used for a backward-compatible, evidence-supported improvement that preserves the same market, universe contract, target horizon and portfolio role.
- **x2.0** is required when the universe contract, label, horizon, objective family, execution semantics or portfolio role changes materially.
- A provider refresh creates a new evidence revision, not automatically a new model version.
- An experiment cannot promote itself. Promotion requires a reviewed decision record and one new untouched challenge window.
- A previously consumed holdout may be used for reporting and robustness diagnostics, but never again for candidate selection.

## Evidence hierarchy

1. Model config in `configs/models/`, including declared-to-effective parameter mapping.
2. Frozen research spec and code/config hashes.
3. Promotion-eligible provider manifest and provider identity.
4. Workflow run, artifact ID and digest.
5. Complete development and challenge metrics.
6. Canonical notebook explaining and validating the contract.

A metric without this chain is exploratory and cannot be attached to a named model.

## Experiment workflow

Every experiment must declare:

- parent model version;
- isolated experiment ID;
- hypothesis and bounded changes;
- development, validation and untouched challenge periods;
- attempted-variant count;
- acceptance and stop rules;
- data/provider identity;
- declared and effective runtime parameters;
- final result: `promote_minor_candidate`, `retain_baseline`, `data_blocked` or `not_reproducible`.

An effective experiment becomes a **candidate for the next version**. It does not mutate x1.0.

## Current research queue

### US x1.0 → potential US x1.1

Priority order:

1. full-backtest window, cost and selection-recurrence stress under Issue #355;
2. security, sector and rebalance-period contribution concentration;
3. seed and block-bootstrap rank/Top-15 stability;
4. explicit XGBoost regularization interface and a newly pre-registered grid;
5. risk-control and Top-K robustness;
6. one new untouched challenge window.

The unresolved 81.43% historical claim is not an optimization target.

### CN x1.0 → potential CN x1.1

Issue #345 is a hard data gate. Provider-snapshot drift must be attributed before another factor or parameter search. After the gate passes, the next experiment should test ranking validity and hidden exposures before portfolio optimization. A true regularization experiment also requires explicit XGBoost parameter mapping.

## Reproduction

The model notebooks contain contract-validation cells and exact CLI commands. Full backtests require the governed provider build and are intentionally opt-in because they are computationally expensive.
