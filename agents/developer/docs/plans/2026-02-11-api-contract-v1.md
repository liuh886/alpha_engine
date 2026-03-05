# Dashboard API Contract v1.0 (2026-02-11)

This document defines the baseline for the Trading Assistant Dashboard API. 
Implemented in: `scripts/dashboard_server.py`.

---

## 1. System & Health
### `GET /health`
- **Description**: Basic health check.
- **Response**: `{ "ok": true }`

### `GET /api/system/paths`
- **Description**: Returns local directory configuration for debug/UI reference.
- **Response**:
```json
{
  "ok": true,
  "paths": {
    "project_root": "...",
    "data_dir": "...",
    "reports_dir": "...",
    "artifacts_dir": "..."
  }
}
```

---

## 2. Data Layer
### `GET /api/data/stock/{symbol}`
- **Description**: Fetches OHLCV data for a specific symbol (last 252 days).
- **Response**: `{ "ok": true, "symbol": "...", "ohlcv": [...] }`

### `GET /api/data/status`
- **Description**: High-level status of data pipelines (latest calendar, quality issues).
- **Response**: `{ "ok": true, "data": { "quality_status": "ok/warning", ... } }`

### `GET /api/data/snapshots/latest`
- **Description**: Get metadata for the latest data snapshot.
- **Query Params**: `dataset_key`, `freq`.

### `GET /api/data/quality/latest`
- **Description**: Get the latest data quality report.
- **Query Params**: `dataset_key`, `freq`, `market`.

### `POST /api/data/update`
- **Description**: Trigger an asynchronous data update job.
- **Body**: `{ "market": "us/cn/all", "incremental": true }`
- **Response**: `202 Accepted` with `job_id`.

---

## 3. Training & Models
### `GET /api/models`
- **Description**: List registered model versions.
- **Query Params**: `limit`, `market`.

### `POST /api/models/promote`
- **Description**: Update the stage (e.g., RECOMMENDED) of a model version.
- **Body**: `{ "version_id": "...", "stage": "..." }`

### `GET /api/runs`
- **Description**: List MLflow-style runs.
- **Query Params**: `limit`, `market`.

### `DELETE /api/runs/{id}`
- **Description**: Cascade delete a run, its artifacts, and its model registry entry.

---

## 4. Backtest
### `POST /api/backtest/run`
- **Description**: Trigger a re-backtest (no retrain) for a model.
- **Body**: `{ "market": "...", "model_path": "...", "start": "...", "end": "..." }`
- **Response**: `202 Accepted` with `job_id`.

### `GET /api/runs/{id}/curve`
- **Description**: Fetch equity curve (NAV/Drawdown) for a specific run.

---

## 5. Arena (擂台)
### `GET /api/arenas`
- **Description**: List available arenas.

### `GET /api/arena/participants`
- **Description**: List participants in an arena.
- **Query Params**: `arena_name` or `arena_id`.

### `POST /api/arena/participants`
- **Description**: Add a new participant (linked to `run_id`).
- **Body**: `{ "arena_name": "...", "run_id": "...", "name": "..." }`

### `GET /api/arena/leaderboard`
- **Description**: Get the latest or specific date leaderboard.
- **Query Params**: `arena_name`, `date`.

### `POST /api/arena/settle`
- **Description**: Trigger the daily settlement job for an arena.
- **Body**: `{ "market": "...", "date": "...", "seed_from_model_registry": true }`

---

## 6. Jobs & Reports
### `GET /api/jobs`
- **Description**: List background jobs.
- **Query Params**: `limit`, `status`.

### `GET /api/jobs/{id}/stream`
- **Description**: SSE (Server-Sent Events) stream for real-time job logs.

### `GET /api/reports`
- **Description**: List generated reports (HTML/PDF).

### `POST /api/reports/export`
- **Description**: Trigger a job to package reports into a ZIP.

---

## 7. Mapping to Design Doc v1.0
| Design Doc Endpoint | Current API | Status |
| :--- | :--- | :--- |
| `POST /data/snapshots` | `POST /api/data/update` | Equivalent |
| `POST /train/runs` | N/A | **GAP** (Handled via CLI Orchestrator) |
| `POST /backtests` | `POST /api/backtest/run` | Implemented |
| `POST /arena/daily/settle`| `POST /api/arena/settle` | Implemented |
| `POST /reports/export` | `POST /api/reports/export` | Implemented |
