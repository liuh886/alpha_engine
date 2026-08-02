# Baseline model lifecycle: US x1.1 and CN x1.0

## Purpose

Alpha Engine uses named, immutable model contracts for governed research. A model version binds the universe rules, feature group, label, effective runtime, portfolio conversion, cost convention and evidence lineage. It does not promise that one performance percentage is invariant across provider snapshots.

## Active baselines

| Market | Active model | Universe | Benchmark | Feature group | Effective XGBoost runtime | Status |
|---|---|---|---|---|---|---|
| US | **US x1.1** | `us_selected_equities_v2` | QQQ | `momentum_volatility_volume` | gain7, 200 rounds, `max_leaves=31`, `learning_rate=0.05`, seed 42 | active research baseline |
| CN | **CN x1.0** | `cn_selected_equities_v3` | CSI 300 | `cn_balanced_ohlcv` | gain5, 100 rounds, `max_leaves=31`, `learning_rate=0.05`, seed 42 | research baseline; data review |

US x1.0 remains an immutable historical baseline and is superseded by US x1.1 for new US experiments. All named models remain `research_only=true` and `trade_ready=false`.

## US x1.1 promotion

US x1.1 promotes the former `us_x1_1_candidate_a` contract following the user's baseline decision on 2026-08-02. The promotion changes the default comparison model; it does not claim operational or trade readiness.

The promoted evidence is bound to:

- provider identity `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95`;
- workflow run `30737322468`;
- artifact `8830089966`;
- digest `sha256:6638e37ea77a7183253de5f96ec466c2ac0eab66c6f47d58e1040d4421d7fd70`.

Development 2024H1–2025H2 produced +110.44% compounded relative excess versus QQQ, four positive-excess windows, mean ICIR 0.2280 and a -27.15% worst drawdown. Window concentration improved relative to the latest US x1.0 evidence, but AAOI, AEHR and BE still recur in every development final Top-15.

## Declared calibration versus effective runtime

The current frozen specifications retain historical LightGBM-oriented calibration fields. In the existing XGBoost execution path:

- `n_gain_bins` is consumed;
- `num_boost_round` is consumed;
- `num_leaves`, `min_data_in_leaf` and candidate `learning_rate` are not passed into XGBoost;
- the adapter uses `max_leaves=31`, `max_depth=0`, `learning_rate=0.05` and `seed=42`.

Therefore US x1.1 establishes the `momentum_volatility_volume` feature group, seven gain bins and 200 rounds under the verified fixed runtime. It does not establish an effective 0.03 learning rate. Issue #357 must merge before any native XGBoost regularization claim is accepted.

## Version semantics

- Released model files are immutable.
- The registry may mark an older version as historical and point to its successor.
- **x1.2** is the next compatible US version after US x1.1.
- **x2.0** is required for a material change to the universe contract, label, horizon, objective family, execution semantics or portfolio role.
- A provider refresh creates an evidence revision unless its provider identity exactly matches the model card.
- A consumed holdout can be reported but cannot be reused for candidate selection.
- A user may designate a research baseline directly; trade readiness still requires independent validation and operational gates.

## Evidence hierarchy

1. Model config in `configs/models/`.
2. Frozen research specification and effective parameter mapping.
3. Promotion-eligible provider manifest and provider identity.
4. Workflow run, artifact ID and digest.
5. Complete development and reporting metrics.
6. Canonical notebook explaining and validating the contract.

## US x1.1 research queue

### Portfolio and concentration validation — Issue #362

Keep the US x1.1 score fixed and test exactly five portfolio variants:

1. Top-20 equal weight;
2. capped inverse-volatility Top-15;
3. name-capped Top-15;
4. sector-capped Top-15;
5. QQQ trend-based exposure overlay.

The experiment may propose a US x1.2 candidate but cannot update the baseline automatically. It must report 20/40/60 bps cost stress, security and sector contributions, leave-one-name/window robustness and the 2025H1 drawdown decomposition.

### Native XGBoost calibration — Issue #357

First make declared and effective parameters identical. Only then run a bounded native grid for `max_leaves`, `max_depth`, `min_child_weight`, `learning_rate`, `subsample`, `colsample_bytree`, regularization, rounds and seed. Historical candidate names remain legacy evidence and are not rewritten.

### Independent validation

The 2026H1 window is consumed and reporting-only. A new untouched challenge window remains required before any operational or trade-readiness claim.

## CN x1.0 research queue

CN x1.0 remains unchanged. Provider identity `bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8` has been reproduced on the latest run, but ranking validity and hidden exposure attribution remain the next research priority before a CN x1.1 candidate.

## Reproduction

The model notebooks contain contract-validation cells and exact CLI commands. Full backtests require the governed provider build and are intentionally opt-in because they are computationally expensive.
