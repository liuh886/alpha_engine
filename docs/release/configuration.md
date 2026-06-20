# Configuration Reference

Alpha Engine reads its configuration from environment variables, typically
loaded from a `.env` file in the project root via `python-dotenv`.  Every
variable has a built-in default, so a bare `python api_server.py` works
out of the box for local development.

## Quick Start

```bash
cp .env.example .env
# Edit .env — set at least TRADING_UI_USER and TRADING_UI_PASSWORD for production.
```

---

## Core

| Variable | Default | Description |
|---|---|---|
| `ALPHA_ENGINE_ENV` | `development` | Set to `production` to disable verbose logging and enable stricter defaults. |
| `API_HOST` | `0.0.0.0` | Network interface the API server binds to. Use `127.0.0.1` to restrict to localhost. |
| `API_PORT` | `8000` | API server port. Also reads `PORT` as a fallback (for PaaS platforms like Heroku). |
| `CORS_ORIGINS` | `http://localhost:5173, http://127.0.0.1:5173, http://localhost:8000, http://127.0.0.1:8000` | Comma-separated list of allowed CORS origins. Also reads `ALLOWED_ORIGINS`. |

### Environment Modes

- **development** (default): Verbose logging, permissive CORS defaults.
- **production**: Structured logging, tighter security posture.  Always set
  `TRADING_UI_USER` and `TRADING_UI_PASSWORD` in production — the API returns
  HTTP 500 on all protected endpoints when credentials are missing.

---

## Authentication

| Variable | Default | Required? | Description |
|---|---|---|---|
| `TRADING_UI_USER` | *(none)* | Yes (production) | Username for HTTP Basic Auth on all `/api/*` routes. |
| `TRADING_UI_PASSWORD` | *(none)* | Yes (production) | Password for HTTP Basic Auth. |
| `ALPHA_DEVELOPER_TOKEN` | *(none)* | No | Token required by MCP tools. When unset, MCP tools accept any request (development mode). |

### How Auth Works

The API uses HTTP Basic Authentication on every router except `/health` and
`/api/public/*`.  If either `TRADING_UI_USER` or `TRADING_UI_PASSWORD` is
unset, protected endpoints return 500 with a message instructing you to set
the variables.  This is intentional — the server fails closed rather than
running unauthenticated in production.

MCP tool authentication is separate: each tool accepts a `token` parameter
that is compared against `ALPHA_DEVELOPER_TOKEN`.  When the env var is unset,
all tokens are accepted.

---

## Path Overrides

All paths default to project-relative directories. Override them for custom
layouts, Docker volumes, or multi-instance deployments.

| Variable | Default | Description |
|---|---|---|
| `TRADING_CONFIG_DIR` | `configs/` | Strategy and workflow YAML configuration files. |
| `TRADING_DATA_DIR` | `data/` | Market data storage. |
| `TRADING_REPORTS_DIR` | `reports/` | Generated backtest and analysis reports. |
| `TRADING_SCRIPTS_DIR` | `scripts/` | Operational scripts (data update, doctor, etc.). |
| `TRADING_ARTIFACTS_DIR` | `artifacts/` | MLflow runs, model checkpoints, factor registry DB. |
| `TRADING_STATIC_SITE_DIR` | `qlib-dashboard/dist/` | Built frontend assets served by the API. |
| `TRADING_ASSISTANT_METADATA_DB_PATH` | `artifacts/metadata/metadata.db` | Override the metadata SQLite database path used by the job service, model registry, and other indices. |

Relative paths are resolved against the project root (the directory containing
`api_server.py`).

### Derived Directories

Several subdirectories are derived from `TRADING_ARTIFACTS_DIR` at runtime:

- `{artifacts_dir}/mlruns` — MLflow experiment tracking
- `{artifacts_dir}/models` — Serialized model artifacts
- `{artifacts_dir}/runs` — Backtest run outputs
- `{artifacts_dir}/archives` — Archived data snapshots

---

## Risk and Limits

| Variable | Default | Description |
|---|---|---|
| `ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD` | `0.15` | Maximum drawdown (as a decimal) before the risk monitor triggers alerts. Value of `0.15` means 15%. |
| `SCORING_TIMEOUT_SEC` | `60` | Timeout in seconds for model scoring/inference operations. |
| `MAX_LEVERAGE` | `1.0` | Maximum portfolio leverage multiplier. `1.0` means no leverage. |

---

## Integrations

| Variable | Default | When Needed |
|---|---|---|
| `OPENAI_API_KEY` | *(none)* | Required only when using the research assistant LLM features. |
| `DATABASE_URL` | *(none)* | Connection string for extended analytics storage. Falls back to SQLite if unset. |
| `TRADING_WEBHOOK_URL` | *(none)* | Slack-compatible webhook URL. When set, job failure alerts are POSTed as JSON payloads. |

---

## PM2 / Systemd Deployment

When running under PM2, environment variables can be set in `ecosystem.config.js`
under the `env` block. The bundled config sets:

```javascript
env: {
    PYTHONPATH: baseDir,
    PORT: 8000,
    TRADING_STATIC_SITE_DIR: "qlib-dashboard/dist",
    PYTHONUNBUFFERED: "1",
}
```

Additional variables (auth credentials, API keys) should go in `.env` which is
loaded automatically by `python-dotenv` at startup.

---

## Verification Checklist

Before deploying to production:

1. **Auth is set**: `TRADING_UI_USER` and `TRADING_UI_PASSWORD` are both non-empty.
2. **No secrets in git**: `.env` is listed in `.gitignore`. Only `.env.example` is committed.
3. **Paths exist**: All overridden path directories exist and are writable by the process.
4. **CORS is locked down**: `CORS_ORIGINS` contains only your actual frontend origin(s).
5. **MCP token is set**: `ALPHA_DEVELOPER_TOKEN` is configured if the MCP server is exposed.

---

## Variable Source Map

This table shows where each variable is read in the codebase:

| Variable | Source File |
|---|---|
| `ALPHA_ENGINE_ENV` | `src/common/runtime_settings.py` |
| `API_HOST` | `src/common/runtime_settings.py` |
| `API_PORT` / `PORT` | `src/common/runtime_settings.py` |
| `CORS_ORIGINS` / `ALLOWED_ORIGINS` | `src/common/runtime_settings.py` |
| `TRADING_UI_USER` | `src/common/runtime_settings.py` |
| `TRADING_UI_PASSWORD` | `src/common/runtime_settings.py` |
| `TRADING_CONFIG_DIR` | `src/common/runtime_settings.py` |
| `TRADING_DATA_DIR` | `src/common/runtime_settings.py` |
| `TRADING_REPORTS_DIR` | `src/common/runtime_settings.py` |
| `TRADING_SCRIPTS_DIR` | `src/common/runtime_settings.py` |
| `TRADING_ARTIFACTS_DIR` | `src/common/runtime_settings.py` |
| `TRADING_STATIC_SITE_DIR` | `src/common/runtime_settings.py` |
| `ALPHA_DEVELOPER_TOKEN` | `src/api/mcp_server.py` |
| `ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD` | `src/guardrails/risk_monitor.py` |
| `TRADING_ASSISTANT_METADATA_DB_PATH` | `src/assistant/metadata_db.py` |
| `TRADING_WEBHOOK_URL` | `src/assistant/job_service.py` |
