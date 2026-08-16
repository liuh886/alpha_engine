# Issue #966 Phase 4 — distribution-state diagnostics

Status: **preregistered diagnostic-only experiment**.

Phase 2 found no independently useful first-wave mechanism, so Phase 3 transform search was intentionally skipped. Phase 4 follows the original plan: test return-distribution factors as possible risk/regime diagnostics before considering any control or model use.

## Scope

Only two independent Alpha Engine factors are introduced:

- `distribution_risk_research.ret_skew_20d` = `Skew($close/Ref($close,1)-1,20)`
- `distribution_risk_research.ret_kurt_20d` = `Kurt($close/Ref($close,1)-1,20)`

They are **diagnostic-only**. They are not appended to US x1.2/CN x1.2 ranker inputs and they do not change portfolio exposure.

The 20-session window is deliberately singular: one trading month is enough to test the distribution-state hypothesis without starting a horizon/transform search.

## Frozen surfaces

The diagnostic reuses the Phase-2 frozen baseline contracts:

- US87 / US x1.2 / selection windows 2024H1–2025H2.
- CN130 / CN x1.2 / development windows 2024H1–2026H1; 2026H2 remains untouched.
- exact market-specific provider identity and cutoff `2026-06-30`.
- existing XGBoost calibration and 10-session forward-return label for the baseline ranker-failure outcome.

## Risk-state construction

Cross-sectional distribution state is reduced to two market-level daily diagnostics:

- **negative median skew20**: higher means the cross-section has more negative return asymmetry;
- **median kurt20**: higher means fatter recent tails.

The comparison set is limited to maintained, simple risk signals already represented in the current architecture:

- benchmark 20-session realized volatility;
- negative benchmark 60-session momentum;
- negative benchmark distance from MA200;
- low breadth: `1 - fraction(universe close > MA60)`.

## Forward outcomes

Every state at date `t` is compared with four 10-session forward adverse outcomes:

1. benchmark loss: negative 10-session forward benchmark return;
2. benchmark drawdown severity: negative minimum benchmark return reached during the next 10 sessions;
3. breadth deterioration: negative change in MA60 breadth over the next 10 sessions;
4. ranker failure: negative daily cross-sectional Rank IC of the frozen baseline score against the 10-session forward return.

These are outcomes only; they never enter factor construction.

## Preregistered evidence rule

For each distribution state/outcome pair, report:

- direct Spearman correlation;
- partial Spearman after rank-residualizing both signal and outcome against all four existing risk signals;
- top-risk-quintile minus bottom-risk-quintile outcome spread;
- per-window Spearman and positive-sign window share.

A pair is called **strong** only when all are true:

- direct Spearman >= `0.08` in the expected risk direction;
- partial Spearman >= `0.05` after existing-risk controls;
- high-risk quintile has a worse forward outcome than low-risk quintile;
- correlation sign is positive in at least `60%` of selection windows.

A distribution state is `diagnostic_useful` only with at least **two** strong outcomes. It becomes eligible for a later **single-use control test** only if at least one of those strong outcomes is benchmark loss or benchmark drawdown severity.

These thresholds decide whether further testing is warranted; they are not promotion or trading thresholds.

## Stop rules

- no ranker feature additions in this phase;
- no exposure or veto rule unless the diagnostic gate first passes;
- no skew/kurt horizon search;
- no transform grid;
- no 2026H2 CN use;
- no automatic promotion.
