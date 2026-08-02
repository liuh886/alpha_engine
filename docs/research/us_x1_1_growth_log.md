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
- A provider mismatch forces `data_blocked` for version promotion.
- Accepted evidence must retain the full provider snapshot, not only its manifest.
- Null, negative and non-reproducible results remain in this log.

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
**Decision:** `data_blocked`  
**Version consequence:** no US x1.2 candidate; US x1.1 unchanged.

### Evidence runs

| Run | Workflow / artifact | Digest | Provider | Replayable provider included |
|---|---|---|---|---|
| A | `30740184315` / `8831050347` | `sha256:31c5c05297bade69bb730f3df7815f043f390e2de59674db3bff151fd71d6776` | `a48bfc398b6207a0de1e38558f15caa4d096922572da2c78df636fc20aabf081` | no |
| B | `30740473510` / `8831147387` | `sha256:67300e7d86876cd31110db9f00060b8c20a241cba93e38a7178f58eb08851e87` | `2238b2f7dc0130b536f70450992f1869a64cdbeab088623edf4eaeb59f8e6024` | yes, 621 files |

Neither provider matches canonical US x1.1. Run B is the retained replayable evidence snapshot.

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

### Reproducibility result

Model fitting was deterministic within both provider snapshots. The effective US x1.1 calibration reproduced identical scores when fitted twice in each window.

Provider refresh was not deterministic:

- Run A and Run B had identical calendars and 88-instrument contracts;
- provider identity changed again within the same day;
- 47 of 88 source CSV hashes changed between full refreshes;
- candidate economic rankings changed materially.

### Result range across the two snapshots

| Calibration | Relative excess range, 20 bps | Worst drawdown range | Stable conclusion |
|---|---:|---:|---|
| US x1.1 effective runtime | 85.07%–114.35% | -34.11% to -33.84% | strong excess; deep risk |
| Lower learning rate / 300 rounds | 169.92%–172.96% | -39.29% to -37.35% | stable return uplift; worse tail risk |
| Higher child weight | 113.15%–162.08% | -38.56% to -32.19% | materially provider-sensitive |
| Row and column sampling 0.8 | 135.80%–164.19% | -35.01% to -33.71% | return uplift; no stable risk improvement |
| Explicit regularization | 119.93%–137.45% | -36.61% to -34.94% | no drawdown solution |
| Maximum leaves 15 | 162.09%–177.10% | -35.53% to -35.28% | stable return uplift; worse risk |

Every candidate retained positive 60 bps relative excess in both runs. No challenger passed the drawdown gate in either run.

### Accepted learning

- Native XGBoost fields create genuinely different score and economic contracts.
- Model fitting is deterministic on a frozen provider.
- Lower learning rate, sampling and lower leaf capacity expose repeatable return uplift directions.
- Parameter return rankings remain too provider-sensitive for candidate selection.
- Parameter tuning alone does not solve the 2025H1 regime drawdown.
- Full provider retention is now mandatory.
- Data reproducibility is the first hard gate for x1.1 growth.

### Rejected learning

- No candidate may be called US x1.2.
- Neither experimental run restates canonical US x1.1.
- No single challenger is retained as uniquely preferred based on these runs.
- Higher return cannot justify promotion while drawdown and source reproducibility fail.

### Next action

- use replayable Run B for mechanism-level attribution only;
- continue source/provider drift work under #358;
- execute 2025H1 drawdown attribution under #381;
- complete the governed sector map under #366;
- test fixed-score portfolio controls under #362 before widening the parameter grid.

Full result: `docs/research/us_x1_1_native_xgb_grid_result_2026-08-02.md`.

## Active research queue

1. Make the US provider refresh snapshot-reproducible and close the #358 data gate.
2. Build the governed US87 sector map under #366.
3. Attribute the 2025H1 drawdown under #381 using the frozen Run B provider.
4. Execute the independent fixed-score portfolio variants under #362.
5. Revisit parameter challengers only after data and portfolio-risk gates are resolved.
6. Reserve a genuinely untouched future challenge window before any operational claim.
