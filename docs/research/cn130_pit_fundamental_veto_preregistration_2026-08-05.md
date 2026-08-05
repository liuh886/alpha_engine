# CN130 PIT fundamental veto and R0 shortlist preregistration

Issue: #544  
Draft PR: #545  
Status: frozen before calibration output is inspected  
Boundary: `research_only=true`, `trade_ready=false`

## Purpose

The equal-weight PIT fundamental composite in #542 passed data coverage but failed model validation. This follow-up does not reopen weights or replace R0. It asks whether a small set of calibration-supported fundamental components can improve R0 only through a Top3 shortlist reranker or a quality veto.

## Separation of stages

- 2022H1–2023H2: component and architecture calibration only.
- 2024H1–2025H2: one-shot frozen validation only after calibration gates pass.
- 2026H1 and 2026H2_PARTIAL: reporting only.

If no component passes Stage A, validation remains closed. If components pass but no architecture passes Stage B, validation remains closed.

## Multiple-comparison boundary

Only six predeclared fundamental components and three bounded transformations of the R0 industry Top1 rule are allowed. Top3, bottom tercile and sector median are fixed before execution. No other shortlist size, threshold or continuous blend is allowed.

## Promotion boundary

Even a validation pass creates only a research candidate. It cannot modify CN x1.0, create CN x1.1 automatically, or become trade-ready without a separate review.
