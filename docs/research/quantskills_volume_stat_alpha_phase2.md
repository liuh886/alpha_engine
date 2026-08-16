# Issue #966 Phase 2 — incremental ablation result

Status: **Gate 2 complete. No individual first-wave mechanism survives. One US joint feature set survives as complementarity evidence.**

Authoritative machine-readable decision: `data/research/quantskills_volume_stat_alpha/gate2_ablation.json`.

## Frozen experiment

Phase 2 changed feature inputs only. Model family/calibration, 10-session label, governed universe/provider identity, portfolio construction, 20/60 bps costs, and selection/holdout boundaries stayed fixed.

- US: US87 / QQQ / current x1.2 seven-factor baseline / 2024H1–2025H2 selection.
- CN: CN130 / CSI300 / current x1.2 seventeen-factor baseline / 2024H1–2026H1 development; 2026H2 remained untouched.
- CN did not create a duplicate price-volume-correlation challenger because `qlib_alpha158.cord5` is already active in CN x1.2.

## US result

Frozen baseline compounded relative excess was `1.670689` at 20 bps and `1.453453` at 60 bps, with worst drawdown `-0.262181` and mean Rank IC `0.049699`.

Each single mechanism failed the incremental economic gate despite acceptable redundancy:

| Challenger | 20 bps relative excess | 60 bps | Worst DD | Mean Rank IC | Max abs mean daily rank corr | Gate 2 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| + signed-volume flow | 1.319526 | 1.133484 | -0.288879 | 0.050216 | 0.697430 | reject |
| + CORD10 | 1.515879 | 1.328740 | -0.273601 | 0.050564 | 0.546879 | reject |
| + RANK20 | 1.431264 | 1.237314 | -0.283049 | 0.049615 | 0.761866 | reject |

The preregistered **all-three** candidate behaved differently: relative excess `2.145274` at 20 bps and `1.906783` at 60 bps, worst drawdown improved to `-0.251436`, and mean Rank IC improved to `0.052400`. All four selection windows had positive excess and exact score reproduction matched. All three component redundancy statistics remained below the preregistered `0.95` threshold.

Decision: keep `us_x1_2_plus_all_three` as a **surviving joint feature set**, not as proof that any individual mechanism is independently promotable.

## CN result

The current CN x1.2 baseline remains clearly stronger:

- baseline: relative excess `0.756642` / `0.515624` at 20/60 bps; worst DD `-0.147714`; mean Rank IC `0.034634`.
- + signed-volume: `0.361672` / `0.180916`; worst DD `-0.200005`; mean Rank IC `0.030438`.
- + RANK20: `0.552197` / `0.337040`; worst DD `-0.150799`; mean Rank IC `0.029755`.
- + signed-volume + RANK20: `0.328075` / `0.152156`; worst DD `-0.214349`; mean Rank IC `0.028469`.

Every CN candidate reproduced scores and exact portfolios deterministically, but none beat the frozen baseline at either cost level. Signed-volume variants also violated the drawdown-worsening limit. Preserve CN x1.2 unchanged.

## Gate 2 interpretation

The important result is not that the external factor corpus is broadly useful. It is narrower:

1. **CN:** no first-wave addition survives.
2. **US individual mechanisms:** none survives on its own.
3. **US joint set:** the three together produce material complementarity under frozen economics.

This is precisely why Phase 2 measured marginal contribution instead of importing source-repository IC rankings.

## Phase 3 decision

**Skip transform search.** Phase 3 is defined as refinement of an independently surviving mechanism. No individual mechanism passed Gate 2 in either market. Starting raw/smoothed/z/vol-scaled/ranked searches now would be post-hoc parameter fishing.

The US joint set stays in evidence for later smallest-winning-feature-set certification. It does not authorize transform expansion.

## Next phase

Proceed to Phase 4 as planned: evaluate return skew/kurtosis primarily as regime/risk/failure-state diagnostics. Start diagnostic-only; do not add them to the cross-sectional ranker or change exposure rules unless the diagnostic evidence first establishes incremental risk information.
