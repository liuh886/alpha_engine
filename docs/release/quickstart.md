# AlphaEngine Quickstart

Get AlphaEngine running on a clean machine in under 10 minutes.

---

## Prerequisites

| Tool     | Version   | Install                                      |
|----------|-----------|----------------------------------------------|
| Python   | >= 3.10   | [python.org](https://www.python.org/)        |
| uv       | latest    | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` (Windows) |
| Node.js  | >= 18 LTS | [nodejs.org](https://nodejs.org/)            |
| npm      | >= 9      | Ships with Node.js                           |
| Git      | any       | [git-scm.com](https://git-scm.com/)         |

Optional but recommended:

- **PM2** for production process management: `npm install -g pm2`
- **Make** (ships with macOS/Linux; on Windows use Git Bash or WSL)

---

## 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/<your-org>/alpha_engine.git
cd alpha_engine

# Install Python dependencies (uv reads pyproject.toml + uv.lock)
uv sync

# Install frontend dependencies
cd qlib-dashboard
npm install
cd ..
```

`uv sync` creates a `.venv` automatically and installs all locked dependencies. No manual virtualenv step is needed.

---

## 2. Environment Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your values. The minimum required variables are:

```ini
# Required: dashboard authentication
TRADING_UI_USER=admin
TRADING_UI_PASSWORD=<pick-a-strong-password>

# Optional: AI features (chat agent)
OPENAI_API_KEY=sk-...

# Optional: override defaults
# API_PORT=8000
# ALPHA_ENGINE_ENV=development
# CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000
```

For local development you can use the development template instead:

```bash
cp .env.development.example .env
```

**Key environment variables reference:**

| Variable               | Default              | Description                              |
|------------------------|----------------------|------------------------------------------|
| `TRADING_UI_USER`      | (none, required)     | Dashboard login username                 |
| `TRADING_UI_PASSWORD`  | (none, required)     | Dashboard login password                 |
| `ALPHA_ENGINE_ENV`     | `development`        | `development` or `production`            |
| `API_PORT`             | `8000`               | API server listen port                   |
| `CORS_ORIGINS`         | localhost defaults   | Comma-separated allowed origins          |
| `OPENAI_API_KEY`       | (none)               | OpenAI key for the research/chat agent   |
| `DATABASE_URL`         | `sqlite:///data/local_market.db` | Market data database path  |
| `MARKET_DATA_PATH`     | `data/market`        | Raw market data directory                |
| `MODEL_REGISTRY_PATH`  | `artifacts/models`   | Trained model storage                    |

---

## 3. Build the Dashboard

Build the frontend so the API server can serve it as a static site:

```bash
cd qlib-dashboard
npm run build
cd ..
```

This produces `qlib-dashboard/dist/` which the API server mounts automatically.

---

## 4. Start the API Server

```bash
# Development mode (with auto-reload)
uv run python api_server.py

# Or using Make
make dev
```

The server starts at `http://localhost:8000`. Logs print to stdout.

### Start with PM2 (production / background)

```bash
pm2 start ecosystem.config.js
pm2 logs alpha-hub     # tail logs
pm2 stop alpha-hub     # stop the server
pm2 restart alpha-hub  # restart
```

On Windows the PM2 launcher uses `pythonw.exe` for a windowless process. On Linux/macOS it uses `uv run python api_server.py`.

---

## 5. Start the Dashboard Dev Server (optional)

If you want hot-reload during frontend development:

```bash
cd qlib-dashboard
npm run dev
```

The dev server starts at `http://localhost:5173` and proxies `/api` requests to the API server on port 8000.

For production, skip this step -- the API server serves the built dashboard at `http://localhost:8000`.

---

## 6. Smoke Test

### Health endpoint

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "version": "2.5.0"}
```

### Version endpoint

```bash
curl http://localhost:8000/api/public/version
```

### Authenticated endpoint

```bash
curl -u admin:your-password http://localhost:8000/api/system/me
```

Expected response:

```json
{"username": "admin"}
```

### Dashboard

Open `http://localhost:8000` in your browser. You should see the login prompt, then the strategy dashboard.

### Environment self-check

```bash
make doctor
```

This runs `scripts/doctor.py` which validates Python version, key dependencies, data directories, and configuration.

---

## 7. Makefile Commands Reference

Run `make help` to see all targets. Key commands:

| Command               | Description                                          |
|-----------------------|------------------------------------------------------|
| `make dev`            | Start dashboard dev server + API server in background|
| `make doctor`         | Run environment self-check                           |
| `make data`           | Update market data (default: CN market)              |
| `make train-cn`       | Train LGBM model for CN market                       |
| `make train-us`       | Train LGBM model for US market                       |
| `make train-cn-xgb`   | Train XGBoost model for CN market                    |
| `make train-us-xgb`   | Train XGBoost model for US market                    |
| `make walk-forward-cn`| Walk-forward validation for CN market                |
| `make walk-forward-us`| Walk-forward validation for US market                |
| `make backtest`       | Run zero-barrier backtest pipeline                   |
| `make breakfast`      | Generate daily morning trading report                |
| `make report`         | Generate latest backtest reports                     |
| `make lint`           | Format and lint with Ruff + Prettier                 |
| `make test`           | Run pytest test suite                                |
| `make typecheck`      | Run mypy type checking                               |
| `make clean`          | Remove generated files and caches                    |
| `make weekly-research`| Run full weekly research cycle                       |
| `make check-decay`    | Check active factors for alpha decay                 |
| `make weekly-report`  | Generate weekly research report                      |

---

## 8. Project Structure (overview)

```
alpha_engine/
  api_server.py            # FastAPI entry point (serves API + dashboard)
  pyproject.toml           # Python project metadata and dependencies
  uv.lock                  # Locked Python dependency versions
  ecosystem.config.js      # PM2 process configuration
  .env                     # Environment variables (git-ignored)
  Makefile                 # Task runner shortcuts
  configs/                 # Strategy profiles, workflow YAMLs, watchlists
  src/                     # Python source: agents, orchestrator, API routers
  scripts/                 # Data pipelines, doctor, reports
  qlib-dashboard/          # React + Vite frontend
    package.json
    vite.config.ts
    src/                   # Dashboard source (components, pages, store)
    dist/                  # Built frontend (generated by npm run build)
  artifacts/               # Models, runs, reports (generated, git-ignored)
  data/                    # Market data (generated, git-ignored)
  logs/                    # PM2 and server logs
```

---

## Troubleshooting

**Port already in use:**
Change the port with `API_PORT=8001 uv run python api_server.py` or set it in `.env`.

**`uv sync` fails:**
Ensure you have Python >= 3.10 on PATH. Run `uv python list` to check available versions.

**`npm install` fails:**
Ensure Node.js >= 18. Run `node --version` to verify.

**Dashboard shows blank page:**
Make sure you ran `npm run build` in `qlib-dashboard/` so the `dist/` directory exists.

**Auth errors on API calls:**
Verify `TRADING_UI_USER` and `TRADING_UI_PASSWORD` are set in `.env`.

**PM2 not found:**
Install globally: `npm install -g pm2`. On Windows, you may need to run the terminal as administrator.

**`make` not found on Windows:**
Use Git Bash, WSL, or run the underlying commands directly (e.g., `uv run python scripts/doctor.py` instead of `make doctor`).
