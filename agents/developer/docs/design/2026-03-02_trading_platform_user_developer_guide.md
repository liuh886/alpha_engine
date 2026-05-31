---
title: Trading Platform User & Developer Guide
project: 2601_Trading
owner: Developer Agent (LifeOS-Soul PM Quality Gate)
version: 1.0.0
last_updated: 2026-03-02
status: active
ssot: true
---

# Trading Platform User & Developer Guide

This document is the **single-source guide** for users and developers of `2601_Trading` and is rendered in WebUI Docs.

## 1. Scope and Boundaries

### 1.1 Product scope (what this system does)
- Local-first quantitative trading assistant for CN/US markets.
- Supports data update, model training, re-backtest, model registry, arena ranking, and report export.
- Provides human-in-the-loop decision support through dashboard and APIs.

### 1.2 Explicit non-goals (what this system does not do)
- No direct broker auto-execution.
- No production-grade multi-tenant auth/RBAC.
- No guaranteed deterministic ML result across all environments.

### 1.3 Primary audience
- End users (operators/analysts): run daily tasks from WebUI.
- Developers/architects: maintain API/runtime/agent architecture and evolve strategy pipeline.

## 2. Documentation Structure (GitHub-style framing)

This guide follows common GitHub platform documentation patterns:
- Start with product boundary and architecture map.
- Provide quickstart and operation paths before internals.
- Explain concepts -> APIs -> implementation -> troubleshooting.
- Keep every key statement traceable to source code paths.

## 3. Architecture Overview

## 3.1 Two-layer architecture

### Runtime layer (independently runnable)
- `api_server.py` (FastAPI entry)
- `src/` (domain logic)
- `scripts/` (operational entrypoints)
- `qlib-dashboard/` (React WebUI)

### Agent layer (identity + intelligent workflow)
- `agents/alpha/*`
- `agents/risk/*`
- `agents/governance/*`
- `agents/developer/*`
- Unified CLI identity entry: `scripts/agent_entry.py`

## 3.2 High-level data/control flow
1. User triggers action in WebUI (e.g., data update, backtest, export).
2. WebUI calls API (`/api/*`).
3. API creates a background job in metadata DB (`jobs` table).
4. Job runner executes script/module commands and writes logs.
5. Artifacts and indexes are updated (`artifacts/*`, sqlite metadata).
6. WebUI polls job status and refreshes artifact-backed views.

## 4. Business Logic by Domain

## 4.1 Data domain
- Trigger path: `POST /api/data/update`.
- Job creation: `src/assistant/services/data_service.py` -> `src/dashboard/data_update_job.py`.
- Execution path: `scripts/update_data.py` and optional dashboard DB rebuild command chain.
- Status source:
  - Calendar: `data/watchlist/calendars/day.txt`
  - Snapshot index: metadata DB via `DataSnapshotIndex`
  - Quality index: metadata DB via `DataQualityIndex`

## 4.2 Backtest/Training domain
- Train: `POST /api/workflow/train`.
- Re-backtest or train-in-dashboard flow: `POST /api/backtest/run`.
- NL strategy compile: `POST /api/strategy/compile`.
- Command compiler and orchestrator core: `src/orchestrator.py`.
- Key constraints:
  - `train` requires `market in {cn, us}` and non-empty `tag`.
  - `rebacktest` requires resolvable `model_path`.

## 4.3 Model registry domain
- List: `GET /api/models`.
- Promote stage: `POST /api/models/promote`.
- Delete model: `POST /api/models/delete`.
- Implementation details:
  - sqlite index update + YAML sync + filesystem operation.
  - recommendation file copy target: `artifacts/models/recommended_<market>_model.pkl`.

## 4.4 Arena domain
- Settle leaderboard job: `POST /api/arena/settle`.
- Add participant: `POST /api/arena/participants`.
- Uses run/model bindings and arena indexes in metadata DB.

## 4.5 Reports domain
- List reports: `GET /api/reports`.
- Export zip job: `POST /api/reports/export`.
- Asynchronous job output logs under `artifacts/runs/`.

## 4.6 Governance/system domain
- Health: `GET /health`.
- Job list/detail/stream:
  - `GET /api/jobs`
  - `GET /api/jobs/{job_id}`
  - `GET /api/jobs/{job_id}/stream` (SSE)
- Panic stop: `POST /api/system/panic` marks running jobs failed.
- Exec command endpoint: `POST /api/system/exec` dispatches shell command as a job.

## 4.7 Agent routing domain
- API chat entry: `POST /api/agent/chat`.
- CLI entry: `python scripts/agent_entry.py --agent ...`.
- Router implementation: `src/agents/agent_router.py` with registry for alpha/risk/governance/developer.

## 5. Configuration Guide

## 5.1 Environment variables

| Variable | Default | Effect |
|---|---|---|
| `TRADING_UI_PASSWORD` | `alpha2026` | Basic auth password for API (username fixed as `agent`). |
| `TRADING_UI_TRUST_LOCALHOST` | `true` | If true, localhost requests can bypass credentials. |
| `TRADING_CONFIG_DIR` | `<project>/configs` | Config directory override. |
| `TRADING_DATA_DIR` | `<project>/data` | Data directory override. |
| `TRADING_ARTIFACTS_DIR` | `<project>/artifacts` | Artifact root override. |
| `TRADING_REPORTS_DIR` | `<project>/reports` | Reports directory override. |
| `TRADING_WEBHOOK_URL` | empty | Optional webhook for failed jobs alerts. |

## 5.2 Key config files
- Strategy/workflow configs: `configs/*.yaml` / `configs/*.json`
- Data router policy: `configs/data_router_policy.yaml`
- Strategy profile defaults: `configs/strategy_profile.json`, `configs/strategy_profile_quant_rating_us.json`

## 5.3 Containerized run
- `docker-compose.yaml` defines:
  - `alpha-api` on `8000` (serves both API and frontend static files)
- Mapped volumes include `data`, `artifacts`, `configs`.
- Frontend is built into `qlib-dashboard/dist/` and served by FastAPI.

## 6. WebUI Functional Map (User-facing)

## 6.1 Main navigation views
- Dashboard (`Dashboard`) — backtest results overview
- Backtest (`BacktestPage.tsx`) — backtest workbench + NL strategy compiler
- Models (`ModelsPage.tsx`) — model registry with sorting/filtering
- Compare (`ComparePage.tsx`) — side-by-side model comparison
- Data (`DataPage.tsx`) — data management + completeness heatmap
- Methodology (`MethodologyPage.tsx`) — training methodology docs
- Docs (`DocsPage.tsx`, this guide)

## 6.2 UI-API integration patterns
- Job-based actions return `job_id`, then UI polls `/api/jobs/{job_id}`.
- Long-running logs stream with SSE from `/api/jobs/{job_id}/stream`.
- Artifact-based pages read from `/artifacts/*.json` for faster rendering.

## 7. API Reference (Operational)

## 7.1 Data APIs
- `POST /api/data/update` payload:
  - `full: bool`
  - `lookback_days: int`
- `GET /api/data/status`
- `GET /api/data/instruments?market=us`
- `GET /api/data/snapshots/latest`
- `GET /api/data/quality/latest`
- `GET /api/data/stock/{symbol}`

## 7.2 Backtest/Train APIs
- `POST /api/backtest/run`
  - fields: `market`, `model_type`, `mode`, `run_id`, `model_path`, `start`, `end`, `tag`, `profile_path`.
- `POST /api/workflow/train`
  - fields: `market`, `model_type`, `tag`, `profile_path`.
- `POST /api/strategy/compile`
  - fields: `text` (NL description), `market` (optional).
- `DELETE /api/backtest/runs/{run_id}`

## 7.3 Model APIs
- `GET /api/models?limit=100&market=us`
- `POST /api/models/promote` with `version_id`, `stage`
- `POST /api/models/delete` with `version_id`

## 7.4 Arena APIs
- `POST /api/arena/settle`
- `POST /api/arena/participants`

## 7.5 Reports APIs
- `GET /api/reports`
- `GET /api/reports/{report_id}`
- `POST /api/reports/export`

## 7.6 System APIs
- `GET /health`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/stream`
- `GET /api/system/paths`
- `POST /api/system/panic`
- `POST /api/system/exec`

## 8. Implementation Deep Dive

## 8.1 Job execution model
- Job metadata is stored in sqlite (`jobs` table).
- Job command list is persisted as JSON.
- Runner executes command(s) sequentially and captures merged stdout/stderr into log file.
- Fail-fast on first non-zero exit code.

## 8.2 Path resolution strategy
- Runtime path access is centralized in `src/common/paths.py`.
- Supports env override without changing business code.
- Derived paths include mlruns/models/runs/dashboard directories.

## 8.3 Orchestrator behavior summary
- Entry: `python -m src.orchestrator run|rebacktest`.
- For `run`:
  - compile profile -> load workflow yaml -> ensure qlib env -> train -> predict -> backtest -> report -> dashboard DB.
- For `rebacktest`:
  - no retraining; load model -> rerun inference/backtest on configured window -> refresh dashboard DB.

## 8.4 Agent architecture behavior summary
- `AgentRouter` creates per-task agent instances dynamically.
- Governance agent coordinates Alpha + Risk and publishes evidence canvas.
- Developer agent focuses on plan execution semantics.
- Current agent implementations include simulation/stub behavior for several research/risk decisions.

## 9. Security and Safety Notes

- Basic auth via `TRADING_UI_USER` and `TRADING_UI_PASSWORD` environment variables.
- `POST /api/system/panic` is an operational kill switch for queued/running jobs in metadata state.

## 10. Developer Workflows

## 10.1 Local development
1. API: `uv run python api_server.py`
2. UI: `cd qlib-dashboard && npm run dev`
3. Open `http://localhost:5173`

## 10.2 Typical verification set
- Backend tests: `python -m pytest tests -q`
- UI build: `cd qlib-dashboard && npm run build`
- Smoke: `python scripts/e2e_smoke.py --market us`

## 10.3 Agent identity entry
- `python scripts/agent_entry.py --agent governance --market all`
- `python scripts/agent_entry.py --agent alpha --market us`
- `python scripts/agent_entry.py --agent risk --market us`
- `python scripts/agent_entry.py --agent developer --topic "architecture review"`

## 11. Troubleshooting

## 11.1 `nodemon` / `ts-node` not found
Symptom:
- `[nodemon] failed to start process, "ts-node src/index.ts" exec not found`

Cause:
- `ts-node` is missing from runtime dependencies or the command is executed in wrong project root.

Fix:
1. Ensure command runs in frontend/backend package where `ts-node` is installed.
2. Install as dev dependency if needed: `npm i -D ts-node`.
3. Prefer project native start scripts (`npm run dev`, `uv run python api_server.py`) instead of generic nodemon templates in this repo.

## 11.2 Job stuck in `running`
- Run repair script or service-level repair logic.
- `JobService.repair_jobs()` marks stale long-running jobs failed.

## 11.3 Empty dashboard data
- Verify `/artifacts/dashboard/dashboard_db.json` exists.
- Rebuild using `python scripts/build_dashboard_db.py`.

## 12. Known Gaps and Technical Debt

- Agent chat and multiple agent behaviors still include mock/simulated outputs.
- Auth model is minimal; no role-based access control yet.
- Some system endpoints are very powerful and require stricter production hardening.

## 13. Source Index (for traceability)

### Backend entry and routers
- `api_server.py`
- `src/api/routers/*.py`

### Services and execution
- `src/assistant/services/*.py`
- `src/assistant/job_service.py`
- `src/dashboard/*_job.py`
- `src/orchestrator.py`

### Agent system
- `src/agents/*`
- `scripts/agent_entry.py`
- `agents/*/workflows/*.workflow.md`

### WebUI
- `qlib-dashboard/src/App.tsx`
- `qlib-dashboard/src/components/Sidebar.tsx`
- `qlib-dashboard/src/pages/*.tsx`

## 14. PM Quality Gate (LifeOS-Soul)

Acceptance checklist for this guide:
- Business logic and runtime flow are mapped to concrete code paths.
- Config and operational instructions are executable and source-backed.
- Architecture description separates runtime and agent layers clearly.
- Security/limitations are disclosed explicitly.
- No duplicated rule document is introduced; this file is implementation documentation, not cross-agent rule authority.

Gate result: **PASS (2026-03-02)**.
