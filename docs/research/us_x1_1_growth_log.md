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

**Date:** 2026-08-02  
**Issue / PR:** #370 / #378  
**Workflow / artifact:** `30740184315` / `8831050347`  
**Artifact digest:** `sha256:31c5c05297bade69bb730f3df7815f043f390e2de59674db3bff151fd71d6776`  
**Decision:** `data_blocked`  
**Version consequence:** no US x1.2 candidate; US x1.1 unchanged.

### Hypothesis

Native regularization may reduce the 2025H1 drawdown or selection instability while retaining broad-window excess.

### Frozen fields

- universe, benchmark and feature group;
- label, holding and rebalance horizon;
- Top-15 equal-weight portfolio role;
- 20 bps base cost;
- score orientation;
- development windows 2024H1–2025H2.

The consumed 2026H1 reporting window was not loaded.

### Provider identity

- canonical US x1.1 provider: `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95`;
- observed provider: `a48bfc398b6207a0de1e38558f15caa4d096922572da2c78df636fc20aabf081`;
- provider match: false;
- calendar and instrument hashes: unchanged;
- changed source CSV hashes: 47 of 88.

This is source-data drift rather than a metadata-only change. Comparative results are retained as a noncanonical evidence revision, but cannot support a version decision.

### Result

Compounded relative excess versus QQQ on the observed provider:

| Calibration | 20 bps | 60 bps | Positive windows | Worst drawdown | Strongest-window share |
|---|---:|---:|---:|---:|---:|
| US x1.1 effective runtime | 114.35% | 94.07% | 4/4 | -33.84% | 47.82% |
| Lower learning rate / 300 rounds | **172.96%** | **147.35%** | 4/4 | **-39.29%** | 45.53% |
| Higher child weight | 113.15% | 93.21% | 3/4 | -38.56% | 50.16% |
| Row and column sampling 0.8 | **164.19%** | **140.63%** | 4/4 | -33.71% | **41.86%** |
| Explicit regularization | 119.93% | 98.62% | 3/4 | -36.61% | 53.58% |
| Maximum leaves 15 | **162.09%** | **139.30%** | 4/4 | -35.53% | 47.06% |

The deterministic repeat-fit check for the effective US x1.1 calibration passed in all four windows.

### Gate result

No challenger passed the drawdown gate. Every challenger needed either a three-percentage-point drawdown improvement or a worst drawdown above -22%.

- lower learning rate generated the highest return, but worsened worst drawdown to -39.29%;
- row/column sampling generated strong return and the best window balance, but improved drawdown by only 0.13 percentage point on the observed provider;
- higher child weight and explicit regularization produced negative excess in 2025H1;
- lower leaf capacity improved return but worsened drawdown.

### Accepted learning

- Native XGBoost fields now create genuinely different score and economic contracts.
- Nearby calibrations preserve positive 60 bps relative excess; transaction costs are not the central weakness.
- Lower learning rate, sampling and smaller leaf capacity expose substantial return upside.
- Parameter regularization alone does not solve the 2025H1 regime drawdown.
- Row/column sampling is the most useful exploratory challenger because it improved return and window balance while retaining 90% mean final Top-15 overlap with US x1.1.

### Rejected learning

- No candidate may be called US x1.2 from this run.
- Higher return does not establish a superior baseline when tail risk deteriorates.
- These metrics do not restate canonical US x1.1 because the provider changed.

### Next action

- retain row/column sampling as an exploratory challenger only;
- prioritize provider reproducibility and full provider artifact retention;
- proceed to fixed-score portfolio and concentration controls rather than expanding the parameter grid;
- use the same drawdown attribution framework on US x1.1 and the sampling challenger after the data gate is resolved.

Full result: `docs/research/us_x1_1_native_xgb_grid_result_2026-08-02.md`.

## Active research queue

1. Preserve full provider snapshots in future evidence artifacts and continue drift attribution under #358.
2. Build the governed US87 sector map under #366.
3. Execute the fixed-score portfolio variants under #362.
4. Decompose the 2025H1 drawdown and recurring-name contribution for US x1.1.
5. Revisit row/column sampling only after the data and portfolio-risk gates are resolved.
6. Reserve a genuinely untouched future challenge window before any operational claim.
