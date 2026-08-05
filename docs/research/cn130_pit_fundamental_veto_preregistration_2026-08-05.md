# CN130 PIT fundamental veto and R0 shortlist preregistration

Issue: #544  
Draft PR: #545  
Status: frozen before calibration output is inspected; amended for immutable-provider history  
Boundary: `research_only=true`, `trade_ready=false`

## Purpose

The equal-weight PIT fundamental composite in #542 passed data coverage but failed model validation. This follow-up does not reopen weights or replace R0. It asks whether a small set of calibration-supported fundamental components can improve R0 only through a Top3 shortlist reranker or a quality veto.

## Separation of stages

- 2022H2–2023H2: component and architecture calibration only, using three independent half-year windows.
- 2024H1–2025H2: one-shot frozen validation only after calibration gates pass.
- 2026H1 and 2026H2_PARTIAL: reporting only.

The originally preregistered 2022H1 window was removed before any component output was generated because the immutable price provider has fewer than the governed minimum 250 purged training sessions before that window. The training-history requirement is unchanged.

To compensate for the shorter calibration history, components and candidate architectures must be positive in all three calibration half-years. All IC, incremental-IC, worst-window, concentration, fiscal-period and leave-one thresholds are unchanged.

If no component passes Stage A, validation remains closed. If components pass but no architecture passes Stage B, validation remains closed.

## Multiple-comparison boundary

Only six predeclared fundamental components and three bounded transformations of the R0 industry Top1 rule are allowed. Top3, bottom tercile and sector median are fixed before execution. No other shortlist size, threshold or continuous blend is allowed.

## Promotion boundary

Even a validation pass creates only a research candidate. It cannot modify CN x1.0, create CN x1.1 automatically, or become trade-ready without a separate review.
