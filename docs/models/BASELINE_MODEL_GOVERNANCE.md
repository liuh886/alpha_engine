# Baseline model lifecycle

## Purpose

Alpha Engine uses named, immutable model contracts for governed research. A model version binds the universe, feature and label contract, effective runtime, portfolio construction, cost convention and evidence lineage. Research-baseline promotion changes the default governed comparison model; it does not by itself authorize trading.

## Active baselines

| Market | Active model | Universe | Benchmark | Core contract | Status |
|---|---|---|---|---|---|
| US | **US x1.2** | `us_selected_equities_v2` | QQQ | 7 OHLCV factors; XGBoost 200 rounds, lr 0.05, row/column sampling 0.8; Top-15 equal weight; max 4 names/sector | active research baseline |
| CN | **CN x1.1** | governed CN130 pool | CSI 300 | regime-gated sector breadth | accepted formal research baseline |

US x1.0 and US x1.1 remain immutable historical baselines. US x1.1 is superseded by US x1.2 for new US research. All named x1 models remain `research_only=true` and `trade_ready=false` unless a later explicit release contract states otherwise.

## US x1.2 promotion — 2026-08-11

US x1.2 promotes the corrected-certification winner `r11_sampled` under explicit user direction. The certification compared three bounded sector-cap routes against the uncapped effective US x1.1 baseline using actual portfolio-turnover transaction costs at 20/40/60 bps.

The frozen US x1.2 contract is:

- seven canonical OHLCV factors in `momentum_volatility_volume`;
- XGBoost `rank:ndcg`, `hist`, `lossguide`;
- 200 rounds, `learning_rate=0.05`, `max_leaves=31`;
- `subsample=0.8`, `colsample_bytree=0.8`, seed 42;
- Top-15 equal weight;
- maximum four names per sector;
- ten-session holding and rebalance;
- 20 bps base transaction cost;
- QQQ benchmark.

Certification identity:

- workflow run `31425868143`;
- artifact `9077297330`;
- artifact digest `sha256:8b1457b926c8dbc675dae04cd2f71b5476625a011fca641976d88ab9ba813b2c`;
- rebuilt provider identity `b016eaa5a11e2d3e75110dceb9a4bf1ae2445d704fe7aded8b95bf3d338c14c6` through 2026-08-10.

Development 2024H1–2025H2:

| Model | Relative excess 20bps | Relative excess 60bps | Worst DD |
|---|---:|---:|---:|
| US x1.1 effective baseline | +125.89% | +105.46% | -34.49% |
| sector-cap only | +178.93% | +155.22% | -26.14% |
| **US x1.2 / r11_sampled** | **+207.84%** | **+182.39%** | -26.87% |
| r11_lower_lr | +144.82% | +125.01% | -26.02% |

`r11_sampled` has the highest pre-registered development selection score and reproduces its score path exactly. `r11_lower_lr` has slightly lower worst drawdown but materially less compounded relative excess.

## Prospective boundary

2026H1 was consumed before this selection and remains reporting-only. It cannot enter candidate ranking.

The available 2026H2 challenge currently covers only 2026-07-01 through 2026-07-27 with 18 horizon-contained dates. US x1.2 improves the incumbent in that slice (+2.31pp relative-excess advantage and lower drawdown), but its own relative excess versus QQQ is still negative (-12.08% at 20 bps).

The pre-registered sector-cap research contract requires a complete untouched future six-month window for prospective acceptance. That gate remains pending. The 2026-08-11 decision is therefore explicitly a **user-directed research-baseline promotion**, not a claim of prospective acceptance or trade readiness.

## US x1.1 historical record

US x1.1 promoted `us_x1_1_candidate_a` on 2026-08-02 and established the previous governed US comparison contract. Its development evidence, frozen spec, notebook and provider identity remain immutable historical evidence. They are not rewritten to resemble US x1.2.

The subsequent native-XGBoost and sector-concentration research identified the core path to x1.2: row/column sampling improved ranking economics while a maximum-four-names-per-sector constraint reduced concentration and drawdown. The corrected x1.2 certification combines those two mechanisms without changing the seven-factor feature family, label horizon or Top-15 portfolio role.

## Version semantics

- Released model files and historical evidence remain immutable.
- Superseded versions are not retained as execution fallbacks.
- A compatible model-contract improvement increments the minor version; the next US research version is **US x1.3**.
- A material universe, label, horizon, objective-family or execution-role change requires a major version.
- Provider refreshes are evidence revisions unless the model contract changes.
- Consumed reporting windows cannot be recycled into future candidate selection.
- User direction may promote a research baseline while independent prospective and operational gates remain explicitly incomplete.
- `trade_ready=false` remains mandatory until its separate validation and operational contract is satisfied.

## Evidence hierarchy

1. Model config under `configs/models/`.
2. Frozen research specification and exact effective parameter mapping.
3. Machine-readable certification/promotion receipt.
4. Provider identity and evidence cutoff.
5. Workflow run, artifact and digest.
6. Complete development/reporting metrics with consumed-window boundaries.
7. Canonical notebook validating the contract.

## Current US research queue

New US research must start from US x1.2, not silently replay US x1.1 as a fallback. The immediate evidence task is prospective observation of the frozen x1.2 contract through a complete untouched six-month window. Any US x1.3 hypothesis must be pre-registered independently and may not reuse that acceptance window for selection.

## Reproduction

The model notebooks validate the frozen contracts and their evidence identities. Computationally expensive full backtests remain governed provider-backed runs rather than browser or documentation recomputation.
