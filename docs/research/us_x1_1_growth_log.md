# US x1.1 growth log

This log is the durable experiment ledger for the active US research baseline. It records successful, failed and null experiments. It does not imply trade readiness.

## Baseline

| Field | Value |
|---|---|
| Model | US x1.1 |
| Status | active research baseline |
| Parent | US x1.0 |
| Universe | `us_selected_equities_v2` |
| Benchmark | QQQ |
| Feature group | `momentum_volatility_volume` |
| Label / holding / rebalance | 10 / 10 / 10 sessions |
| Portfolio | Top-15 equal weight |
| Base cost | 20 bps |
| Effective XGBoost runtime | gain7, 200 rounds, max leaves 31, learning rate 0.05, seed 42 |
| Canonical provider identity | `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95` |
| Canonical workflow / artifact | `30737322468` / `8830089966` |
| Development relative excess vs QQQ | +110.44% |
| Worst development drawdown | -27.15% |
| Consumed reporting window | 2026H1 |

US x1.0 remains immutable historical evidence. US x1.1 remains `research_only=true` and `trade_ready=false`.

## Version rules

- Experiments never mutate US x1.1.
- A supported compatible improvement may become a reviewed **US x1.2 candidate**.
- A contract-breaking change requires US x2.0.
- The consumed 2026H1 window cannot select another candidate.
- A provider mismatch forces `data_blocked` for version promotion, even when comparative results are retained as noncanonical evidence.
- Null and negative results remain in this log.

## Experiment 001 — establish US x1.1

**Date:** 2026-08-02  
**Issues / PRs:** #350, #363, #365, #371  
**Decision:** Candidate A promoted to formal research baseline by user direction.

### Result

- 2024H1–2025H2 compounded relative excess vs QQQ: +110.44%.
- Positive-excess windows: 4/4.
- Mean ICIR: 0.2280.
- Mean Rank IC: 0.0410.
- Worst drawdown: -27.15%.
- Strongest positive-window share: 42.71%.
- AAOI, AEHR and BE appeared in every development final Top-15.

### Learning

The `momentum_volatility_volume` feature family improved broad-window balance relative to the latest US x1.0 evidence. The model still has meaningful drawdown and recurring-name concentration. Promotion changed the research baseline, not the trade-readiness status.

## Experiment 002 — native XGBoost identity contract

**Date:** 2026-08-02  
**Issue / PR:** #357 / #369  
**Decision:** implementation foundation accepted; no model change.

### Result

- Added explicit native fields for leaves/depth, child weight, learning rate, sampling, L1/L2 and seed.
- Unknown or ignored fields fail closed.
- Candidate names and SHA-256 identities contain all effective native parameters.
- Actual XGBoost fit and prediction tests proved parameter propagation.

### Learning

Historical PR #343/#344 candidate names included fields that were not consumed by XGBoost. Those experiments remain valid for factor group, gain-bin and round-count comparisons, but not for learning-rate or leaf-regularization attribution.

## Experiment 003 — six-candidate native XGBoost grid

**Status:** running through Issue #370.  
**Parent:** US x1.1.  
**Decision windows:** 2024H1, 2024H2, 2025H1, 2025H2.  
**Reporting-only window:** none in candidate selection; 2026H1 remains excluded.

### Hypothesis

Native regularization may reduce the 2025H1 drawdown or selection instability while retaining broad-window excess.

### Frozen fields

- universe, benchmark and feature group;
- label, holding and rebalance horizon;
- Top-15 equal-weight portfolio role;
- 20 bps base cost;
- score orientation;
- development windows.

### Pre-registered candidates

1. exact effective US x1.1 runtime;
2. learning rate 0.03 with 300 rounds;
3. minimum child weight 5;
4. row and column sampling at 0.8;
5. explicit L1/L2 regularization with child weight 2;
6. maximum leaves 15.

### Required outputs

- provider identity and manifest;
- effective parameter identity per candidate and window;
- 20/40/60 bps cost stress;
- score-rank correlation and final Top-15 overlap versus US x1.1;
- window contribution balance and recurring names;
- deterministic rerun check for the baseline calibration;
- one final decision: `native_xgb_x1_2_candidate_supported`, `us_x1_1_native_runtime_preferred`, `native_grid_unstable`, or `data_blocked`.

Results will be appended after the workflow artifact is reviewed.

## Active research queue

1. Complete native-grid evidence and decide whether any parameter candidate deserves x1.2 validation.
2. Build the governed US87 sector map under #366.
3. Execute the fixed-score portfolio variants under #362.
4. Decompose the 2025H1 drawdown and recurring-name contribution.
5. Reserve a genuinely untouched future challenge window before any operational claim.
