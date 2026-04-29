---
path: 100_Project/2601_Trading/agents/alpha/docs/factor-mining/2026-01-28-strategy-discovery-design.md
title: Strategy Discovery + Backtest Validation (CN/US)
date: 2026-01-28
owner_project: 100_Project/2601_Trading
status: archived
---

> Historical design asset migrated from root `docs/` on 2026-02-24.
> For current project facts and execution status, use `100_Project/2601_Trading/README.md`.

# Goal
Establish a minimal, repeatable strategy discovery + validation loop for CN and US using the existing Qlib-first pipeline. Focus on fast iteration and comparability, not breadth of model/strategy variants.

# Scope and Constraints
- Markets: CN (HS300 benchmark) + US (QQQ benchmark)
- Universe: merged concept of index constituents + watchlist; practical input is the current `configs/watchlist.yaml`
- Holding period: 1-2 weeks
- Rebalance: every 10 trading days
- Portfolio: Top5, equal-weight, long-only, no leverage
- Turnover: soft constraint (not a hard reject)
- Cost: 10 bps
- Model: LightGBM Ranker
- Label horizon: h=10
- Features: Alpha158 + Feature Pack A (ret_5d, ret_10d, ret_20d, vol_10d, vol_chg_10d)
- Validation window: 2025 (train 2021-2024), no rolling yet
- Split: time series with purged split + embargo (>= h) where applicable

# Success Criteria
Primary ranking metric: validation-period excess annualized return vs benchmark.
Secondary (soft) checks: max drawdown, turnover.

# Data Flow
1) Inputs:
   - `configs/strategy_profile.json` defines discovery constraints.
   - `configs/watchlist.yaml` defines universe.
   - `configs/*_workflow.yaml` are execution configs compiled from strategy profile.
2) Execution:
   - `python -m src.orchestrator run --market cn|us|all`
3) Extraction:
   - `python scripts/extract_backtest_sample.py` refreshes `dashboard_sample_data.json`
4) Dashboard:
   - Auto-load JSON, display meta (label/features/strategy/benchmark) + results.

# Feature Pack A
Add five simple, cross-market indicators:
- ret_5d, ret_10d, ret_20d (simple returns)
- vol_10d (return std)
- vol_chg_10d (volume change over 10d)

# Evaluation
For each market, produce one candidate run and rank by excess annualized return in 2025.
Show drawdown and turnover for sanity checks in the dashboard.

# Error Handling and Testing
- Fail fast if feature columns are missing.
- Verify JSON meta fields: label, features, benchmark, strategy profile.
- Confirm dashboard loads without manual import and compare view shows both runs.

# Next Steps
1) Implement Feature Pack A in data pipeline and config wiring.
2) Update workflow defaults for h=10, rebalance=10, Top5, long-only, cost=10bps, 2021-2024 train / 2025 validate.
3) Verify extraction meta fields and dashboard display.
