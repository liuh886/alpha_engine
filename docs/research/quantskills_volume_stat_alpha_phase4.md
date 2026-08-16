# Issue #966 Phase 4 — distribution-state diagnostics

Status: **COMPLETE. US negative-median skew survives as one research-only exposure control; kurtosis and all CN distribution controls reject.**

Authoritative machine-readable evidence: `data/research/quantskills_volume_stat_alpha/gate4_distribution_risk.json`.

Phase 2 found no independently useful first-wave mechanism, so Phase 3 transform search was intentionally skipped. Phase 4 tested return-distribution factors as risk/regime diagnostics before considering any control use.

## Scope

Only two independent Alpha Engine factors were introduced:

- `distribution_risk_research.ret_skew_20d` = `Skew($close/Ref($close,1)-1,20)`
- `distribution_risk_research.ret_kurt_20d` = `Kurt($close/Ref($close,1)-1,20)`

Both passed exact-provider structural checks on US87 and CN130: finite coverage, no inf, non-constant output, no future expression window, symbol isolation, and deterministic reproduction. They therefore advance from `unvalidated_formula` to `candidate` as canonical research formulas. That status does not imply trading usefulness.

The 20-session window remains the only distribution horizon tested. No transform or horizon grid was opened.

## Frozen surfaces

- US87 / US x1.2 / selection windows 2024H1–2025H2.
- CN130 / CN x1.2 / development windows 2024H1–2026H1; 2026H2 remained untouched.
- exact market-specific provider identity and cutoff `2026-06-30`.
- existing XGBoost calibration and 10-session forward-return label for the baseline ranker-failure outcome.
- no ranker feature changes during the diagnostic gate.

## Diagnostic construction

Cross-sectional distribution state was reduced to two market-level daily diagnostics:

- **negative median skew20**: higher means more negative return asymmetry;
- **median kurt20**: higher means fatter recent tails.

Existing risk controls were benchmark 20-session realized volatility, negative benchmark 60-session momentum, negative benchmark distance from MA200, and low MA60 breadth.

Forward adverse outcomes were benchmark 10-session loss, future 10-session benchmark drawdown severity, MA60 breadth deterioration, and frozen-baseline ranker failure (negative daily Rank IC).

A relationship was preregistered as strong only when direct Spearman >= `0.08`, partial Spearman after existing-risk controls >= `0.05`, high-risk quintile outcome spread > 0, and the expected sign appeared in at least `60%` of windows. A state needed at least two strong outcomes to become diagnostic-useful.

## US diagnostic result

`negative_median_skew20` passed the diagnostic gate with two strong market-stress outcomes:

| Outcome | Direct Spearman | Partial Spearman | Positive-window share | High-risk minus low-risk outcome spread |
| --- | ---: | ---: | ---: | ---: |
| future benchmark loss | 0.211222 | 0.247292 | 75% | 0.027970 |
| future drawdown severity | 0.237146 | 0.195108 | 75% | 0.024473 |

The ranker-failure relationship was positive in aggregate but failed the preregistered window-stability rule, and breadth deterioration also failed the stability rule. That is acceptable: the hypothesis was market risk-state information, not universal prediction of every adverse outcome.

`median_kurt20` had zero strong outcomes and is not a control candidate.

Decision: only negative-median skew was eligible for **one** control test.

## CN diagnostic result

No CN distribution state passed the utility gate.

- negative median skew20 had zero strong outcomes; several relationships ran in the opposite direction.
- median kurt20 had one strong relationship, future benchmark loss (`direct=0.086295`, `partial=0.064360`, positive in 80% of windows), but the preregistered rule required at least two strong outcomes.

Decision: keep both CN distribution factors diagnostic-only. No CN control was tested.

## Single-use US exposure-control test

The control was preregistered before execution and changed only gross risky exposure:

- state: negative cross-sectional median skew20;
- high-risk threshold: current state above the **strictly lagged** trailing 252-session 80th percentile;
- normal risky exposure: `1.0`;
- high-risk risky exposure: `0.5`;
- no threshold search;
- no exposure-level search;
- same frozen US x1.2 score, Top-15 sector-capped selection, 10-session cadence, and 20/60 bps costs.

The controlled evaluator first reproduced the existing full-exposure sector-cap economics exactly in every window and at both costs. The control itself reproduced deterministically on a second run.

Across the four selection windows it fired in only **7 of 48** rebalance periods.

| Metric | Frozen full exposure | Skew control | Change |
| --- | ---: | ---: | ---: |
| 20 bps compounded relative excess | 2.592880 | 2.608204 | +0.015324 |
| 20 bps max drawdown | -0.262181 | -0.241268 | **+0.020912** |
| 20 bps turnover | 21.8 | 20.8 | -1.0 |
| 60 bps compounded relative excess | 2.255733 | 2.285163 | +0.029430 |
| 60 bps max drawdown | -0.268090 | -0.245775 | +0.022315 |

Relative-excess retention was `1.00591` at 20 bps and `1.01305` at 60 bps, all four windows remained positive, and every preregistered Gate-4 check passed.

Decision: **negative-median skew20 survives as a research-only risk-control candidate.** It is not automatically added to the production model or portfolio policy.

## Phase 4 close

- US skew formula: structurally validated candidate; diagnostic useful; one exposure-control use passed.
- US kurtosis: structurally validated candidate; diagnostic utility rejected.
- CN skew/kurtosis: structurally validated candidates; control utility rejected.
- US/CN ranker features unchanged.
- production portfolio policy unchanged.
- no automatic promotion.

Next: Phase 5 should consolidate factor evidence/status through the existing canonical FactorLibrary rather than create another catalog. Phase 6 should then certify the smallest winning US feature set and the surviving skew control while preserving the reserved holdout boundary.
