# US x1.1 growth log

**Ledger status:** current through Experiment 012 on 2026-08-03.

This is the durable cumulative experiment ledger for the active US research
baseline. It records positive, negative, null and blocked results. Detailed
ledgers remain in the linked result documents and workflow artifacts. Nothing in
this file implies trade readiness.

## Current baseline and active challenger

| Field | Value |
|---|---|
| Active model | US x1.1 |
| Model status | active research baseline |
| Parent | US x1.0 |
| Candidate universe | fixed `us_selected_equities_v2`, 87 equities |
| Benchmark | QQQ |
| Feature group | `momentum_volatility_volume` |
| Label / holding / rebalance | 10 / 10 / 10 sessions |
| Baseline portfolio | Top-15 equal weight |
| Base cost | 20 bps |
| Effective XGBoost runtime | gain7, 200 rounds, max leaves 31, learning rate 0.05, seed 42 |
| Canonical provider | `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95` |
| Canonical workflow / artifact | `30737322468` / `8830089966` |
| Canonical development relative excess | +110.44% |
| Worst canonical development drawdown | -27.15% |
| Deterministic revision provider | `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95` |
| Consumed reporting window | 2026H1 |
| Active portfolio-control challenger | rank-aware Top-15 sector cap, max four names per sector |
| Challenger status | supported for frozen shadow validation only |

US x1.0 and canonical US x1.1 evidence remain immutable. US x1.1 remains
`research_only=true` and `trade_ready=false`. The sector-cap challenger is a
separate portfolio contract; it is not US x1.2.

## Governance rules

- Experiments never mutate US x1.1 in place.
- Provider identity is part of every model claim.
- Complete accepted evidence retains source and provider snapshots.
- Historical source revisions create new evidence revisions; they never replace
  canonical evidence silently.
- Source-model selection identity and economic-selection identity are retained
  separately when raw forward-return availability changes the eligible cross
  section.
- The fixed US87 pool is the research domain; no pool-external generalization is
  claimed or tested.
- The consumed 2026H1 window cannot select or tune another candidate.
- A compatible model improvement may become a reviewed US x1.2 candidate.
- A portfolio-control improvement remains separate from model versioning.
- Failed, blocked and null experiments remain recorded.
- Passing consumed development evidence only permits shadow validation.
- Any change to the sector ceiling, classification, exception list, Top-15 rule
  or rebalance contract restarts the future challenge clock.

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

| Layer | SHA-256 |
|---|---|
| Raw OHLCV + Adj Close snapshot | `3848fc1c474a408c67243b48d2c693bc7af531c3a6330069bd3e72bc609d19ad` |
| Formula | `004d92900c94f687c827bd1b17d8e7ac8e163ec57c4386a2bafe2482b6554c49` |
| Model-input tree | `1653a3d5ee0efdbed486aa1ac998ff9ff42baab15b9f09659bf443c41072f939` |
| Qlib provider | `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95` |

Two independent materializations from the same raw snapshot matched exactly.
The contract retains raw OHLCV and Adj Close separately, derives adjusted
prices through `us_raw_adjustment_v1`, and blocks any rewrite of a frozen
historical prefix.

Full result:
`docs/research/us_raw_adjustment_contract_result_2026-08-02.md`.

### Experiment 007 — deterministic US x1.1 reproduction

**Issue / PR:** #393 / #394  
**Workflow / artifact:** `30743067256` / `8831960659`  
**Decision:** `us_x1_1_deterministic_on_revision_provider`.

US x1.1 was fitted independently twice on provider `5c09d0...`. All four
windows matched exactly on effective parameters, complete scores and ranks,
daily Top-15 source selections, raw returns and 20/40/60 bps economics.

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

The attribution engine first reproduced Experiment 007 exactly. Source-model
scores and daily selections were retained separately from the economic score
and selection layer after non-null raw forward-return alignment.

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
- negative QQQ-trend periods represented 52.72% of negative contribution;
- the initial -21.07% shock occurred while the QQQ trend was still positive.

Independent controls:

| Control | Excess | Max DD | Outcome |
|---|---:|---:|---|
| Baseline | +5.54% | -33.88% | baseline |
| Top-20 equal | +1.74% | -33.92% | fail |
| Inverse vol, 10% cap | +7.24% | -33.39% | fail drawdown gate |
| Equal Top-15, 8% cap | +5.54% | -33.88% | mechanically null |
| QQQ negative 20D trend, 50% gross | +7.62% | -27.66% | advance to multi-window test |

Full result:
`docs/research/us_x1_1_drawdown_attribution_phase_a_result_2026-08-02.md`.

### Experiment 009 — multi-window QQQ trend overlay

**Issue / PR:** #396 / #400  
**Workflow / artifact:** `30745446452` / `8832729580`  
**Artifact digest:** `sha256:f58853fb4d6da2d722b63049ee25495649270a5b935b9837fcd4cf3d4cece740`  
**Decision:** `trend_overlay_destroys_too_much_upside`.

| Contract | Relative excess | Retained baseline excess | Worst DD | Positive windows | Average gross |
|---|---:|---:|---:|---:|---:|
| Baseline 100% | +113.35% | 100.00% | -33.88% | 4/4 | 100.0% |
| QQQ-negative 50% | +86.91% | 76.68% | -27.66% | 4/4 | 87.5% |
| QQQ-negative cash | +60.93% | 53.75% | -21.15% | 3/4 | 75.0% |

The overlay controlled the continuation phase of the 2025H1 drawdown but
materially destroyed upside elsewhere. Neither fixed overlay became a portfolio
contract. The same trend lookback or threshold must not be tuned on these
consumed windows.

Full result:
`docs/research/us_x1_1_qqq_trend_overlay_result_2026-08-02.md`.

### Experiment 010 — QQQ beta-residual target

**Issue / PR:** #422 / #425  
**Workflow / artifact:** `30776268639` / `8842169424`  
**Artifact digest:** `sha256:ba0489194946b59293c4b609b36a752a7a5a72d7f54fe1a38356418e4980333a`  
**Decision:** `beta_residual_adds_no_value`.

The experiment kept the fixed US87 pool, features, XGBoost runtime, windows and
portfolio contract unchanged. It replaced the raw ten-session target with a
stock-specific QQQ beta-residual target using trailing 60-session beta with at
least 40 paired observations.

A naive `stock return - QQQ return` control proved exactly rank-equivalent to
the raw target under the daily cross-sectional ranker and therefore was not a
new model.

On the beta-compatible comparison sample:

| Metric | Raw-target baseline | Beta-residual target |
|---|---:|---:|
| 20 bps strategy return | +239.76% | +193.69% |
| 20 bps relative excess | +118.92% | +89.24% |
| Worst drawdown | -38.77% | -38.26% |
| Mean selected beta | 1.854 | 1.893 |

The challenger materially changed rankings but retained only 75.04% of baseline
relative excess, failed to lower beta, worsened QQQ-down performance and
increased window concentration. The target path is closed; US x1.1 remains
unchanged.

### Experiment 011 — governed sector, style and 2025H1 mechanism attribution

**Issues / PR:** #366, #381 / #430  
**Workflow / artifact:** `30778065622` / `8842736844`  
**Artifact digest:** `sha256:7b577b7c0147bbc11cd04c27374f77f82f7580f454dcfe4c142abd7ac2dd093b`  
**Decision:** `mixed_sector_style_regime`.

The run added an immutable 87/87 governed sector and industry map, point-in-time
market-style snapshots and complete sector/style contribution ledgers.

2025H1 mechanism findings:

- maximum sector weight: 86.67%;
- Technology share of negative contribution: 70.26%;
- high-volatility share of negative contribution: 87.98%;
- high-beta share of negative contribution: 83.73%;
- QQQ negative-trend loss share: 52.72%, below the regime-dominance gate;
- the drawdown was not dominated by one name or one narrow industry.

The most accurate interpretation is a broad high-beta/high-volatility Technology
selection shock amplified by sector concentration. A corrected rank-aware
sector-cap diagnostic warranted an independently pre-registered portfolio
experiment; no model or portfolio contract was updated in this attribution run.

Full result:
`docs/research/us_x1_1_sector_style_attribution_result_2026-08-03.md`.

### Experiment 012 — rank-aware US87 sector cap

**Issue / PR:** #432 / #433  
**Workflow / artifact:** `30779386691` / `8843152145`  
**Artifact digest:** `sha256:9ced02f9329d7c955a6166ee0303bf523c0a7e030fb9b7d8ea8a7f0a2bb4e3fc`  
**Decision:** `rank_aware_sector_cap_supported_for_shadow`.

The challenger scans the complete US x1.1 ranking, selects exactly 15 equal
weight names, and admits no more than four names from one governed sector. All
other model, data, score, return, cost and timing contracts remain frozen.

Aggregate canonical economics:

| Contract | Cost | Strategy return | Relative excess | Worst DD | Turnover | Strongest-window share |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 20 bps | +231.11% | +113.35% | -33.88% | 25.67 | 48.72% |
| Sector cap | 20 bps | **+242.76%** | **+120.85%** | **-29.36%** | **22.53** | **32.91%** |
| Sector cap | 60 bps | +213.82% | +102.21% | -29.93% | 22.53 | 33.52% |

Every pre-registered development gate passed:

- 4/4 positive simple-excess windows;
- positive 60 bps compounded relative excess;
- 106.62% baseline relative-excess retention;
- +4.52 percentage-point worst-drawdown improvement;
- turnover at 87.79% of baseline;
- strongest positive-window share below 55%;
- exact two-run materialization identity.

The result is not uniformly superior. In 2025H2 the challenger returned 24.91%
versus 60.13% for baseline and worsened drawdown from -19.38% to -26.07%. It
frequently removed high-ranked Technology winners such as ALAB, IREN, SNDK,
AEHR, LITE and MU. Mean Top-15 overlap was 61.81%, with 5.73 replacements per
rebalance and a maximum selected rank of 46.

The contract therefore advances only to frozen prospective shadow validation.
It does not replace US x1.1, create US x1.2 or establish trade readiness.

Full result:
`docs/research/us_x1_1_rank_aware_sector_cap_result_2026-08-03.md`.

## Current research queue

1. Freeze the Experiment 012 sector-cap contract and begin prospective shadow
   evidence from the first eligible rebalance after 2026-08-03.
2. Retain baseline and challenger signals before outcomes exist, with hashes,
   selections, replacement pairs, expected turnover and data/provider identity.
3. Do not use 2026H1 or the consumed 2024H1–2025H2 development windows to tune
   the four-name sector ceiling, classification or exception rules.
4. Reserve an untouched six-month shadow challenge before any acceptance or
   operational claim.
5. Close #362 portfolio-control governance using the cumulative evidence:
   Top-20, inverse volatility, 8% name cap and fixed QQQ overlays are rejected or
   null; the rank-aware sector cap is the only supported shadow path.
6. Do not resume broad model-parameter search until prospective portfolio-risk
   evidence is available.

## Current conclusion

US x1.1 remains the active fixed-US87 research baseline. Its deterministic data
and execution contract are reproducible, the 2025H1 drawdown mechanism is now
understood, the beta-residual target and fixed QQQ overlays are rejected, and a
rank-aware sector-cap portfolio control has passed consumed development gates.

The next research phase is prospective shadow validation of the frozen
sector-cap contract. No US x1.2 candidate exists and nothing is trade ready.
