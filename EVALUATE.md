> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Evaluation Log

## 2026-08-11: USx Iteration — XGBoost Native Calibration Grid

### Experiment: us_x1_1_native_xgb_grid_v1

**Status**: Completed (evidence generated, decision blocked on provider mismatch)

**Setup**:
- Parent: US x1.1 (XGBoost rank:ndcg, 7 OHLCV factors, Top-15 equal-weight, 10D horizon)
- Provider: local `data/providers/us` (132 instruments, identity differs from canonical)
- Windows: 2024H1, 2024H2, 2025H1, 2025H2 (complete windows only)
- 2026H1 excluded as consumed reporting window
- 6 calibrations tested

**Key Result**: The `row_and_column_sampling` calibration (subsample=0.8, colsample_bytree=0.8) improves compounded development excess by ~10pp (+109.75% vs +99.87%), achieves better diversification (strongest_window_share 0.43 vs 0.49), and eliminates BE from recurring Top-15 names. However, it does not improve worst drawdown (-29.10% vs -28.40%), falling short of the 3pp gate.

### Per-Calibration Summary (20bps cost, development windows compounded)

| Calibration | Excess | Worst DD | Rank IC | ICIR | Strongest Share | Recurring Names |
|---|---|---|---|---|---|---|
| baseline (x1_1) | +99.87% | -28.40% | 0.0449 | 0.235 | 0.489 | AAOI, AEHR, BE, IREN, TYGO |
| lower_lr_more_rounds | +96.36% | -28.86% | 0.0471 | 0.243 | 0.502 | AAOI, AEHR, IREN |
| higher_child_weight | +105.76% | -28.17% | 0.0436 | 0.229 | 0.472 | AAOI, IREN, TYGO |
| **row_and_column_sampling** | **+109.75%** | -29.10% | 0.0453 | 0.242 | **0.430** | AAOI, AEHR, HOOD, IREN, TYGO |
| regularized | +94.39% | -29.24% | 0.0455 | 0.240 | 0.447 | AAOI, AEHR, IREN, TYGO |
| lower_leaf_capacity | +114.64% | -29.05% | 0.0448 | 0.231 | 0.426 | AAOI, AEHR, BE, TYGO |

### Gate Analysis

All 5 challengers fail the same gate:
- `drawdown_improves_3pp_or_stays_above_minus_22pct`: FAIL (baseline DD is -28.40%, challengers range -28.17% to -29.24%)

All 5 challengers pass:
- `four_positive_excess_windows`: PASS
- `positive_60_bps_relative_excess`: PASS
- `retain_at_least_90pct_baseline_relative_excess`: PASS
- `mean_rank_ic_not_materially_weaker`: PASS
- `strongest_window_share_below_55pct`: PASS

### Per-Window: Baseline vs Best Challenger

| Window | Baseline Excess | Baseline DD | Challenger Excess (row+col) | Challenger DD | Delta |
|---|---|---|---|---|---|
| 2024H1 | +8.89% | -3.57% | +13.81% | -3.14% | +4.92pp |
| 2024H2 | +25.43% | -16.23% | +31.85% | -16.52% | +6.42pp |
| 2025H1 | +9.93% | -28.40% | +7.49% | -29.10% | -2.44pp |
| 2025H2 | +42.43% | -13.87% | +40.00% | -12.86% | -2.43pp |

The challenger improves early-window performance but trades off late-window performance.

### Design Implications

1. XGBoost calibration tuning alone cannot fix the structural drawdown problem. The -28% DD in 2025H1 is driven by factor/sector concentration, not model fitting.
2. The `row_and_column_sampling` calibration with subsample=0.8, colsample_bytree=0.8 is the recommended baseline for US x1.2 experiments due to better diversification and improved excess.
3. Sector cap (max 4 names per sector) remains the most promising drawdown mitigation vector but requires score ledger availability.
4. Provider refresh is needed to align local and canonical evidence for formal promotion.

### Next Steps

1. Refresh US provider data to include ALAB, HIMS, SNDK, TIGO and match canonical identity
2. Run sector cap experiment (`us_x1_1_rank_aware_sector_cap_v1`) with deterministic reproduction
3. Combine `row_and_column_sampling` calibration with sector cap in a unified US x1.2 candidate
4. Reserve 2026H2 as the untouched challenge window for final candidate evaluation
