# v4.24 XGBoost ordinal adjacent-state path-utility result

Date: 2026-08-05  
Issue: #530  
Pull request: #533  
Decision: `xgb_adjacent_path_utility_not_supported`

## Executive summary

v4.24 tested whether three fixed shallow XGBoost classifiers could learn adjacent transitions across a four-level risk ladder using path-aware utility rather than terminal-return ranking.

The final audited experiment is a valid negative result:

- all 12 fold×edge models produced non-constant probabilities;
- 18/18 artifact file hashes were independently verified;
- the four-state topology avoided the v4.23 endpoint collapse;
- feature importance was distributed rather than dominated by action descriptors;
- nevertheless, edge AUC, balanced accuracy, utility regret, fold consistency, top-two accuracy and placebo gates all failed;
- Phase 2 portfolio construction was correctly skipped.

The result indicates that the current daily price, volatility, relative-strength and credit/duration information set does not reliably predict adjacent ten-session path utility out of sample.

## Frozen architecture

### Ordered states

| State | Historical weights | Actual-product weights |
|---|---|---|
| Defense | 100% BIL | 100% SGOV |
| Bridge | 50% BIL + 50% QQQ | 50% SGOV + 50% QQQ |
| Core | 100% QQQ | 100% QQQ |
| Leveraged | 25% QQQ + 75% TQQQ | 25% QQQ + 75% TQQQ |

### Adjacent classifiers

1. defense versus bridge;
2. bridge versus core;
3. core versus leveraged.

Every model received the same 35 inputs:

- 21 raw market features inherited from v4.16;
- eight credit/duration features admitted by v4.19;
- six frozen next-open v4.2 state and weight context variables.

Candidate-state weights were not model inputs.

### Path utility

For each state and each non-overlapping ten-session decision block:

1. enter at the next adjusted open;
2. apply exact entry turnover from frozen-v4.2 proxy-economic weights;
3. hold for ten open-to-open sessions;
4. apply reconciliation turnover to frozen-v4.2 end weights;
5. compute terminal net return;
6. compute maximum adverse excursion from the cumulative net path;
7. calculate:

`path_utility = terminal_net_return + 0.50 × maximum_adverse_excursion`

Maximum adverse excursion is zero or negative, so deeper adverse paths lower utility.

### Model

- XGBoost `binary:logistic`;
- max depth 3;
- learning rate 0.03;
- 300 rounds;
- subsample and column sample 0.80;
- L2 10.0;
- L1 1.0;
- gamma 0.10;
- fixed seeds;
- no early stopping, parameter search, feature selection or threshold search.

## Compatibility correction before valid evidence

The first workflow artifact is not part of the economic result:

- workflow: `30939933439`;
- artifact: `8904708915`;
- digest: `sha256:6ab0b71c675ff868d9c82e5982e227c0ea157eb1e21ad6a60b2c9228c0ac8050`.

It reused v4.23 `min_child_weight=20`. v4.23 had five action rows per decision group, whereas each v4.24 edge model has one row per decision date. In the first two folds all six edge models emitted a single constant probability, so the artifact could not test the intended hypothesis.

The discarded result was not interpreted economically. The parameter was mechanically scaled by row geometry:

`20 × (1 row / 5 rows) = 4`

No target, state, feature, threshold, outer fold or validation gate changed. A new hard check required at least two distinct probabilities in every fold×edge test cell.

## Final evidence identity

- workflow: `30940446053`;
- artifact: `8904922382`;
- artifact digest: `sha256:589b88fba1fc344eb0f26ce9c919d3aac8c0e6f50e0f5a2b7245febcf88c1b02`;
- source data through: `2026-08-04`;
- manifest files: 18;
- independently verified hashes: 18/18;
- OOF decision blocks: 201;
- actual 2024+ decision blocks: 62;
- probability geometry: 12/12 fold×edge cells passed.

The adjusted-open/close research adapter preserved provider-adjusted open and close prices. Synthetic high/low envelopes were not used by any feature or label.

## Embargo and chronology

| Fold | Training groups | Training end | Test groups | Test period |
|---|---:|---|---:|---|
| 2016–2017 | 125 | 2015-12-07 | 51 | 2016-01-06 to 2017-12-29 |
| 2018–2019 | 176 | 2017-12-14 | 50 | 2018-01-16 to 2019-12-26 |
| 2020–2021 | 226 | 2019-12-11 | 50 | 2020-01-10 to 2021-12-20 |
| 2022–2023 | 276 | 2021-12-06 | 50 | 2022-01-04 to 2023-12-15 |

Every fold excludes the immediately preceding ten-session decision group, leaving one complete intervening group. No target overlap or leakage was found.

## Phase 1 results

### Headline

| Metric | Result | Gate | Outcome |
|---|---:|---:|---|
| Mean edge AUC | 0.4883 | ≥0.58 | Fail |
| Minimum edge AUC | 0.4624 | ≥0.52 | Fail |
| Mean balanced accuracy | 0.4966 | ≥0.55 | Fail |
| Utility-regret reduction vs v4.2 | -17.34% | ≥20% | Fail |
| Median selected utility advantage | 0.00% | >0 | Fail |
| Positive outer folds | 1/4 | ≥3/4 | Fail |
| Top-two utility rate | 48.76% | ≥60% | Fail |
| Minimum state selections | 19 | ≥10 | Pass |
| Maximum state share | 38.81% | ≤60% | Pass |
| Placebo beat rate | 30% | ≥90% | Fail |
| Largest single-feature SHAP share | 10.48% | ≤20% | Pass |
| Largest feature-family SHAP share | 28.57% | ≤50% | Pass |

### Edge diagnostics

| Edge | Positive rate | AUC | Balanced accuracy | Brier score |
|---|---:|---:|---:|---:|
| Defense vs bridge | 61.19% | 0.4624 | 0.4755 | 0.2641 |
| Bridge vs core | 57.71% | 0.4834 | 0.4896 | 0.2737 |
| Core vs leveraged | 51.74% | 0.5191 | 0.5249 | 0.2722 |

Only core versus leveraged was slightly above random in pooled AUC, but it was not preregistered as an independent promotion candidate and cannot be selected after inspection.

### Fold evidence

| Fold | Regret reduction | Top-two rate | Total utility advantage vs v4.2 |
|---|---:|---:|---:|
| 2016–2017 | +15.36% | 54.90% | +17.42% |
| 2018–2019 | -16.14% | 52.00% | -29.35% |
| 2020–2021 | -29.18% | 46.00% | -59.93% |
| 2022–2023 | -23.39% | 42.00% | -57.76% |

The signal did not merely weaken in later folds; it reversed economically after 2017.

### State coverage

| State | Selected blocks | Share | Top-two rate | Median utility advantage |
|---|---:|---:|---:|---:|
| Defense | 55 | 27.36% | 34.55% | -1.51% |
| Bridge | 19 | 9.45% | 52.63% | +0.34% |
| Core | 49 | 24.38% | 57.14% | 0.00% |
| Leveraged | 78 | 38.81% | 52.56% | 0.00% |

v4.24 successfully avoided v4.23's endpoint collapse. The failure therefore cannot be attributed to a missing state-diversity constraint. The model selected all four states but selected them at the wrong times.

### Placebo

Observed utility-regret reduction was `-17.34%`. It beat only 6 of 20 deterministic label-permutation paths. Several randomized models lost less utility than the real-label model.

### SHAP

| Family | Mean absolute SHAP share |
|---|---:|
| Credit/duration | 28.57% |
| QQQ price path | 25.20% |
| Relative strength | 23.19% |
| Volatility | 19.15% |
| Frozen v4.2 context | 3.89% |

Largest individual features:

- QQQ minus VOO 5-day return: 10.48%;
- QQQ distance from MA200: 9.51%;
- HYG/SHY 20-day relative return: 9.10%.

The importance distribution passed both concentration gates. The negative result is not caused by one static feature dominating the model.

## 2024+ quarantine diagnostic

No portfolio was generated, but frozen models trained through 2023 produced a read-only score ledger for 62 actual-product blocks.

State selections:

- defense: 29;
- bridge: 5;
- core: 6;
- leveraged: 22.

Diagnostics:

- mean utility advantage versus v4.2: -0.71% per block;
- median utility advantage: -0.26%;
- total utility advantage: -44.05%;
- top-two utility rate: 53.23%;
- utility-regret reduction: -18.51%.

The actual window confirms rather than contradicts the OOF failure.

## Why Phase 2 was skipped

Phase 1 failed model discrimination, economic regret, fold consistency, top-two and placebo gates. The runner therefore produced no:

- OOF state-machine portfolio;
- CAGR, Sortino, drawdown or Calmar promotion comparison;
- 2024+ portfolio;
- shadow signals;
- alert changes.

This is the intended fail-closed behavior.

## Structural conclusion

v4.23 and v4.24 jointly identify the boundary:

- with candidate action descriptors and terminal-return labels, XGBoost learns real but mostly static convex endpoint priors;
- without candidate action descriptors and with a path-aware adjacent target, the current daily feature set has no stable OOF timing power.

The evidence therefore does not support deeper trees, probability-threshold search, a different MAE coefficient, state deletion or another booster on the same 35 features and history.

The next admissible XGBoost study must begin with genuinely new pre-decision information. Candidate sources include option skew and tail pricing, dealer/option positioning proxies, survivorship-safe breadth data or direct credit-spread levels. Source coverage and admissibility must be proven before outcome calculation.

## Decision

`xgb_adjacent_path_utility_not_supported`

- no prospective shadow model;
- no direct promotion;
- no v4.2 change;
- no Telegram change;
- Issue #348 unchanged;
- retain the path-utility frame, adjacent-edge implementation, probability-geometry audit, placebo framework and negative evidence.