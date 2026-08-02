# US x1.1 growth log

This is the durable experiment ledger for the active US research baseline. It
records positive, negative, null and blocked results. It does not imply trade
readiness.

## Current baseline

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
| Canonical provider | `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95` |
| Canonical workflow / artifact | `30737322468` / `8830089966` |
| Development relative excess | +110.44% |
| Worst canonical development drawdown | -27.15% |
| Consumed reporting window | 2026H1 |

US x1.0 and canonical US x1.1 evidence remain immutable. US x1.1 remains
`research_only=true` and `trade_ready=false`.

## Governance rules

- Experiments never mutate US x1.1 in place.
- Provider identity is part of every model claim.
- Complete accepted evidence retains source and provider snapshots.
- Historical source revisions create new evidence revisions; they never replace
  canonical evidence silently.
- The consumed 2026H1 window cannot select another candidate.
- A compatible model improvement may become a reviewed US x1.2 candidate.
- A portfolio-control improvement remains separate from model versioning.
- Failed, blocked and null experiments remain recorded.

## Experiment ledger

### Experiment 001 — establish US x1.1

**Issues / PRs:** #350, #363, #365, #371  
**Decision:** establish Candidate A as the formal US x1.1 research baseline.

- compounded relative excess: +110.44%;
- positive windows: 4/4;
- mean ICIR: 0.2280;
- mean Rank IC: 0.0410;
- worst drawdown: -27.15%;
- recurring final Top-15 names: AAOI, AEHR and BE.

The model improved broad-window balance over US x1.0 but retained material
portfolio drawdown and recurring-name risk.

### Experiment 002 — native XGBoost identity contract

**Issue / PR:** #357 / #369  
**Decision:** implementation foundation accepted; no model change.

- native leaves, depth, child weight, learning rate, sampling, L1/L2 and seed
  are explicit;
- unknown or ignored fields fail closed;
- candidate and effective runtime identities are SHA-bound;
- actual XGBoost fitting tests prove parameter propagation.

Historical LightGBM-shaped candidate names are no longer treated as proof that
XGBoost consumed those fields.

### Experiment 003 — six-candidate native XGBoost grid

**Issue / PR:** #370 / #378  
**Decision:** `data_blocked`; no US x1.2 candidate.

Two successful model runs used different same-day provider snapshots:

| Run | Workflow / artifact | Provider |
|---|---|---|
| A | `30740184315` / `8831050347` | `a48bfc398b6207a0de1e38558f15caa4d096922572da2c78df636fc20aabf081` |
| B | `30740473510` / `8831147387` | `2238b2f7dc0130b536f70450992f1869a64cdbeab088623edf4eaeb59f8e6024` |

Stable learning across both snapshots:

- lower learning rate, row/column sampling and smaller leaf capacity increased
  return;
- no parameter candidate solved the deep drawdown;
- all candidates retained positive 60 bps excess;
- parameter ranking was provider-sensitive;
- row/column sampling remained exploratory only.

Full result:
`docs/research/us_x1_1_native_xgb_grid_result_2026-08-02.md`.

### Experiment 004 — full US87 provider A/B audit

**Issue / PR:** #358 / #384  
**Workflow / artifact:** `30741031977` / `8831306221`  
**Decision:** `unexplained_provider_drift_blocking`, narrowed to adjusted-price
floating recomputation.

- 41/88 source files were identical;
- 47/88 changed across hundreds of historical dates;
- dates, rows, volume and factor remained identical;
- OHLC changed proportionally within each date by sub-ppm amounts;
- coarse rounding failed to create a safe deterministic identity.

Provider generation was deterministic from fixed source CSVs. The unstable
layer was upstream adjusted source retrieval.

### Experiment 005 — Yahoo adjustment-mode isolation

**Issue / PR:** #386 / #388  
**Workflow / artifact:** `30741674075` / `8831499091`  
**Decision:** `bounded_subset_reproducible`.

Ten high-impact symbols were downloaded twice under adjusted+repair,
adjusted-no-repair and raw+Adj Close modes.

- all three modes reproduced 10/10 exactly;
- repair on/off was identical;
- raw OHLCV and Adj Close were identical;
- explicit adjustment matched yfinance auto-adjust within `1e-8`.

`repair=True` was not supported as the root cause. The remaining likely layer
was upstream historical adjustment snapshot timing or revision.

Detailed data audit record:
`docs/research/us_x1_1_data_reproducibility_experiments_2026-08-02.md`.

### Experiment 006 — deterministic raw-plus-adjustment contract

**Issue / PR:** #389 / #392  
**Workflow / artifact:** `30742690159` / `8831837784`  
**Decision:** `deterministic_raw_adjustment_contract_ready`.

Frozen identities:

| Layer | SHA-256 |
|---|---|
| Raw OHLCV + Adj Close snapshot | `3848fc1c474a408c67243b48d2c693bc7af531c3a6330069bd3e72bc609d19ad` |
| Formula | `004d92900c94f687c827bd1b17d8e7ac8e163ec57c4386a2bafe2482b6554c49` |
| Model-input tree | `1653a3d5ee0efdbed486aa1ac998ff9ff42baab15b9f09659bf443c41072f939` |
| Qlib provider | `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95` |

Two independent materializations from the same raw snapshot matched exactly.
The contract now retains raw OHLCV and Adj Close separately, derives adjusted
prices through `us_raw_adjustment_v1`, and blocks any rewrite of a frozen
historical prefix.

Full result:
`docs/research/us_raw_adjustment_contract_result_2026-08-02.md`.

### Experiment 007 — deterministic US x1.1 reproduction

**Issue / PR:** #393 / #394  
**Workflow / artifact:** `30743067256` / `8831960659`  
**Decision:** `us_x1_1_deterministic_on_revision_provider`.

US x1.1 was fitted independently twice on provider `5c09d0...`. All four
windows matched exactly on:

- effective parameter identity;
- complete scores;
- ranks;
- per-rebalance Top-15 selections;
- raw returns;
- 20/40/60 bps economics.

Revision-provider result:

| Metric | Canonical | Deterministic revision |
|---|---:|---:|
| Relative excess, 20 bps | +110.44% | +113.35% |
| Worst drawdown | -27.15% | -33.88% |
| Mean ICIR | 0.2280 | 0.2599 |
| Mean Rank IC | 0.0410 | 0.0459 |

Execution became reproducible, but the data revision materially worsened risk.
Canonical US x1.1 therefore remained unchanged.

Full result:
`docs/research/us_x1_1_deterministic_reproduction_result_2026-08-02.md`.

### Experiment 008 — 2025H1 drawdown attribution Phase A

**Issue / PR:** #381 / #395  
**Workflow / artifact:** `30743901477` / `8832228801`  
**Decision:** `portfolio_control_path_supported`.

The attribution engine first reproduced Experiment 007 exactly. Complete model
scores were explicitly intersected with non-null raw 10-session returns before
ranking, preserving both score identities.

Drawdown path:

- peak: 2025-02-03;
- trough: 2025-04-01;
- maximum drawdown: -33.88%;
- no recovery within 2025H1.

Mechanism findings:

- APP, HIMX and TEM were the three largest negative names, but represented only
  24.65% of total negative contribution;
- excluding APP improved drawdown by only 1.56 percentage points;
- loss was broad across volatility buckets;
- low-beta contribution was worse than high-beta;
- negative QQQ-trend periods represented 52.72% of negative contribution;
- the initial -21.07% shock occurred while the QQQ trend was still positive.

Independent portfolio controls:

| Control | Excess | Max DD | Outcome |
|---|---:|---:|---|
| Baseline | +5.54% | -33.88% | baseline |
| Top-20 equal | +1.74% | -33.92% | fail |
| Inverse vol, 10% cap | +7.24% | -33.39% | fail drawdown gate |
| Equal Top-15, 8% cap | +5.54% | -33.88% | mechanically null |
| QQQ negative 20D trend, 50% gross | +7.62% | -27.66% | pass |

The drawdown was not dominated by one name, high volatility or high beta. The
trend overlay could not prevent the initial shock, but materially reduced the
continuation phase.

Full result:
`docs/research/us_x1_1_drawdown_attribution_phase_a_result_2026-08-02.md`.

## Current research queue

1. **#396 — multi-window QQQ trend overlay validation.** Compare baseline,
   50% gross and cash under negative QQQ 20D trend across 2024H1–2025H2 and
   20/40/60 bps.
2. **#366 — governed US87 sector map.** Complete exact 87/87 source-bound
   mapping before sector attribution, sector cap or leave-one-sector-out.
3. **#381 Phase B.** Add sector contribution and concentration evidence after
   #366; retain Phase A name and regime conclusions.
4. **#362.** Reconcile the original portfolio-control issue with Phase A and
   #396; close rejected controls and retain only supported contracts.
5. Revisit native parameter challengers only after portfolio-risk controls are
   resolved.
6. Reserve a genuinely untouched future challenge window before any
   operational claim.

## Current conclusion

US x1.1 has not become US x1.2. Its model execution and data contract are now
reproducible, its 2025H1 drawdown has been decomposed, and one bounded portfolio
control merits multi-window validation. The active task is risk-contract
validation, not another blind parameter search.
