---
path: 100_Project/2601_Trading/scripts/Task_Registry_Candidates_v0.1.md
version: 0.2.0
last_edit_date: 2026-02-24
status: draft
---

# Trading Script -> Runtime Task Registry Candidates (v0.2)

Purpose:
- provide a governed migration backlog from project-supported script entrypoints to runtime task registry tasks
- improve execution routing clarity without prematurely registering unstable commands

Scope:
- candidates only (no registry entries are created by this file)
- based on `100_Project/2601_Trading/scripts/README.md` -> `Supported entrypoints`

## Phase 1 Registration Status (2026-02-24)

Registered into `800_System/Runtime/Registry/task_registry.json`:
- `project.trading.e2e_smoke`
- `project.trading.dashboard_db_build`
- `project.trading.daily_run`

The remaining rows below stay as migration backlog candidates.

## Prioritization Rules

- `P0`: frequent operational entrypoints used in daily/weekly execution
- `P1`: reporting/export entrypoints with stable inputs/outputs
- `P2`: less frequent or more stateful entrypoints (serve/delete/admin flows)

## Candidate Mapping Backlog

| Priority | Candidate Task ID | Current Entrypoint | Purpose | Readiness | Notes |
|---|---|---|---|---|---|
| P0 | `project.trading.daily_run` | `python scripts/daily_run.py` | Daily data -> inference -> dashboard JSON | registered | Phase 1 complete (runtime task added) |
| P0 | `project.trading.e2e_smoke` | `python scripts/e2e_smoke.py --market {cn|us}` | P0 smoke validation | registered | Phase 1 complete (runtime task added) |
| P0 | `project.trading.orchestrator_run` | `python -m src.orchestrator run --market {cn|us|all} ...` | Train + backtest | medium | Needs stable args contract (`tag`, `strategy_template`, cost params) |
| P0 | `project.trading.rebacktest` | `python -m src.orchestrator rebacktest --market {cn|us} ...` | No-retrain backtest rerun | medium | Good candidate after arg schema is frozen |
| P0 | `project.trading.dashboard_db_build` | `python scripts/build_dashboard_db.py` | Rebuild dashboard dataset | registered | Phase 1 complete (runtime task added) |
| P1 | `project.trading.dashboard_server` | `python scripts/dashboard_server.py` | Serve UI + local APIs | low | Long-running process; define runner policy separately |
| P1 | `project.trading.arena_settle` | `python scripts/arena_settle.py ...` | Arena leaderboard settlement | medium | Requires stable arena/date arg contract |
| P1 | `project.trading.backtest_report_generate` | `python scripts/generate_backtest_report.py ...` | HTML backtest report generation | medium | Consider split `latest` vs `run_id` modes |
| P1 | `project.trading.arena_report_generate` | `python scripts/generate_arena_report.py ...` | Arena report generation | medium | |
| P1 | `project.trading.reports_zip_export` | `python scripts/export_reports_zip.py ...` | Report archive export | medium | |
| P1 | `project.trading.static_site_export` | `python scripts/export_static_site_data.py --market all --output site/data` | GitHub Pages data export | high | Stable output path and clear verification hook |
| P1 | `project.trading.static_site_check` | `python scripts/check_static_site.py --site-dir site` | Static site validation | high | Good candidate paired with export |

## Suggested Registration Sequence

1. `project.trading.static_site_export`
2. `project.trading.static_site_check`
3. `project.trading.orchestrator_run`
4. `project.trading.rebacktest`
5. `project.trading.arena_settle`

## Registry Migration Notes (When Implementing)

- Register only supported entrypoints, not utilities.
- Each task should declare:
  - working directory = `100_Project/2601_Trading`
  - executor = `python`
  - argument mode and expected outputs
- Update:
  - `800_System/Runtime/Registry/task_registry.json`
  - `100_Project/2601_Trading/agents/governance/workflows/trading_execution_bus.workflow.md` (`task_ids`)
  - `100_Project/2601_Trading/README.md` (Module 3 execution bus notes)

