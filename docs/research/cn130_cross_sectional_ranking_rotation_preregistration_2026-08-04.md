# CN130 cross-sectional ranking and rotation preregistration

Date: 2026-08-04  
Issue: #509  
Parent model: CN x1.0  
Status: preregistered, implementation and immutable snapshot binding required  
Research boundary: `research_only=true`, `trade_ready=false`

## Decision

Keep `cn_selected_equities_v3` unchanged at 130 candidates.

The next CN research cycle will not treat pool reduction as the primary explanation for CN x1.0 weakness. It will first determine whether a stable cross-sectional ranking signal exists and only then test how that frozen signal should be translated into a rotating portfolio.

The experiment contract is:

`configs/research_experiments/cn130_cross_sectional_ranking_rotation_v1.yaml`

## Why the stages are separated

CN x1.0 currently combines a weak full-cross-section ranking signal with a Top-15 equal-weight portfolio. Positive portfolio economics in some historical windows were not consistently aligned with positive Rank IC. A portfolio can outperform because of sector concentration, beta, volatility, a small number of names, or benchmark composition even when the full ranking is not valid.

Therefore:

1. ranking candidates are selected by ranking evidence, not portfolio return;
2. the selected ranking rule is frozen;
3. portfolio and rotation alternatives are then compared without reopening the ranking model.

This prevents a profitable portfolio overlay from hiding an invalid stock-ranking signal.

## Fixed research universe

- pool: `cn_selected_equities_v3`;
- declared candidates: 130;
- benchmark: CSI 300 / `000300`;
- horizon, holding and rebalance cadence: 10 A-share sessions;
- base transaction cost: 20 bps;
- membership changes: prohibited;
- references entering candidate ranks: prohibited.

All experiments must preserve explicit lifecycle, suspension, limit and next-valid-session execution boundaries.

## Data gate

Execution is blocked until one immutable provider and data identity is bound into the experiment receipt. The receipt must contain:

- provider identity and cutoff;
- pool hash;
- market-calendar identity;
- corporate-action adjustment identity;
- factor-panel identity;
- code and config hashes.

Issue #345 remains a promotion blocker. Diagnostics may use one immutable snapshot, but the result may not be described as snapshot-independent until provider drift is explained.

## Required taxonomy

The complete CN130 pool must receive a versioned, reviewable taxonomy before ranking results are inspected:

- level-1 sector;
- level-2 sector or economic basket;
- market-cap group;
- beta and volatility measures;
- liquidity group;
- lifecycle and tradability status.

Taxonomy supports neutralization, hierarchical ranking and attribution. It may not be used to remove candidates after observing results.

## Ranking candidates

### R0 — current CN x1.0

Current raw forward-return percentile label, `cn_balanced_ohlcv`, XGBoost `rank:ndcg`, and one global cross-section.

### R1 — benchmark-relative ranking

Predict future 10-session stock return minus future CSI 300 return.

This tests whether the model should rank benchmark-relative opportunity rather than raw market-direction exposure.

### R2 — industry-relative ranking

Predict future return relative to the same-date sector median or sector percentile.

This removes the ability to appear successful merely because an entire industry rises.

### R3 — risk-residual ranking

Predict the residual future return after point-in-time cross-sectional controls for sector, market cap, beta and realized volatility.

This directly tests whether the model contains selection information beyond common style exposure.

### R4 — two-stage hierarchical ranking

Rank sectors or economic baskets first, rank securities within sectors second, then combine fixed percentiles:

`final_score = 0.35 * sector_percentile + 0.65 * within_sector_security_percentile`

The weights are frozen before performance evidence.

## Feature-family boundary

The first comparison may use only governed feature families:

1. current CN OHLCV baseline;
2. readiness-passed Alpha158 families;
3. PIT fundamentals only after their coverage gate passes.

Feature-family ablation is required. Individual Alpha158 fields may not be mined against the final evidence.

## Ranking decision

A ranking candidate must show positive and stable evidence across multiple windows. The primary tests are:

- Rank IC and Rank ICIR;
- Top-minus-Bottom spread;
- 5/10/20-session rank decay;
- Top-K and Bottom-K precision;
- score and rank stability;
- seed and block-bootstrap stability;
- leave-one-sector/name/window-out;
- sector, size, beta, volatility and liquidity exposure.

Portfolio return is a tiebreaker only after ranking support is established.

If no candidate passes, the experiment ends with:

`cn130_cross_sectional_ranking_not_supported`

## Rotation candidates after ranking freeze

The frozen ranking rule will be transformed through separately attributable portfolio cells:

- P0: current Top-15 equal weight;
- P1: Top 5 / 8 / 10 / 15 breadth comparison;
- P2: global ranking with sector and economic-basket caps;
- P3: hierarchical sector rotation with optional cash;
- P4: entry/exit rank buffer to reduce boundary churn;
- P5: 0% / 50% / 100% exposure based only on predeclared cross-sectional confidence.

Market-trend timing is an independent attribution cell and may not be used to select the ranking candidate.

## Required evidence upgrade

The existing formal CN x1.0 package retains only partial history. This experiment must preserve, for every rebalance date:

- every eligible security score and rank;
- realized 10-session returns;
- benchmark- and sector-relative returns;
- target and realized weights;
- transaction costs;
- security and sector contributions;
- exposure and lifecycle metadata;
- Top/Bottom membership and rank migration.

No half-year-only final-position substitute is acceptable.

## Final decisions

The experiment must end with exactly one:

- `cn130_cross_sectional_ranking_not_supported`;
- `cn130_ranking_supported_rotation_not_supported`;
- `cn_x1_1_candidate_supported`;
- `data_blocked`.

No decision updates CN x1.0 automatically. A supported candidate requires a separate reviewed version proposal and new untouched validation evidence.
