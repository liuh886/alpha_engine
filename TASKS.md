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

## P0 — Security (Sprint 2026-06-08)

- [x] **T11: Untrack .env and create .env.example** — Created template with placeholder values. ✅ 2026-06-08
- [x] **T12: Add MCP server authentication** — Token verification on all 5 tools. ✅ 2026-06-08
- [x] **T13: Fix hardcoded username in frontend** — Dynamic via /api/system/me endpoint. ✅ 2026-06-08

## P1 — Data Integrity (Sprint 2026-06-08)

- [x] **T14: Enable risk manager in configs** — use_risk_manager: true + risk_config in both YAML configs. ✅ 2026-06-08
- [x] **T15: Wire trailing stop + position limits** — Added to BiweeklyTrend and WeeklyQuantRating strategies. ✅ 2026-06-08
- [x] **T16: Automate walk-forward validation** — Runs after training, persists to artifacts/. ✅ 2026-06-08
- [x] **T17: Make MDD threshold configurable** — Via ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD env var. ✅ 2026-06-08

## P2 — Architecture Cleanup (Sprint 2026-06-08)

- [x] **T18: Remove dead agent code** — Deleted 4 deprecated agents, ported self_heal(). ✅ 2026-06-08
- [x] **T19: Update AGENTS.md** — Reflects actual single-agent architecture. ✅ 2026-06-08
- [x] **T20: Fix pages.yml workflow** — Corrected paths from old monorepo. ✅ 2026-06-08
- [x] **T21: Fix daily_run.py duplicate** — Removed duplicate if __name__ block. ✅ 2026-06-08

## Factor Lifecycle Infrastructure (Sprint 2026-06-08)

- [x] **T22: Build FactorRegistry** — SQLite-backed factor store with lifecycle stages. ✅ 2026-06-08
- [x] **T23: Build FactorEvaluator** — Arbitrary expression → IC/decay/quintile analysis. ✅ 2026-06-08
- [x] **T24: Add MCP factor tools** — 5 new tools including discover_factor composite. ✅ 2026-06-08
- [x] **T25: Factor lifecycle integration tests** — 30 tests, all passing. ✅ 2026-06-08
- [x] **T26: Batch factor scanner** — scan_factor_pool with 16 pre-built factors, parallel evaluation. ✅ 2026-06-08
- [x] **T27: Three-tier promotion gates** — Gate 1/2/3 with increasing rigor + correlation check. ✅ 2026-06-08
- [x] **T28: Factor-to-strategy compiler** — Auto-include Active factors in workflow YAML. ✅ 2026-06-08
- [x] **T29: Factor return attribution** — OLS factor model, per-factor return/risk contribution. ✅ 2026-06-08
- [x] **T30: Additional MCP tools** — scan_factor_pool, compile_strategy_with_factors, attribute_factor_returns. ✅ 2026-06-08
- [x] **T31: FDR correction** — Benjamini-Hochberg for multiple testing in factor scanning. ✅ 2026-06-08
- [x] **T32: Factor library** — 261 combinatorial factor expressions across 7 categories. ✅ 2026-06-08
- [x] **T33: Agent research loop** — End-to-end scan→compile→backtest→attribute→promote. ✅ 2026-06-08
- [x] **T34: Dashboard factor page** — FactorRegistryPage with stage badges, search, promote/demote. ✅ 2026-06-08

## Technical Debt Sprint (2026-06-08)

- [x] **T35: Wire analyze_factors() to real attribution** — Calls FactorAttribution, returns real R² and factor contributions. ✅ 2026-06-08
- [x] **T36: Walk-forward hard gate** — Blocks model promotion if ICIR < 0.3 or consistency < 0.55. ✅ 2026-06-08
- [x] **T37: ExperimentJournal** — Unified query over factors/models/walk-forward. MCP tool query_experiments. ✅ 2026-06-08
- [x] **T38: E2E pipeline validation** — 10-step validation, all 16 MCP tools confirmed working. ✅ 2026-06-08
- [x] **T39: Dashboard attribution page** — AttributionPage.tsx with bar chart + table. ✅ 2026-06-08
