# US x1.1 native XGBoost calibration plan

## Purpose

US x1.1 is now the active US research baseline. Its historical candidate identity contains LightGBM-oriented fields that were not passed into XGBoost. Before further parameter optimization, Alpha Engine needs a native calibration contract in which every declared field is consumed and recorded in the effective runtime manifest.

This work implements the first slice of Issue #357. It does not replace the shared Qlib execution path yet and does not change US x1.1.

## Native contract

`src/research/xgb_native_calibration.py` defines the complete bounded parameter surface:

- gain bins and boosting rounds;
- maximum leaves and maximum depth;
- minimum child weight;
- learning rate;
- row and column sampling;
- L1 and L2 regularization;
- seed.

The structural objective remains protected:

- `objective=rank:ndcg`;
- `tree_method=hist`;
- `grow_policy=lossguide`.

Unknown fields fail closed. Candidate names and SHA-256 identity manifests include every effective native parameter. Predictions carry the effective runtime parameters and identity hash in DataFrame metadata.

## Pre-registered grid

The first US x1.1 native grid contains six candidates:

1. exact effective US x1.1 baseline;
2. lower learning rate with more rounds;
3. higher minimum child weight;
4. row and column sampling;
5. explicit L1/L2 regularization;
6. lower leaf capacity.

Only 2024H1–2025H2 may select a candidate. The consumed 2026H1 window is reporting-only. Features, universe, label, horizon and portfolio role remain fixed.

## Selection priority

The experiment prioritizes:

1. positive excess in all development windows;
2. lower worst drawdown;
3. lower security and window concentration;
4. positive 60 bps compounded relative excess;
5. stable Rank IC and Top-15 overlap;
6. compounded relative excess.

At most one candidate may survive as a possible US x1.2 candidate. No automatic model update is allowed.

## Remaining integration work

Before Issue #357 can close, the native contract must be integrated into the shared paradigm and Qlib execution path:

- add separate `xgb_calibrations` and `lgbm_calibrations` schemas;
- materialize native candidates without legacy field translation;
- pass the native parameter mapping through `fit_ranker_scores`;
- retain per-window and final effective-parameter manifests;
- fail execution when declared and effective identities differ;
- preserve historical PR #343/#344 candidate IDs as legacy evidence.

The full grid will run only after this integration passes focused and repository-level CI.
