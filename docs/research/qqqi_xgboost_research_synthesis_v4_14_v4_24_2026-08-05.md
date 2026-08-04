# XGBoost research synthesis through v4.24

Date: 2026-08-05

## Executive conclusion

The v4.x evidence no longer supports the idea that v4.2 is difficult to beat mainly because it is rule based. Nonlinear models can extract some real statistical structure, but the economic result depends more strongly on the target, action topology and information set.

Two complementary XGBoost experiments establish the current boundary:

- v4.23 found strong non-random terminal-return ranking information, but the target structurally collapsed to 100% TQQQ or 100% cash and did not learn a stable multi-state allocation machine.
- v4.24 removed action descriptors, preserved all intermediate states, used adjacent transitions and added a maximum-adverse-excursion penalty. Once the static action prior was removed, the current daily market and credit/duration features failed to predict local path utility out of sample.

The remaining problem is therefore not primarily XGBoost capacity. It is a shortage of stable, independent information about future path risk.

## Durable lessons from v4.14-v4.22

1. Static Boolean rules generalized too broadly; transition rules became too sparse.
2. Ridge, logistic, state-conditioned and state-specific models also failed, proving that model family alone was not the bottleneck.
3. The complete credit/duration block added cross-era ranking information, but did not support return-magnitude calibration or an executable threshold policy.
4. Intraday opening information did not identify the worst state-2 tail days and sacrificed the recovery convexity that drives v4.2.
5. v4.2 is strong because it combines slow trend persistence, conservative transition rules and sustained participation in convex upside. Many overlays improve local classification while destroying compounding through false defensive exits.

## v4.23: nonlinear information existed, but the target was structurally wrong

The grouped LambdaRank experiment used five candidate allocations and terminal ten-session net return relevance.

Positive evidence:

- observed NDCG@1: 0.5453;
- frozen-v4.2 action comparator NDCG@1: 0.3061;
- improvement: +0.2391;
- 20/20 deterministic placebo rankers beaten;
- positive median selected-action advantage;
- three of four outer folds positive.

Failure mechanism:

- 162/201 OOF selections were 100% TQQQ;
- 37/201 were 100% cash;
- bridge and controlled leverage were never selected;
- candidate-action descriptors supplied 73.49% of mean absolute SHAP;
- the largest single action descriptor supplied 32.65%;
- regret improved only 9.65%, and top-two accuracy was 55.22%;
- 2022-2023 produced negative economic regret improvement despite positive NDCG improvement.

Interpretation: terminal-return ranking across convex allocations rewards endpoint actions. The model learned a historical action prior, not robust state timing.

## v4.24: path-aware adjacent transitions removed the prior but exposed no stable signal

### Design correction

v4.24 replaced the five-action global ranking target with:

- four ordered states: defense, bridge, core and controlled leverage;
- three independent adjacent edge classifiers;
- 35 market, credit/duration and frozen-v4.2 context features;
- no candidate-action descriptors;
- path utility equal to terminal net return plus 0.50 times maximum adverse excursion;
- deterministic sequential traversal at probability 0.50.

The first artifact reused v4.23 `min_child_weight=20` on one-row-per-date edge models. The first two folds produced constant probabilities in all six edge cells. That artifact was rejected as implementation-incompatible. The parameter was mechanically scaled by row geometry from 20 to 4, preserving the v4.23 per-decision regularization scale. No economic result informed the scaling.

### Audited final result

- 18/18 manifest hashes verified;
- 201 OOF decision blocks;
- 12/12 fold-edge cells produced non-constant probabilities;
- source data through 2026-08-04;
- Phase 2 correctly skipped.

Model evidence:

| Metric | Result |
|---|---:|
| Mean edge AUC | 0.4883 |
| Minimum edge AUC | 0.4624 |
| Mean balanced accuracy | 0.4966 |
| Utility-regret reduction vs v4.2 | -17.34% |
| Top-two utility rank | 48.76% |
| Positive outer folds | 1/4 |
| Placebo beat rate | 30% |
| Total OOF utility advantage vs v4.2 | -129.63% |

Edge AUC:

- defense versus bridge: 0.4624;
- bridge versus core: 0.4834;
- core versus leveraged: 0.5191.

The model selected all four states and avoided v4.23's endpoint collapse:

- defense: 55 blocks;
- bridge: 19;
- core: 49;
- leveraged: 78.

However, broader state coverage did not improve correctness. Selected-state regret was worse than frozen v4.2, only the 2016-2017 fold was positive, and 2024+ quarantine evidence also showed negative utility advantage and regret deterioration.

SHAP concentration was healthy rather than collapsed:

- largest single feature share: 10.48%;
- largest family share: 28.57%;
- credit/duration: 28.57%;
- QQQ price path: 25.20%;
- relative strength: 23.19%;
- volatility: 19.15%;
- v4.2 context: 3.89%.

This matters because the negative result is not explained by one dominant feature or static action descriptor. The models used a diversified feature set and still failed out of sample.

## Combined diagnosis

### What XGBoost can do on the current information set

- detect broad historical action priors;
- fit nonlinear relationships inside development samples;
- distribute importance across price, volatility, relative-strength and credit features;
- produce meaningful diagnostics and falsifiable state-machine tests.

### What it has not demonstrated

- stable prediction of local ten-session path utility;
- reliable identification of defense, bridge, core and leverage transitions;
- positive economic regret improvement over v4.2;
- consistency after 2019;
- an executable policy that survives the actual 2024+ window.

### Why another model architecture is not the immediate answer

v4.23 and v4.24 bracket the problem:

- allowing action descriptors creates strong ranking statistics but mostly learns convex endpoint priors;
- removing action descriptors and asking for path-aware local timing removes that apparent edge.

A deeper tree, different threshold, changed MAE coefficient, feature subset or state deletion would now be retrospective model mining on the same information set.

## Research boundary after v4.24

Closed retrospective directions:

- XGBoost parameter search on the existing 35 daily features;
- changing the 0.50 path-risk penalty;
- changing the ten-session horizon;
- probability-threshold search;
- selecting only the core-versus-leveraged edge because its pooled AUC was slightly above 0.50;
- removing defense or bridge after observing weak performance;
- resurrecting a cash/TQQQ binary policy;
- SHAP-based feature deletion;
- deeper trees or a new booster on the same labels and history.

The next admissible XGBoost study must add genuinely new information that is available before the decision close. Candidate families include option skew and tail pricing, dealer/option positioning proxies, market breadth with survivorship-safe constituent data, or credit-spread levels unavailable from simple ETF ratios. Data coverage and source admissibility must be established before any new outcome calculation.

## Operating decision

Frozen v4.2 remains the only research baseline and Telegram signal source. Neither v4.23 nor v4.24 authorizes shadow positions, direct promotion or alert changes. Issue #348 remains the active prospective evidence program.