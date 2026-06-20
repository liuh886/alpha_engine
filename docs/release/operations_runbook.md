# Alpha Engine Operations Runbook

Runtime observability, failure diagnosis, and recovery procedures for Alpha Engine.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Inspecting Running Jobs](#inspecting-running-jobs)
3. [Streaming and Viewing Logs](#streaming-and-viewing-logs)
4. [Stopping a Job](#stopping-a-job)
5. [Understanding Failure Causes](#understanding-failure-causes)
6. [Rerunning Safely](#rerunning-safely)
7. [PM2 Management Commands](#pm2-management-commands)
8. [Common Recovery Scenarios](#common-recovery-scenarios)

---

## System Overview

Alpha Engine runs as a single PM2-managed process (`alpha-hub`) that serves the FastAPI API server and spawns child threads for job execution. All paths below are relative to `PROJECT_ROOT` (the repository root).

### Key Paths

| Purpose | Path |
|---|---|
| API server entry | `api_server.py` (Linux) / `pm2_launcher.pyw` (Windows) |
| PM2 config | `ecosystem.config.js` |
| Job metadata DB | `artifacts/metadata.db` |
| Job run logs | `artifacts/runs/dashboard_exec_<job_id>.log` |
| PM2 stdout log | `logs/alpha-hub-out.log` |
| PM2 stderr log | `logs/alpha-hub-err.log` |
| Failure log (governance) | `artifacts/governance/failure_log.json` |
| Agent thought stream | `artifacts/agent_thought_stream.json` |
| MLflow runs | `artifacts/mlruns/` |
| Trained models | `artifacts/models/` |

Use `GET /api/system/paths` to retrieve the resolved paths at runtime (requires auth).

---

## Inspecting Running Jobs

### Via API

**List all jobs (most recent first):**

```
GET /api/jobs?limit=100
```

Filter by status:

```
GET /api/jobs?status=running
GET /api/jobs?status=failed
GET /api/jobs?status=succeeded
```

**Get a single job by ID:**

```
GET /api/jobs/{job_id}
```

Response includes: `id`, `type`, `status`, `created_at`, `started_at`, `finished_at`, `exit_code`, `error`, `log_path`, `commands`, `command_envelopes`.

### Via Database Directly

The job metadata lives in an SQLite database at `artifacts/metadata.db`:

```bash
sqlite3 artifacts/metadata.db "SELECT id, type, status, created_at, exit_code FROM jobs ORDER BY created_at DESC LIMIT 20;"
```

Check only running jobs:

```bash
sqlite3 artifacts/metadata.db "SELECT id, type, started_at FROM jobs WHERE status = 'running';"
```

### Via Dashboard

The web dashboard at `http://localhost:8000` provides a visual job queue with real-time status updates and log streaming.

---

## Streaming and Viewing Logs

### Real-Time Job Log Streaming (SSE)

Each job has a Server-Sent Events endpoint that streams log output in real time:

```
GET /api/jobs/{job_id}/stream
```

This endpoint:
- Streams new log lines as they are written to the job's log file
- Sends a `done` event when the job reaches `succeeded` or `failed` status
- Sends keep-alive comments every 500ms while the job is running

Example with `curl`:

```bash
curl -N http://localhost:8000/api/jobs/{job_id}/stream
```

### Job Log Files

Each job writes its combined stdout/stderr to:

```
artifacts/runs/dashboard_exec_{job_id}.log
```

View a completed job's log:

```bash
cat artifacts/runs/dashboard_exec_{job_id}.log
```

Tail a running job's log:

```bash
tail -f artifacts/runs/dashboard_exec_{job_id}.log
```

### PM2 Logs

PM2 captures the API server's own stdout/stderr (separate from job logs):

```bash
# View last 100 lines
pm2 logs alpha-hub --lines 100

# Follow in real time
pm2 logs alpha-hub --nostream

# Log file locations (defined in ecosystem.config.js)
# Windows: logs/alpha-hub-out.log, logs/alpha-hub-err.log
```

### Application Logs (structlog)

The API server uses structured logging (structlog with JSON output in production, console renderer in development). Logs go to stderr and are captured by PM2 into `logs/alpha-hub-err.log`.

### Agent Thought Stream

View the latest agent reasoning steps:

```
GET /api/system/thought_stream?limit=50
```

Or read directly:

```bash
cat artifacts/agent_thought_stream.json
```

---

## Stopping a Job

### Panic Stop (Kill All Running Jobs)

The panic endpoint immediately marks all running jobs as failed and attempts to kill their OS processes:

```
POST /api/system/panic
```

Optional body:

```json
{"reason": "Manual intervention required"}
```

Response:

```json
{
  "ok": true,
  "halted_jobs": 2,
  "total_marked_failed": 2,
  "reason": "Manual intervention required",
  "triggered_at": 1718800000.0
}
```

What happens internally:
1. All jobs with `status = "running"` are set to `status = "failed"` with `exit_code = -2` and `error = "SYSTEM_PANIC: <reason>"`
2. For each job, `kill_job()` is called to terminate the OS process (SIGTERM on Linux, `proc.terminate()` on Windows)
3. Running job threads detect the panic state and exit gracefully

### Single Job Kill

There is no per-job kill endpoint. To kill a single job:

1. Find the job's PID by checking the process tree (see PM2 management below)
2. Or use the panic endpoint and then manually reset unrelated jobs back to their previous state in the database

### Force Kill via OS

If a job process is stuck and not responding to SIGTERM:

```bash
# Linux: find and kill
ps aux | grep "dashboard_exec\|collect_data\|arena_settle"
kill -9 <pid>

# Windows: find and kill
tasklist | findstr python
taskkill /PID <pid> /F
```

---

## Understanding Failure Causes

### Failure Classification System

The reliability module (`src/reliability/`) classifies failures into structured error codes. When a job fails, the system:

1. Classifies the failure via `classify_failure()` in `src/reliability/classifier.py`
2. Assigns a governance action via `GovernanceReliabilityPolicy` in `src/reliability/governance_policy.py`
3. Logs the event to `artifacts/governance/failure_log.json`

### Error Code Reference

| Code | Category | Severity | Retryable | Default Action |
|---|---|---|---|---|
| `ERR_DATA_GAP` | data | high | yes | `refresh_data_then_retry` |
| `ERR_PROVIDER_TIMEOUT` | provider | medium | yes | `retry_with_backoff` |
| `ERR_PROVIDER_PAYLOAD_INVALID` | provider | medium | yes | `rotate_provider` |
| `ERR_FEATURE_DRIFT` | features | high | no | `recompute_alignment` |
| `ERR_MODEL_STALE` | model | high | no | `schedule_retrain` |
| `ERR_MODEL_MISSING` | model | high | no | `resolve_from_registry` |
| `ERR_BACKTEST_CACHE_MISS` | cache | low | no | `compute_and_populate` |
| `ERR_BACKTEST_ARTIFACT_MISSING` | artifacts | medium | yes | `rebuild_artifacts` |
| `ERR_QLIB_INIT_CONFLICT` | runtime | medium | yes | `reroute_to_isolated_process` |
| `ERR_PIPELINE_SUBPROCESS_FAILED` | runtime | medium | yes | `classify_and_retry` |
| `ERR_GOVERNANCE_STORAGE_UNAVAILABLE` | governance | medium | yes | `fallback_to_json_log` |

### Reading the Failure Log

```bash
cat artifacts/governance/failure_log.json | python -m json.tool
```

Each event contains:

- `event_id` -- unique identifier for the failure instance
- `code` -- one of the error codes above
- `severity` -- `low`, `medium`, or `high`
- `retryable` -- whether automatic retry is safe
- `component` -- which subsystem failed (e.g., `data_pipeline`, `model_trainer`)
- `operation` -- what was being attempted
- `summary` -- human-readable description
- `details.stderr_tail` -- last 500 chars of stderr
- `details.returncode` -- process exit code
- `governance_action.action` -- recommended recovery action
- `governance_action.status` -- `pending` or `resolved`
- `status` -- `open` or `resolved`

### Classifying Patterns in Job Errors

From the job's error field (viewable via `GET /api/jobs/{job_id}`):

- `SYSTEM_PANIC:` prefix -- job was killed by panic stop
- `Stale job (likely crashed)` -- job was running when the process died; auto-detected by `repair_jobs()` after 24 hours
- `Command failed:` prefix with stderr -- normal subprocess failure; check stderr for the root cause
- `Exception:` prefix with traceback -- Python-level error in the job runner itself

### Resolving Failure Events

After fixing a failure, mark it resolved in the failure log:

```python
from src.reliability.failure_log import resolve_failure_event

resolve_failure_event(
    "your-event-id",
    resolution={"notes": "Fixed by refreshing data", "resolved_by": "operator_name"}
)
```

---

## Rerunning Safely

### Check Prerequisites Before Rerunning

1. **Data freshness**: Ensure market data is up to date before rerunning a train or backtest job that failed due to `ERR_DATA_GAP`.

2. **No conflicting runs**: Check that no other job of the same type is already running:

   ```
   GET /api/jobs?status=running
   ```

3. **Stale job cleanup**: If the previous job shows `status = "running"` but the process is actually dead, the system auto-repairs jobs older than 24 hours via `repair_jobs()`. To force cleanup immediately, update the database:

   ```sql
   UPDATE jobs SET status = 'failed', error = 'Manually cleaned up'
   WHERE status = 'running' AND id = '<stale-job-id>';
   ```

### Rerun via API

**Data update (safe, idempotent):**

```
POST /api/system/exec
{"task": "data_update", "args": []}
```

**Arena settlement:**

```
POST /api/system/exec
{"task": "arena_settle", "args": []}
```

**Train a model:**

```
POST /api/system/exec
{"task": "train", "args": ["--market", "cn", "--model_type", "lgbm"]}
```

**Backtest:**

```
POST /api/system/exec
{"task": "backtest", "args": ["--market", "cn", "--model_type", "lgbm"]}
```

### Rerun via Command Line

If the API is unreachable, run the underlying scripts directly:

```bash
# Data update
uv run python scripts/collect_data.py

# Arena settlement
uv run python scripts/arena_settle.py

# Train (example: CN market, LightGBM)
uv run python -m src.workflows.train --market cn --model_type lgbm

# Backtest
uv run python -m src.workflows.backtest --market cn --model_type lgbm
```

### Allowed Tasks Only

The `/api/system/exec` endpoint only accepts these task keys:

- `data_update` -- runs `scripts/collect_data.py`
- `arena_settle` -- runs `scripts/arena_settle.py`
- `train` -- runs the training workflow via `WorkflowCommandEnvelope`
- `backtest` -- runs the backtest workflow via `WorkflowCommandEnvelope`

Any other task key returns HTTP 400. This is a security boundary -- do not bypass it.

---

## PM2 Management Commands

PM2 manages the `alpha-hub` process (the API server). Job subprocesses are spawned by the API server, not by PM2 directly.

### Basic Operations

```bash
# Check process status
pm2 status

# View process details
pm2 show alpha-hub

# Restart the API server (graceful, 5s timeout)
pm2 restart alpha-hub

# Stop the API server
pm2 stop alpha-hub

# Start after a stop
pm2 start ecosystem.config.js

# Reload (zero-downtime restart, if applicable)
pm2 reload alpha-hub

# Delete from PM2 process list
pm2 delete alpha-hub
```

### Log Management

```bash
# View recent logs
pm2 logs alpha-hub --lines 50

# Clear log files
pm2 flush alpha-hub

# Log file locations
#   logs/alpha-hub-out.log  (stdout)
#   logs/alpha-hub-err.log  (stderr + structlog JSON)
```

### Monitoring

```bash
# Real-time CPU/memory dashboard
pm2 monit

# Process list with details
pm2 list
```

### PM2 Configuration Notes

From `ecosystem.config.js`:

- **Max memory**: 2 GB (`max_memory_restart: '2G'`) -- PM2 auto-restarts if memory exceeds this
- **Max restarts**: 10 (`max_restarts: 10`) -- PM2 stops trying after 10 consecutive crashes
- **Min uptime**: 5 seconds (`min_uptime: 5000`) -- process must run at least 5s to count as "started"
- **Kill timeout**: 5 seconds (`kill_timeout: 5000`) -- graceful shutdown window before SIGKILL
- **Listen timeout**: 5 seconds (`listen_timeout: 5000`) -- how long to wait for the app to be ready

### Windows-Specific Notes

On Windows, PM2 launches `pm2_launcher.pyw` via `pythonw.exe` (no console window). The Python executable path is `.venv/Scripts/pythonw.exe`. If the venv is missing or corrupted, PM2 will fail to start -- recreate it with `uv sync`.

---

## Common Recovery Scenarios

### Scenario 1: Job Shows "running" but Process Is Dead

**Symptom**: Job appears running in the dashboard/API but is clearly not producing output. The process may have crashed without updating the database.

**Diagnosis**:

```bash
# Check if the log file is still growing
ls -la artifacts/runs/dashboard_exec_{job_id}.log
# Wait 10 seconds, check again
```

**Recovery**:

Wait for automatic repair (24 hours) or manually mark as failed:

```sql
sqlite3 artifacts/metadata.db \
  "UPDATE jobs SET status = 'failed', error = 'Stale job - manually cleaned up'
   WHERE id = '{job_id}';"
```

### Scenario 2: All Jobs Halted / System in Bad State

**Symptom**: Multiple jobs failing, dashboard unresponsive to normal operations.

**Recovery**:

1. Use the panic stop to halt everything:

   ```
   POST /api/system/panic
   {"reason": "System recovery - clearing all jobs"}
   ```

2. If the API is unreachable, restart PM2:

   ```bash
   pm2 restart alpha-hub
   ```

3. If PM2 restart fails, stop and start fresh:

   ```bash
   pm2 stop alpha-hub
   pm2 delete alpha-hub
   pm2 start ecosystem.config.js
   ```

4. Verify health:

   ```bash
   curl http://localhost:8000/health
   ```

### Scenario 3: Data Gap Failures (ERR_DATA_GAP)

**Symptom**: Train or backtest jobs fail with `ERR_DATA_GAP`. The failure log shows `empty universe`, `no tickers`, or `qlib data not found`.

**Recovery**:

1. Run data update first:

   ```
   POST /api/system/exec
   {"task": "data_update", "args": []}
   ```

2. Wait for data update to complete (monitor via `GET /api/jobs?status=running`).

3. Retry the original operation:

   ```
   POST /api/system/exec
   {"task": "train", "args": ["--market", "cn", "--model_type", "lgbm"]}
   ```

### Scenario 4: Qlib Initialization Conflict (ERR_QLIB_INIT_CONFLICT)

**Symptom**: Failure with `already initialized` in stderr. Two jobs tried to initialize Qlib simultaneously.

**Recovery**: The system handles this automatically by isolating future jobs into subprocesses. If it persists:

1. Ensure only one train/backtest job runs at a time
2. Use the panic stop to clear concurrent jobs
3. Retry the single desired job

### Scenario 5: Model Missing (ERR_MODEL_MISSING)

**Symptom**: Backtest or prediction job fails because a `.pkl` model file is not found.

**Recovery**: This is not retryable without retraining.

1. Check if the model exists in `artifacts/models/`
2. If missing, run a training job first
3. Then retry the backtest

### Scenario 6: PM2 Process Keeps Restarting

**Symptom**: `pm2 status` shows the process in `errored` or constantly restarting state.

**Diagnosis**:

```bash
pm2 logs alpha-hub --lines 200
```

**Common causes and fixes**:

| Symptom in logs | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | Missing Python dependency | `uv sync` then `pm2 restart alpha-hub` |
| `OSError: [Errno 98] Address already in use` | Port 8000 occupied | Kill the conflicting process or change `PORT` env var |
| `MemoryError` / PM2 auto-restart | Memory exceeds 2GB | Check for memory leaks; increase `max_memory_restart` if needed |
| `Permission denied` | File permission issue | Check ownership of `artifacts/`, `logs/`, `data/` directories |

### Scenario 7: Webhook Alerts Not Sending

**Symptom**: Job failures happen but no webhook notification arrives.

**Diagnosis**: Check that `TRADING_WEBHOOK_URL` is set:

```bash
# Linux
echo $TRADING_WEBHOOK_URL

# Windows PowerShell
$env:TRADING_WEBHOOK_URL
```

If not set, the webhook silently does nothing (by design). Set it in `.env` or the environment.

### Scenario 8: Dashboard Shows No Data / Empty State

**Symptom**: The web UI loads but shows empty charts, no jobs, no models.

**Diagnosis**:

1. Check if `artifacts/` directory and its databases exist
2. Run `GET /api/system/paths` to verify all paths resolve
3. Check `artifacts/metadata.db` has a `jobs` table:

   ```bash
   sqlite3 artifacts/metadata.db ".tables"
   ```

**Recovery**: The database schema is auto-created on first use. If the database is corrupted:

```bash
mv artifacts/metadata.db artifacts/metadata.db.bak
# Restart the server -- it will recreate the schema
pm2 restart alpha-hub
```

---

## Quick Reference Card

| Action | Command |
|---|---|
| Health check | `curl http://localhost:8000/health` |
| List running jobs | `GET /api/jobs?status=running` |
| Stream job log | `GET /api/jobs/{id}/stream` |
| Kill all jobs | `POST /api/system/panic` |
| Run data update | `POST /api/system/exec {"task": "data_update"}` |
| Run training | `POST /api/system/exec {"task": "train", "args": ["--market", "cn", "--model_type", "lgbm"]}` |
| View failure log | `cat artifacts/governance/failure_log.json` |
| PM2 status | `pm2 status` |
| PM2 restart | `pm2 restart alpha-hub` |
| PM2 logs | `pm2 logs alpha-hub --lines 100` |
| View system paths | `GET /api/system/paths` |
