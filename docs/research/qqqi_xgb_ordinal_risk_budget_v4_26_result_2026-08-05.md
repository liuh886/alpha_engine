# v4.26 XGBoost ordinal risk-budget convergence result

Date: 2026-08-05  
Issue: #547  
Pull request: #549  
Decision: `xgb_ordinal_risk_budget_not_supported`

## Executive conclusion

v4.26 tested the last preregistered architecture that could convert the v4.23-v4.24 XGBoost evidence into one explicit candidate without new information or parameter search.

The experiment fitted one four-class `multi:softprob` model across defense, bridge, core and leveraged states. It used the exact v4.24 path-utility labels and mapped the posterior expected risk index to the nearest ordered state.

The candidate failed:

- pooled macro one-vs-rest AUC: 0.4908;
- quadratic weighted kappa: -0.0070;
- macro recall: 0.2076;
- utility regret: 6.94% worse than frozen v4.2;
- positive outer folds: 2/4;
- label-placebo beat rate: 50%;
- 2024+ utility regret: 8.60% worse than v4.2.

The model avoided v4.23's direct endpoint over-selection, but failed in the opposite direction. Predictions concentrated in bridge and core while realized oracle states were predominantly defense and leveraged. The current 35 daily features do not identify when the correct risk budget is at either endpoint.

The daily-feature XGBoost candidate path is closed. Frozen v4.2 is the explicit converged candidate model for prospective evidence collection.

## Final head evidence identity

- workflow run: `31004901099`;
- artifact: `8929899467`;
- artifact digest: `sha256:ef32dbcb5d4b0798874c304c23da21cd8eff43600a52640f1a211a8303a80221`;
- source bars through 2026-08-04, with the latest VIX row through 2026-08-05;
- OOF decision blocks: 201;
- actual 2024+ blocks: 62;
- manifest files: 17;
- independently verified hashes: 17/17;
- Phase 2 portfolio evidence: correctly skipped;
- candidate shadow authorized: false;
- direct promotion authorized: false.

## Invalid implementation-preflight run

Workflow `31004129547` stopped before model fitting because the first implementation imposed an extra minimum of five observations per class. The earliest training fold contained:

- defense: 58;
- bridge: 2;
- core: 6;
- leveraged: 59.

Issue #547 did not preregister this guard, and `multi:softprob` permits a rare class under a fixed four-class contract. The failed run generated no predictions or economic results.

The implementation-only guard was removed. Labels, features, folds, model parameters, posterior mapping and validation gates were unchanged. Rare-class usefulness was evaluated by the registered recall, kappa, state-coverage, placebo and economic gates.

## Frozen architecture

| Index | State | Historical weights | Actual weights |
|---:|---|---|---|
| 0 | defense | 100% BIL | 100% SGOV |
| 1 | bridge | 50% BIL + 50% QQQ | 50% SGOV + 50% QQQ |
| 2 | core | 100% QQQ | 100% QQQ |
| 3 | leveraged | 25% QQQ + 75% TQQQ | 25% QQQ + 75% TQQQ |

For each non-overlapping ten-session block:

1. execute at the next adjusted open;
2. apply 10 bps per turnover unit;
3. compute terminal net return and maximum adverse excursion;
4. define path utility as terminal return plus `0.50 × MAE`;
5. assign the highest-utility state as the oracle, breaking ties toward lower risk;
6. fit one four-class XGBoost model;
7. compute `expected_risk = Σ p(state=k) × k`;
8. round half-up to select the state.

Inputs and model were frozen:

- 21 market/path features;
- eight credit/duration features;
- six frozen-v4.2 context features;
- 35 inputs total;
- depth 3, eta 0.03, 300 rounds, `min_child_weight=4`;
- subsample and column sample 0.80;
- L2 10, L1 1, gamma 0.10, max bin 64;
- four chronological outer folds and 20 deterministic label permutations.

No action descriptors, class weighting, threshold search, calibration, state deletion, feature selection or parameter comparison was allowed.

## Phase 1 results

| Metric | Result | Gate | Outcome |
|---|---:|---:|---|
| Macro OVR AUC | 0.4908 | >=0.56 | Fail |
| Quadratic weighted kappa | -0.0070 | >=0.12 | Fail |
| Macro recall | 0.2076 | >=0.30 | Fail |
| Multiclass log loss | 1.1029 | descriptive | — |
| Mean absolute state error | 1.4080 | descriptive | — |
| Utility-regret reduction vs v4.2 | -6.94% | >=15% | Fail |
| Median utility advantage | 0.00% | >0 | Fail |
| Positive outer folds | 2/4 | >=3/4 | Fail |
| Top-two utility rate | 52.74% | >=60% | Fail |
| Minimum state selections | 4 | >=10 | Fail |
| Maximum state share | 56.22% | <=60% | Pass |
| Placebo beat rate | 50% | >=90% | Fail |
| Largest feature SHAP share | 8.82% | <=20% | Pass |
| Largest family SHAP share | 27.51% | <=50% | Pass |

Probability geometry passed. Every test fold had one distinct expected-risk value per decision block, and class probabilities summed to one within `7.9e-8`. The failure is not caused by constant predictions or malformed probabilities.

## Chronological evidence

| Fold | Macro AUC | QWK | Macro recall | Regret reduction | Total utility advantage | Top-two rate |
|---|---:|---:|---:|---:|---:|---:|
| 2016-2017 | 0.6099 | 0.0594 | 0.1585 | -12.42% | -14.08% | 58.82% |
| 2018-2019 | 0.5172 | 0.0199 | 0.3971 | +6.37% | +11.58% | 50.00% |
| 2020-2021 | 0.4449 | 0.0159 | 0.1250 | -24.49% | -50.30% | 52.00% |
| 2022-2023 | 0.4358 | 0.0182 | 0.0972 | +0.36% | +0.90% | 50.00% |

Two folds had positive total utility, but neither the classification evidence nor the pooled economics approached the registered gates. The stronger 2016-2017 AUC did not translate into economic improvement.

## Failure mechanism: middle-state compression

### Realized OOF oracle states

| State | Blocks | Share |
|---|---:|---:|
| defense | 78 | 38.81% |
| bridge | 7 | 3.48% |
| core | 12 | 5.97% |
| leveraged | 104 | 51.74% |

### Model-selected OOF states

| State | Blocks | Share |
|---|---:|---:|
| defense | 4 | 1.99% |
| bridge | 80 | 39.80% |
| core | 113 | 56.22% |
| leveraged | 4 | 1.99% |

Defense or leveraged supplied 182 of 201 oracle labels. The posterior expectation converted uncertainty about those endpoints into middle-state allocations.

Pooled class recall:

- defense: 2.56%;
- bridge: 28.57%;
- core: 50.00%;
- leveraged: 1.92%.

Exact state accuracy was 5.97%. The model did not learn when to select the two economically decisive endpoint states.

This completes the structural sequence:

- v4.23 selected endpoints too frequently because action descriptors and terminal-return ranking encoded an endpoint prior;
- v4.24 removed action priors, but independent adjacent path timing was not predictive;
- v4.26 estimated a joint posterior, but smoothed endpoint uncertainty into incorrect middle states;
- no tested topology identified endpoint timing from the current information set.

## Placebo and feature evidence

Observed utility-regret reduction was -6.94% and beat only 10 of 20 deterministic label permutations. It was not distinguishable from shuffled ordinal labels under the registered standard.

SHAP remained diversified:

| Feature family | SHAP share |
|---|---:|
| credit/duration | 27.51% |
| relative strength | 25.42% |
| QQQ price path | 22.78% |
| volatility | 20.11% |
| v4.2 context | 4.18% |

The largest feature, `qqq_voo_bollinger_gap`, contributed 8.82%. The failure is not caused by one dominant action descriptor or leakage-like input.

## Actual 2024+ quarantine evidence

The actual window contained 62 decision blocks.

| Metric | Result |
|---|---:|
| Mean utility advantage vs v4.2 | -0.33% per block |
| Median utility advantage | -0.21% |
| Total utility advantage | -20.47% |
| Top-two utility rate | 61.29% |
| Utility-regret reduction | -8.60% |

Selected states:

- bridge: 33;
- core: 29;
- defense: 0;
- leveraged: 0.

Actual oracle states:

- defense: 24;
- bridge: 1;
- core: 5;
- leveraged: 32.

The quarantine window independently repeats the middle-state compression failure.

## Candidate decision

Phase 1 failed, so the workflow generated no OOF or actual portfolio headline, CAGR, Calmar, drawdown, shadow signal or alert target.

Final decision:

`xgb_ordinal_risk_budget_not_supported`

Consequences:

- v4.26 is rejected as a shadow candidate;
- the current 35-feature daily XGBoost path is closed;
- no v4.27 may change tree parameters, class weights, posterior mapping, states, horizon or feature subset;
- no post-result argmax, endpoint-only classifier, state deletion or SHAP feature selection is permitted;
- frozen v4.2 becomes the explicit converged candidate model;
- v4.2 remains the sole alert source;
- Telegram and Issue #348 remain unchanged;
- another learned candidate requires genuinely new point-in-time-safe information admitted by a separate Phase 0 contract.
