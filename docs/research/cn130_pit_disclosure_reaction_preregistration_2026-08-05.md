# CN130 PIT disclosure-reaction conditioning preregistration

Issue: #550  
Status: frozen before validation output is inspected  
Boundary: `research_only=true`, `trade_ready=false`

## Purpose

Static PIT accounting levels and growth fields did not improve the CN130 R0 tail architecture. This experiment tests a genuinely dated signal: the price and turnover reaction immediately after a periodic-report disclosure.

R0 continues to select four sectors and define each sector's Top3 shortlist. Event information may only condition the final Top1 decision or remove one sector's exposure.

## Event-time integrity

- One event is retained per symbol, disclosure date and fiscal period.
- The first reaction session is the first provider trading day strictly after `available_at`.
- The three-session feature is unavailable until all three reaction sessions are complete.
- At each rebalance only the latest completed event no more than 20 trading sessions old is eligible.
- Same-day disclosure trading and future event reactions are prohibited.

## Stage separation

- `2022H2`, `2023H1`, `2023H2`: component and architecture calibration only.
- `2024H1` through `2025H2`: one-shot frozen validation only if both calibration gates pass.
- `2026H1` and `2026H2_PARTIAL`: reporting only.

If the component gate fails, architecture calibration and validation stay closed. If a component passes but no architecture passes, validation stays closed.

## Multiple-comparison boundary

Only five event components and three event-conditioned transformations of the existing R0 sector-4x1 rule are allowed. No alternative event age, reaction horizon, shortlist size, continuous blend or threshold search is allowed in this round.

## Promotion boundary

A validation pass would create only a research candidate. It cannot modify CN x1.0, create CN x1.1 automatically, or become trade-ready without a separate promotion review.
