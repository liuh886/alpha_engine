> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Evaluation Log

## 2026-05-29: Full System Audit (Product Manager Perspective)

**Evaluator**: Claude (PM role)
**Scope**: All frontend pages, backend API contracts, data pipeline, model methodology
**Goal**: Assess effectiveness and usability for "discovering effective trading strategies for alpha excess returns vs QQQ/CSI300"

### P0 — Data Credibility (blocks trust in all numbers)

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 1 | Valid = Test (same 2025 period for both) — all metrics are optimistically biased | CRITICAL | `configs/us_lgbm_workflow.yaml:247-255`, `cn_lgbm_workflow.yaml` |
| 2 | `data-parser.ts` uses `\|\| 0` for missing metrics — zero and missing are indistinguishable | HIGH | `qlib-dashboard/src/lib/data-parser.ts:33-38` |
| 3 | BacktestPage polls global latest job, not the specific job_id — false-positive completion | HIGH | `qlib-dashboard/src/pages/BacktestPage.tsx` |

### P1 — Strategy Selection Efficiency (blocks core workflow)

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 4 | ModelsPage has no sorting/filtering by metrics | HIGH | `qlib-dashboard/src/pages/ModelsPage.tsx` |
| 5 | No drawdown chart or monthly returns heatmap | MEDIUM | `qlib-dashboard/src/components/PerformanceCharts.tsx` |
| 6 | Compare page hidden from sidebar — strategy comparison undiscoverable | MEDIUM | `qlib-dashboard/src/components/Sidebar.tsx` |

### P2 — System Robustness

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 7 | All fetch errors silently swallowed — backend down shows stale data | MEDIUM | `App.tsx` lines 53, 80, 212, 221 |
| 8 | No data staleness indicator — `generated_at` parsed but never shown | LOW | `App.tsx`, `data-parser.ts` |
| 9 | BacktestPage model type hardcoded to `["lgbm"]` only | LOW | `BacktestPage.tsx` |
| 10 | Risk controls: only post-hoc MDD check, no position-level stop-loss | LOW | `src/guardrails/risk_monitor.py` |

### P3 — Nice to Have

- KPI cards show benchmark comparison inline (e.g., "Sharpe 1.2 vs QQQ 0.8")
- Heatmap click-through to symbol detail
- Methodology doc editable from UI

### Methodology Assessment

- **Train/Valid/Test**: Scientifically invalid (Valid=Test). Must fix before trusting any metric.
- **Features**: Alpha158 is solid but US/CN configs are identical — ignores market structure differences.
- **Strategy**: BiweeklyTrend is reasonable but Top-5 is highly concentrated; equal-weight sizing ignores volatility.
- **Risk**: Minimal — only post-hoc MDD check at 15% threshold. No intraday monitoring, no sector limits.
