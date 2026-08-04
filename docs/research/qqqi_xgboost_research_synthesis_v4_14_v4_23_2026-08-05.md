# XGBoost research synthesis after v4.14-v4.23

Date: 2026-08-05

## Purpose

This note records the durable conclusions that govern the next XGBoost experiment. It is not a retrospective search for a better v4.23 parameter set.

## What the v4.x sequence established

### 1. Rule expressiveness was a real limitation, but not the only limitation

The static and transition-rule studies showed that fixed Boolean thresholds either generalized too broadly or became too sparse. However, the later Ridge, logistic, state-conditioned and state-specific models also failed. Therefore, replacing a rule engine with machine learning is not sufficient by itself.

### 2. New information exists, but representation and objectives matter

The complete credit/duration family admitted by v4.19 improved action ranking across eras. v4.20 preserved that gain, but failed magnitude calibration, event economics, turnover and portfolio gates. The signal was useful for relative ordering, not for estimating an absolute action advantage threshold.

### 3. v4.23 proved nonlinear information exists

The fixed XGBoost LambdaRank experiment achieved:

- NDCG@1 of 0.5453 versus 0.3061 for the frozen-v4.2 action comparator;
- +0.2391 NDCG improvement;
- positive selected-action median advantage;
- 3/4 positive outer folds;
- 20/20 deterministic placebo rankers beaten.

The result was therefore not a random-null failure.

### 4. v4.23 also proved terminal-return ranking was the wrong state-machine target

The ranker selected 100% TQQQ in 162/201 OOF blocks and 100% cash in 37/201. Bridge and leveraged were never selected, while core appeared only twice. Candidate-action descriptors supplied 73.49% of mean absolute SHAP and `candidate_qqq_weight` alone supplied 32.65%.

The target structurally rewarded convex endpoints. In the realized oracle labels, accelerated or defense was the best terminal-return action in 87.5% of blocks. The model learned a strong action prior rather than stable market timing across a risk-budget ladder.

### 5. Statistical ranking metrics can contradict economic execution

The 2022-2023 fold retained positive NDCG improvement while regret reduction and aggregate advantage turned negative. A model can rank relevance better and still make economically worse choices. Every future XGBoost experiment must therefore gate on path utility, regret, turnover, state coverage and portfolio outcomes, not only AUC or NDCG.

## New design principles

1. **Anchor to a risk topology.** Learn local transitions between adjacent risk states rather than globally rank convex endpoints.
2. **Remove static action priors.** Separate edge models receive market and frozen-v4.2 context only; they do not receive candidate action weights.
3. **Value the path, not only the endpoint.** Labels must penalize maximum adverse excursion in addition to terminal net return.
4. **Keep decisions independent.** Use the governed non-overlapping ten-session grid and audited ten-session embargo translation.
5. **Fail closed before portfolio claims.** Model, regret, state-diversity, placebo and concentration gates must all pass before any state-machine portfolio is constructed.
6. **Do not mine the v4.23 failure.** No cash/TQQQ binary extraction, action deletion, SHAP feature selection, probability-threshold search or parameter retuning is admissible.

## v4.24 hypothesis

A shallow XGBoost model may be useful if it learns three adjacent path-utility comparisons:

- defense versus bridge;
- bridge versus core;
- core versus controlled leverage.

The resulting ordinal policy advances through the risk ladder only when each adjacent higher-risk state has predicted path utility above the lower-risk state. This tests whether nonlinear factors can improve state timing without turning the problem into a historical bet on the most convex endpoint.

## Governance boundary

Historical success can authorize prospective shadow observation only. Frozen v4.2 remains the sole research baseline and alert source. Telegram and Issue #348 are unchanged.