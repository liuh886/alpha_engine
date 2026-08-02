---
path: scripts/README.md
version: 2.0.0
last_edit_date: 2026-08-02
status: active
---

# Scripts Catalog

This folder contains supported Python research entrypoints and explicitly isolated utilities. Browser execution is not supported; Research Artifact Studio reads exported evidence only.

## Supported entrypoints

- **Environment doctor**
  - `uv run python scripts/doctor.py`
- **Data update**
  - `uv run python scripts/update_data.py --market {cn|us|all}`
- **Training and backtest orchestration**
  - `uv run python -m src.orchestrator run --market {market} --model_type lgbm --tag <MODEL_TAG>`
- **Re-backtest**
  - `uv run python -m src.orchestrator rebacktest --market {market} --start 2025-01-01 --end latest`
- **End-to-end research smoke**
  - `uv run python scripts/e2e_smoke.py --market {market} [--dry-run]`
- **Build dashboard evidence JSON**
  - `uv run python scripts/build_dashboard_db.py`
- **Export static evidence source**
  - `uv run python scripts/export_static_site_data.py --market all --output artifacts/site/data`
- **Export versioned research bundle**
  - `uv run python scripts/export_research_bundle.py --source artifacts/site --output artifacts/research-bundle`
- **Daily research routine**
  - `uv run python scripts/daily_run.py`
- **Daily US low-turnover decision evidence**
  - `uv run python scripts/run_latest_us_low_turnover_decision.py`
- **Weekly research**
  - `uv run python scripts/weekly_research.py --market {market}`
- **Factor decay check**
  - `uv run python scripts/check_factor_decay.py --update-metadata`
- **Weekly report**
  - `uv run python scripts/generate_weekly_report.py`
- **Local schedule template**
  - `uv run python scripts/setup_cron.py`
- **Arena settlement**
  - `uv run python scripts/arena_settle.py --market {market} --arena-name "{arena}" --date latest`
- **Research Assistant compatibility entry**
  - `uv run python scripts/agent_entry.py --agent {alpha|risk|governance|developer} [--market {cn|us|all}] [--topic "<topic>"]`

## Controlled research utilities

These commands must remain bound to their predeclared evidence contracts:

- Build an isolated NDX provider:
  - `uv run python scripts/build_ndx_window_start_provider.py --base-data-root . --output-data-root <isolated-root>`
- Run the frozen candidate_v2 on official NDX window-start membership:
  - `uv run python scripts/run_candidate_v2_ndx_window_start_evidence.py --data-root <isolated-root> --provider-lineage-path <isolated-root>/data/provider_backfill_lineage.json --first-test-year 2024 --last-test-year 2026`
- Diagnose broad IC versus exact Top-3 tails:
  - `uv run python scripts/run_candidate_v2_ndx_factor_diagnostics.py --data-root <isolated-root>`
- Falsify the predeclared binary-Top-3 objective:
  - `uv run python scripts/run_candidate_v2_top3_holdout_evidence.py --data-root <isolated-root> --provider-lineage-path <isolated-root>/data/provider_backfill_lineage.json`
- Run NDX residual-trend evidence:
  - `uv run python scripts/run_ndx_residual_trend_evidence.py --data-root <isolated-root>`
- Run CN residual-trend evidence:
  - `uv run python scripts/run_cn_residual_trend_evidence.py --data-root <isolated-cn-root>`
- Decompose static-to-PIT alpha collapse:
  - `uv run python scripts/run_static_to_pit_alpha_decomposition.py --static-reference-provider-uri <original-static-provider> --decomposition-provider-uri <repaired-pit-provider>`

## Output rules

- Persist configuration, commit SHA, provider identity, data cutoff, universe identity and benchmark identity.
- Write immutable evidence under `artifacts/` or `reports/`.
- Export browser-visible results through the versioned research bundle.
- Do not silently overwrite a prior run identity.
- Do not bypass coverage, cost, embargo, walk-forward or promotion gates.
- Keep `research_only=true` and `trade_ready=false` unless an independently governed process changes that status.

## Legacy utilities

Deprecated scripts kept only for reference live under `scripts/_legacy/`. They are not supported entrypoints and must not be restored to the product path without a new architecture decision.
