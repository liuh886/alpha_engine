> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Design Decisions

## Architecture Overview

```
Qlib Binary Data (data/watchlist/)
    ↓
MLflow Training Pipeline (src/workflows/hooks.py)
    ↓
Pickle Artifacts (mlruns/{exp_id}/{run_id}/artifacts/)
    ↓
build_dashboard_db.py → dashboard_db.json
    ↓
FastAPI (api_server.py) → React Dashboard (qlib-dashboard/)
```

## Key Design Constraints

- Single-user system (no multi-tenancy)
- Qlib binary format for market data (float32 .bin files)
- LightGBM only (no neural nets, no ensemble)
- BiweeklyTrendStrategy with TopK=5 concentration
- 15% MDD circuit breaker as sole risk control

## Decision Log

### 2026-05-29: Dashboard Simplification
- Reduced sidebar from 10 to 6 items
- Added Data Completeness Heatmap (Canvas 2D for 191K+ cells)
- Added Methodology documentation page
- Added Backtest Workbench page
- Removed glassmorphism UI, switched to neutral dark theme

### 2026-05-29: Data Pipeline Fix
- Added `compute_indicators_from_report()` to build_dashboard_db.py
- Added `merge_benchmarks_into_report()` for bench_qqq/bench_hs300 columns
- Fixed MLflow DB schema mismatch (upgraded 1.27.0 → 1.30.1)
