> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Task Board

## P0 — Data Credibility

- [x] **T1: Fix Valid/Test split** — Changed test period to 2026-01-01/2026-04-03 in both configs. ✅ 2026-05-28
- [x] **T2: Fix metric zero-fallback** — Changed `|| 0` to `?? null` in data-parser.ts, "N/A" display in OverviewCards. ✅ 2026-05-28
- [x] **T3: Fix BacktestPage job polling** — Two-phase polling with proper refs cleanup. ✅ 2026-05-28

## P1 — Strategy Selection

- [x] **T4: Add metric sorting/filtering to ModelsPage** — Sort by Sharpe/Return/MDD, filter by market and min Sharpe. ✅ 2026-05-29
- [x] **T5: Add drawdown chart** — Drawdown curve with max-DD annotation in PerformanceCharts. ✅ 2026-05-29
- [x] **T6: Add monthly returns heatmap** — Year×Month grid with color-coded returns. ✅ 2026-05-29
- [x] **T7: Restore Compare in sidebar** — Added Compare nav item with Layers icon. ✅ 2026-05-29

## P2 — Robustness

- [x] **T8: Add error state to data fetching** — API error banner in GlobalStatusBar with WifiOff icon. ✅ 2026-05-29
- [x] **T9: Show data staleness** — Data age in GlobalStatusBar (e.g. "Data: 3h ago"), yellow warning after 2 days. ✅ 2026-05-29
- [x] **T10: Dynamic model type list** — Model type is now a text input, not hardcoded buttons. ✅ 2026-05-29
