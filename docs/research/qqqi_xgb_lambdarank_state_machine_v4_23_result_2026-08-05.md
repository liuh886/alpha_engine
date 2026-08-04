# v4.23 XGBoost LambdaRank 10D allocation state machine

Decision: `xgb_action_ranking_not_supported`

## Research question

Can one fixed shallow XGBoost learning-to-rank model use the accumulated v4.x factor evidence to choose among five discrete ten-session SGOV/BIL, QQQ and TQQQ allocations, and thereby replace hand-written Boolean state rules without relying on predicted-return magnitude calibration?

The answer is **no under the frozen v4.23 contract**. The model detects non-random action-ranking information, but it does not meet the preregistered regret, top-two accuracy or feature-concentration gates. It also collapses almost completely to the two extreme actions, `defense` and `accelerated`, rather than learning a stable five-state allocation machine.

## Frozen architecture

- signal at the session close;
- execution at the next adjusted open;
- one non-overlapping decision every ten global sessions;
- fixed ten-session holding period;
- ten-session label embargo before every outer fold;
- 10 bps transaction cost per turnover unit;
- five actions:
  - `defense`: 100% BIL historically and 100% SGOV in the actual product period;
  - `balanced`: 50% cash and 50% QQQ;
  - `core`: 100% QQQ;
  - `leveraged`: 25% QQQ and 75% TQQQ;
  - `accelerated`: 100% TQQQ;
- 39 frozen inputs:
  - 21 raw market and volatility inputs inherited from v4.16;
  - the complete eight-feature credit/duration block admitted by v4.19;
  - six frozen v4.2 state and weight descriptors;
  - four candidate-action descriptors;
- one native XGBoost `rank:ndcg` model with NDCG@1;
- fixed max depth 3, eta 0.03, 300 rounds, strong L1/L2 regularization and deterministic seed;
- no parameter search, early stopping on outer folds, feature selection, action deletion or continuous-weight optimization.

Every decision date is one five-row ranking group. Labels are the within-date relevance ranks of exact ten-session action returns after entry and end-of-block reconciliation turnover. The model does not predict return magnitude.

## Evidence identity

- workflow run: `30933201200`;
- artifact: `8902023278`;
- artifact digest: `sha256:d0422f2fb1b0d89380c76eecdbb7c1aa38fc0439c3fc846a773b96e1375fb08d`;
- source data through: `2026-08-04`;
- manifest hashes independently verified: `16/16`;
- OOF decision groups: `201`;
- OOF action rows: `1,005`;
- actual 2024+ complete-label groups: `62`.

The daily source used the audited Yahoo adjusted-open/close research adapter. Adjusted open and close were preserved. Synthetic high/low envelopes were used only to satisfy the common bar schema and were not used by any range, volatility or factor calculation.

## Chronology and leakage audit

| Fold | Training groups | Training end | Test groups | Test start | Decision-grid gap |
|---|---:|---|---:|---|---:|
| 2016–2017 | 125 | 2015-12-07 | 51 | 2016-01-06 | one complete intervening 10D group |
| 2018–2019 | 176 | 2017-12-14 | 50 | 2018-01-16 | one complete intervening 10D group |
| 2020–2021 | 226 | 2019-12-11 | 50 | 2020-01-10 | one complete intervening 10D group |
| 2022–2023 | 276 | 2021-12-06 | 50 | 2022-01-04 | one complete intervening 10D group |

The first evidence run incorrectly interpreted a ten-session embargo as ten complete decision groups. That run was discarded before the final decision. The corrected implementation excludes the immediately preceding decision group and leaves approximately nineteen intervening trading sessions, satisfying the frozen ten-session embargo.

## Phase 1 ranking result

| Metric | v4.23 result | Frozen gate | Result |
|---|---:|---:|---|
| Selected NDCG@1 | 0.5453 | — | diagnostic |
| v4.2-action comparator NDCG@1 | 0.3061 | — | diagnostic |
| NDCG improvement | **+0.2391** | ≥ +0.05 | pass |
| Mean regret reduction | **9.65%** | ≥ 20% | fail |
| Median selected advantage vs v4.2 | **+0.56%** | > 0 | pass |
| Positive outer folds | **3/4** | ≥ 3/4 | pass |
| Selected action in true top two | **55.22%** | ≥ 60% | fail |
| Deterministic placebo beat rate | **100%** | ≥ 90% | pass |
| Largest positive year share | 16.55% | ≤ 35% | pass |
| Largest positive macro-cluster share | 5.86% | ≤ 25% | pass |
| Advantage without best year | +57.25% aggregate | > 0 | pass |
| Advantage without best cluster | +30.82% aggregate | > 0 | pass |
| Largest single-feature SHAP share | **32.65%** | ≤ 20% | fail |
| Largest feature-family SHAP share | **73.49%** | ≤ 50% | fail |

The observed NDCG@1 of 0.5453 exceeded all twenty deterministic label-permutation rankers. Placebo NDCG@1 ranged from approximately 0.278 to 0.397. The model therefore contains real ranking structure; the negative decision is not equivalent to random performance.

However, the economic improvement is materially weaker than the headline NDCG difference. Mean regret falls only 9.65%, and the selected action enters the true top two on only 55.22% of decision dates. Both miss the frozen execution-quality gates.

## Outer-fold result

| Fold | Groups | NDCG improvement | Regret reduction | Top-two rate | Aggregate advantage vs v4.2 |
|---|---:|---:|---:|---:|---:|
| 2016–2017 | 51 | +0.2510 | +33.16% | 54.90% | +43.07% |
| 2018–2019 | 50 | +0.2213 | +14.98% | 56.00% | +27.90% |
| 2020–2021 | 50 | +0.3160 | +12.00% | 64.00% | +24.39% |
| 2022–2023 | 50 | +0.1680 | **-10.68%** | **46.00%** | **-35.23%** |

The 2022–2023 fold is a direct chronological contradiction. NDCG remains above the simple v4.2-action comparator, but economic regret worsens and aggregate advantage becomes materially negative. This shows that rank relevance and executable excess return are not interchangeable.

## Action selection collapse

| Action | Selected OOF blocks | Top-two rate | Median advantage vs v4.2 | Aggregate advantage |
|---|---:|---:|---:|---:|
| Defense | 37 | 29.73% | -0.96% | -45.91% |
| Balanced | 0 | unavailable | unavailable | 0.00% |
| Core | 2 | 0.00% | approximately 0.00% | approximately 0.00% |
| Leveraged | 0 | unavailable | unavailable | 0.00% |
| Accelerated | 162 | 61.73% | +1.14% | +106.04% |

The model does not learn a five-state machine. It behaves almost entirely as an extreme-action selector:

- 80.6% of OOF blocks select 100% TQQQ;
- 18.4% select 100% cash;
- balanced and leveraged are never selected;
- core is selected only twice.

The realized best action is itself structurally concentrated at the extremes: accelerated is best on 56.7% of OOF blocks and defense on 30.8%; balanced, core and leveraged together are best on only 12.4%. This follows from the geometry of ranking terminal return across convex allocation mixtures: absent a path-risk utility, intermediate allocations rarely dominate both endpoints.

Consequently, the model's apparent ranking success is substantially a learned prior over extreme actions rather than stable timing of all five states.

## Feature and interaction diagnostics

The largest mean absolute SHAP shares were:

1. `candidate_qqq_weight`: 32.65%;
2. `candidate_tqqq_weight`: 14.52%;
3. `candidate_l1_from_v4_2_proxy`: 8.33%;
4. `candidate_cash_weight`: 4.75%;
5. `qqq_distance_ma200`: 4.26%.

By family:

| Feature family | Mean absolute SHAP share |
|---|---:|
| Candidate action descriptors | **73.49%** |
| QQQ price path | 7.83% |
| Volatility | 5.86% |
| Credit/duration | 5.70% |
| Relative strength | 5.68% |
| Frozen v4.2 context | 1.44% |

XGBoost did learn nonlinear structure, but most predictive contribution comes from the candidate action identity and weights rather than time-varying market state. The complete credit/duration family remains present but supplies only about 5.7% of mean absolute SHAP contribution in this action-ranking formulation.

This is precisely why the preregistered concentration gates are necessary. Without them, the experiment could be misread as a successful market-state model even though it mainly learns that extreme exposure has historically dominated intermediate mixtures.

## Actual 2024+ diagnostic

Phase 2 was prohibited after the Phase 1 failure, so no actual-product portfolio or promotion comparison was generated.

The quarantined ranker output nevertheless remained available as a diagnostic:

- 62 complete ten-session decision groups;
- 53 accelerated selections and nine defense selections;
- no balanced, core or leveraged selections;
- top-two rate approximately 56.45%;
- median realized advantage approximately +0.77%;
- aggregate block-level advantage approximately +49.27 percentage points.

These figures do not authorize a strategy. They repeat the same extreme-action collapse and were not permitted to override the failed OOF regret, accuracy and concentration gates.

## Final interpretation

The experiment resolves the original question more precisely:

1. **The rule-based architecture is not the only bottleneck.** A nonlinear ranker can extract substantially more within-date action-order information than the simple v4.2 action comparator.
2. **XGBoost does identify real non-random structure.** It beats every deterministic placebo ranker and produces positive median advantage across three of four outer folds.
3. **The current terminal-return ranking target is structurally misaligned with a diversified state machine.** It naturally rewards 100% cash or 100% TQQQ and rarely makes intermediate states optimal.
4. **The remaining failure is economic, not merely statistical.** Regret reduction, top-two accuracy, 2022–2023 stability and feature concentration all fail.
5. **No evidence supports replacing v4.2.** Phase 2 was correctly skipped before any portfolio-selection conclusion.

## Decision boundary

Decision: `xgb_action_ranking_not_supported`.

- v4.23 is not a shadow or actionable model;
- no Phase 2 state-machine backtest is authorized from this contract;
- v4.2 remains the current research baseline and sole Telegram signal source;
- Issue #348 remains unchanged;
- do not reduce the regret or top-two gates;
- do not delete balanced, core or leveraged after observing their low selection frequency;
- do not convert the result into an accelerated-only or defense/accelerated binary strategy;
- do not retune XGBoost parameters, feature subsets, relevance labels, action weights or the ten-session horizon on the observed history;
- do not use the positive 2024+ block diagnostic to override the OOF failure.

## Retained research assets

- grouped action-context dataset and exact cost-aware rank labels;
- fixed XGBoost LambdaRank implementation;
- chronological outer-fold and placebo framework;
- gain and SHAP family-concentration audit;
- fail-closed two-stage runner that prevents portfolio construction after a ranking-gate failure;
- audited adjusted-open/close research data path;
- corrected ten-session embargo translation for a ten-session decision grid.

A future, separately preregistered experiment would require a target that explicitly values path risk or drawdown, rather than another modification of terminal-return action ranks. That is a new research question and cannot be inferred as a promoted solution from v4.23.
