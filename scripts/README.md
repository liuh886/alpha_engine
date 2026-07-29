---
path: scripts/README.md
version: 1.2.0
last_edit_date: 2026-07-26
status: active
---

# Scripts Catalog

This folder contains a mix of **supported entrypoints** (stable, documented) and **one-off utilities** (debug/legacy).

## Supported entrypoints

- **E2E Smoke Test** (P0 - Single-command P0 validation of the entire pipeline.):
  - `python scripts/e2e_smoke.py --market {market} [--dry-run]`
- **Training + Backtest** (P0 - Full training and backtest pipeline. Generates MLflow runs and updates dashboard.):
  - `python -m src.orchestrator run --market {market} --model_type lgbm --tag <MODEL_TAG> [--strategy_template <STRAT>]`
- **Re-backtest** (P1 - Recompute drawdown or extend backtest to latest data without retraining.):
  - `python -m src.orchestrator rebacktest --market {market} --start 2025-01-01 --end latest`
- **API Server** (P0 - Serves the analytical UI and local APIs.):
  - `python api_server.py` (located in root)
- **Build Dashboard DB** (P0 - Regenerate dashboard JSON from MLflow artifacts.):
  - `python scripts/build_dashboard_db.py`
- **Daily Routine** (P0 - E2E sequence: data sync -> inference -> dashboard update.):
  - `python scripts/daily_run.py`
- **Arena Settle** (P1 - Calculate leaderboard and rankings from backtest equity curves.):
  - `python scripts/arena_settle.py --market {market} --arena-name "{arena}" --date latest`
- **System Doctor** (P0 - Check environment health and metadata consistency.):
  - `python scripts/doctor.py`
- **Research Assistant Compatibility Entry** (P0 - Route a legacy role alias
  into the unified `ResearchAssistant`; these aliases are not separate runtime
  agents.):
  - `python scripts/agent_entry.py --agent {alpha|risk|governance|developer} [--market {cn|us|all}] [--topic "<topic>"]`

## Utilities (use as needed)

- Update Data: `python scripts/update_data.py --market {market}`
- Static Site Export: `python scripts/export_static_site_data.py --market all --output site/data`
- Build an isolated NDX research provider without mutating operational data:
  `uv run python scripts/build_ndx_window_start_provider.py --base-data-root . --output-data-root <isolated-root>`
  The builder verifies copied source hashes, fails closed on split-like
  adjusted-close discontinuities, and records any full-history refresh in its
  provider lineage.
- Re-run the frozen candidate_v2 on official NDX window-start membership:
  `uv run python scripts/run_candidate_v2_ndx_window_start_evidence.py --data-root <isolated-root> --provider-lineage-path <isolated-root>/data/provider_backfill_lineage.json --first-test-year 2024 --last-test-year 2026`
- Diagnose broad IC versus exact Top-3 tails for the seven frozen candidate_v2
  inputs without training or tuning:
  `uv run python scripts/run_candidate_v2_ndx_factor_diagnostics.py --data-root <isolated-root>`
- Falsify one predeclared binary-Top-3 LambdaRank objective on the
  horizon-contained 2026H1 holdout:
  `uv run python scripts/run_candidate_v2_top3_holdout_evidence.py --data-root <isolated-root> --provider-lineage-path <isolated-root>/data/provider_backfill_lineage.json`

## Legacy

Deprecated/kept-for-reference scripts live under `scripts/_legacy/`.

If a utility script becomes part of the “daily/weekly” workflow, promote it to the supported list above and document it in `README.md`.
