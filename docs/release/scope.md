# Alpha Engine v1.0 -- Release Scope Freeze

> Frozen: 2026-06-19
> This document classifies every public surface of Alpha Engine as **release**, **experimental**, or **internal**.

## Classification Definitions

| Tag | Meaning |
|-----|---------|
| `release` | Stable, documented, supported in production. Breaking changes require a major version bump. |
| `experimental` | Functional but API may change without notice. Not covered by SLA. |
| `internal` | Operator / developer tooling. Not exposed to end users. May be removed or renamed at any time. |

---

## Supported Markets

| Market | Region Code | Benchmark | Data Source | Status |
|--------|-------------|-----------|-------------|--------|
| China A-shares | `cn` | CSI 300 (`000300`) | Qlib bin (watchlist universe) | `release` |
| US equities | `us` | QQQ | Qlib bin (watchlist universe) | `release` |
| Hong Kong | `hk` | -- | Watchlist only (no model) | `experimental` |

---

## Supported Strategies

| Strategy Class | Config Name | Rebalance | Status |
|----------------|-------------|-----------|--------|
| `BiweeklyTrendStrategy` | `biweekly_trend` | Every 10 trading days | `release` |
| `WeeklyQuantRatingStrategy` | `weekly_quant_rating` | Weekly | `experimental` |
| `DualLayerStrategy` | `dual_layer` | Per config | `experimental` |
| `VectorizedBiweeklyStrategy` | `vectorized` | Every 10 trading days | `experimental` |

---

## Supported Model Types

| Model Class | Module | Markets | Status |
|-------------|--------|---------|--------|
| `LGBModel` (LightGBM) | `qlib.contrib.model.gbdt` | CN, US | `release` |
| `XGBModel` (XGBoost) | `qlib.contrib.model.xgboost` | CN, US | `experimental` |

---

## API Endpoints

Base path: `/api`. All endpoints require authentication (`get_current_user`).

### Data (`/api/data`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/data/update` | Trigger data update job | `release` |
| `GET` | `/data/instruments` | List instruments for a market | `release` |
| `GET` | `/data/status` | Overall data status | `release` |
| `GET` | `/data/snapshots/latest` | Latest data snapshot | `release` |
| `GET` | `/data/quality/latest` | Latest data quality report | `release` |
| `GET` | `/data/stock/{symbol}` | Inspect stock data | `release` |
| `GET` | `/data/completeness` | Completeness/value matrix | `experimental` |
| `GET` | `/data/features` | Available features for heatmap | `experimental` |
| `GET` | `/data/integrity` | Data integrity checks | `experimental` |
| `GET` | `/data/name-map` | Ticker-to-name mapping | `release` |
| `GET` | `/data/watchlist` | Full watchlist grouped by market | `release` |
| `POST` | `/data/instruments/add` | Add symbols to watchlist | `release` |
| `POST` | `/data/instruments/remove` | Remove symbols from watchlist | `release` |

### Backtest (`/api/backtest`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/backtest/` | List backtest runs with metrics | `release` |
| `GET` | `/backtest/curve` | Equity curve (NAV, drawdown) | `release` |
| `GET` | `/backtest/compare` | Side-by-side equity curve comparison | `release` |
| `GET` | `/backtest/{run_id}/attribution` | Profit attribution | `release` |
| `GET` | `/backtest/{run_id}/ledger` | Trading ledger (holdings & trades) | `release` |
| `GET` | `/backtest/{run_id}/alpha-decomposition` | Alpha decomposition | `experimental` |
| `POST` | `/backtest/run` | Submit backtest job | `release` |
| `POST` | `/backtest/train/run` | Submit training job | `release` |
| `DELETE` | `/backtest/runs/{run_id}` | Delete a run | `release` |
| `POST` | `/backtest/walk-forward` | Walk-forward validation | `experimental` |
| `GET` | `/backtest/walk-forward/{job_id}` | Walk-forward results | `experimental` |

### Models (`/api/models`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/models/` | List model versions | `release` |
| `GET` | `/models/{version_id}` | Model version details | `release` |
| `POST` | `/models/promote` | Promote model to target stage | `release` |
| `POST` | `/models/delete` | Delete model version | `release` |
| `GET` | `/models/health` | Model health check | `release` |

### Reports (`/api/reports`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/reports/` | List reports | `release` |
| `GET` | `/reports/{report_id}` | Get specific report | `release` |
| `POST` | `/reports/export` | Export reports (background) | `release` |

### Jobs (`/api/jobs`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/jobs` | List jobs with status filter | `release` |
| `GET` | `/jobs/{job_id}` | Get job details | `release` |
| `GET` | `/jobs/{job_id}/stream` | SSE job log stream | `release` |

### Workflow (`/api/workflow`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/workflow/train` | Start training workflow | `release` |
| `POST` | `/workflow/backtest` | Start backtest workflow | `release` |
| `POST` | `/workflow/research-cycle` | Full research cycle | `experimental` |
| `GET` | `/workflow/status` | List workflow status | `release` |

### Strategy (`/api/strategy`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/strategy/compile` | NL to Qlib YAML compilation | `experimental` |
| `GET` | `/strategy/list` | List strategy config files | `release` |
| `GET` | `/strategy/content/{filename}` | Read strategy config | `release` |
| `POST` | `/strategy/save` | Save strategy config YAML | `release` |
| `POST` | `/strategy/compile-with-factors` | Compile with registered factors | `experimental` |
| `GET` | `/strategy/plugins` | List strategy plugins | `experimental` |
| `GET` | `/strategy/plugins/{name}/schema` | Plugin parameter schema | `experimental` |
| `POST` | `/strategy/plugins/{name}/validate` | Validate plugin params | `experimental` |
| `GET` | `/strategy/schema/{filename}` | Strategy schema definition | `experimental` |

### Factors (`/api/factors`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/factors/ic` | Full IC report | `release` |
| `GET` | `/factors/ic/top` | Top N factors by \|rank_ic\| | `release` |
| `GET` | `/factors/decay` | IC decay curve for a factor | `experimental` |
| `POST` | `/factors/scan` | Batch-scan factor expressions | `experimental` |
| `POST` | `/factors/attribute` | Factor return attribution (OLS) | `experimental` |
| `POST` | `/factors/attribute/rolling` | Rolling factor attribution | `experimental` |
| `GET` | `/factors/exists` | Check factor existence | `experimental` |
| `GET` | `/factors/registry` | List registry factors | `experimental` |
| `GET` | `/factors/registry/{factor_id}` | Factor detail | `experimental` |
| `POST` | `/factors/registry/{factor_id}/promote` | Promote factor lifecycle | `experimental` |
| `POST` | `/factors/registry/{factor_id}/demote` | Demote factor | `experimental` |
| `GET` | `/factors/experiments` | Query experiment journal | `experimental` |
| `GET` | `/factors/experiments/summary` | Experiment summary stats | `experimental` |
| `GET` | `/factors/experiments/failed` | List failed experiments | `experimental` |

### Stock Analysis (`/api/stock-analysis`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/stock-analysis/{symbol}/decision` | BUY/HOLD/SELL decision | `experimental` |
| `GET` | `/stock-analysis/{symbol}/factors` | Factor z-scores for a stock | `experimental` |
| `GET` | `/stock-analysis/watchlist/summary` | Signal overview for watchlist | `experimental` |
| `GET` | `/stock-analysis/data/freshness` | Data freshness check | `experimental` |
| `POST` | `/stock-analysis/portfolio/analysis` | Batch decision engine | `experimental` |
| `GET` | `/stock-analysis/{symbol}/history` | Historical signal log | `experimental` |
| `POST` | `/stock-analysis/nl-compile` | NL strategy to factor recs | `experimental` |
| `POST` | `/stock-analysis/{symbol}/record` | Record decision to history | `experimental` |
| `GET` | `/stock-analysis/{symbol}/signal-grade` | Signal grade (AAA-VVV) | `experimental` |
| `GET` | `/stock-analysis/{symbol}/signal-performance` | Signal perf by grade | `experimental` |
| `GET` | `/stock-analysis/{symbol}/signal-markers` | K-line chart markers | `experimental` |
| `GET` | `/stock-analysis/{symbol}/signal-daily` | Daily signal series | `experimental` |
| `GET` | `/stock-analysis/ranking` | Stock ranking by prediction | `experimental` |

### Arena (`/api/arena`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/arena/list` | List arenas | `experimental` |
| `GET` | `/arena/leaderboard` | Arena leaderboard | `experimental` |
| `POST` | `/arena/settle` | Trigger settlement job | `experimental` |
| `POST` | `/arena/participants` | Add participant | `experimental` |

### Artifacts (`/api/artifacts`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/artifacts/arena-leaderboard/{arena_id}` | Arena leaderboard artifact | `experimental` |
| `GET` | `/artifacts/{artifact_key}` | Generic artifact by key | `experimental` |

### Decay (`/api/decay`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/decay/check` | Check all Active factors for decay | `experimental` |
| `GET` | `/decay/factor/{factor_name}` | Single factor decay check | `experimental` |
| `POST` | `/decay/apply` | Apply decay status changes | `experimental` |

### Portfolio (`/api/portfolio`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/portfolio/check` | Check portfolio constraints | `experimental` |
| `GET` | `/portfolio/config` | Constraint configuration | `experimental` |

### Research (`/api/research`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/research/run` | Start research workflow run | `experimental` |
| `GET` | `/research/runs` | List research runs | `experimental` |
| `GET` | `/research/runs/{run_id}` | Research run details | `experimental` |
| `GET` | `/research/runs/{run_id}/steps` | Step-by-step status | `experimental` |

### Evidence (`/api/evidence`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/evidence/{subject_type}/{subject_id}` | Evidence bundle | `experimental` |

### Agent (`/api/agent`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/agent/chat` | Agent router chat dispatch | `experimental` |

### Tools (`/api/tools`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/tools/analyze-factors` | Factor analysis | `experimental` |
| `POST` | `/tools/suggest-hyperparams` | Hyperparameter suggestions | `experimental` |
| `POST` | `/tools/assess-risk` | Risk assessment | `experimental` |
| `GET` | `/tools/data-quality/{market}` | Data quality check | `experimental` |
| `POST` | `/tools/audit-run/{run_id}` | Audit backtest run | `experimental` |
| `GET` | `/tools/capabilities` | List available tools | `experimental` |
| `POST` | `/tools/chat` | NL interface to tools | `experimental` |

### System (`/api/system`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/system/thought_stream` | Agent thought logs | `internal` |
| `GET` | `/system/paths` | System path info | `internal` |
| `GET` | `/system/docs/main` | Main system doc (markdown) | `internal` |
| `GET` | `/system/docs/methodology` | Methodology doc (markdown) | `internal` |
| `POST` | `/system/panic` | Emergency stop all jobs | `internal` |
| `POST` | `/system/exec` | Execute whitelisted command | `internal` |

---

## MCP Tools

Server: `AlphaEngine Trading Assistant` (stdio transport).

| Tool | Description | Status |
|------|-------------|--------|
| `get_market_signals` | Run inference, detect data gaps | `release` |
| `repair_market_data` | Fix data gaps with lookback | `release` |
| `run_backtest` | Run strategy backtest | `release` |
| `diagnose_platform` | Doctor diagnostic script | `release` |
| `update_market_data` | Update market data for region | `release` |
| `define_factor` | Register factor expression (Proposed) | `experimental` |
| `evaluate_factor` | Evaluate factor: IC, decay, quintiles | `experimental` |
| `validate_factor` | Validate and promote factor | `experimental` |
| `register_factor_for_strategy` | Register Validated factor for strategy | `experimental` |
| `discover_factor` | Full lifecycle: register-evaluate-validate-promote | `experimental` |
| `scan_factor_pool` | Scan factor pool against gates | `experimental` |
| `load_factor_pool` | Load factor pool from YAML | `experimental` |
| `get_factor_library` | Return 200+ factor expressions as JSON | `experimental` |
| `compile_strategy_with_factors` | Compile strategy YAML with Active factors | `experimental` |
| `attribute_factor_returns` | Cross-sectional factor attribution (OLS) | `experimental` |
| `attribute_returns_rolling` | Rolling factor attribution | `experimental` |
| `parse_research_goal` | NL goal to structured JSON task | `experimental` |
| `query_experiments` | Query experiment journal | `experimental` |
| `run_research_cycle` | Full automated research cycle | `experimental` |
| `run_iterative_research` | Multi-cycle iteration to target Sharpe | `experimental` |
| `compare_models_with_fdr` | FDR-corrected model comparison | `experimental` |
| `validate_model_batch` | FDR-corrected batch validation (T-04) | `experimental` |

---

## Dashboard Pages

All pages are hash-routed (`/#/path`). The dashboard is a single-page React app served from the API server.

| Route | Component | Description | Status |
|-------|-----------|-------------|--------|
| `/dashboard` | (default) | Overview / landing | `release` |
| `/backtest` | `BacktestPage` | Launch backtests, view results, charts | `release` |
| `/models` | `ModelsPage` | Model registry, promote, delete | `release` |
| `/compare` | `ComparePage` | Side-by-side run comparison | `release` |
| `/reports` | `ReportsPage` | Report browser with download | `release` |
| `/data` | `DataPage` | Watchlist management, data updates, heatmap | `release` |
| `/factors` | `FactorPage` | Factor IC analysis | `release` |
| `/docs` | `DocsPage` | Documentation viewer | `release` |
| `/terminal` | `StockTerminal` | Individual stock analysis, signal grading | `experimental` |
| `/arena` | `ArenaPage` | Model arena leaderboard | `experimental` |
| `/factor-registry` | `FactorRegistryPage` | Factor lifecycle registry | `experimental` |
| `/experiments` | `ExperimentLogPage` | Experiment log browser | `experimental` |
| `/attribution` | `AttributionPage` | Factor return attribution | `experimental` |
| `/strategy` | `StrategyPage` | Strategy spec viewer | `experimental` |
| `/methodology` | `MethodologyPage` | Training methodology doc | `experimental` |
| `/system` | `SystemPage` | Research runs, factor decay monitor | `internal` |
| `/agent` | `AgentControlCenter` | AI agent chat + quick actions | `internal` |

---

## CLI Scripts (Operator Tooling)

All scripts under `scripts/` are **internal** operator tools. None are part of the public API surface.

| Script | Purpose |
|--------|---------|
| `daily_run.py` | Scheduled daily data + training + backtest pipeline |
| `collect_data.py` | Data collection from upstream sources |
| `dump_bin.py` | Convert CSV data to Qlib binary format |
| `run_agents_pipeline.py` | Run the full agent research pipeline |
| `doctor.py` | Platform health diagnostics |
| `build_dashboard_db.py` | Build dashboard SQLite database |
| `arena_settle.py` | Arena settlement logic |
| `check_factor_decay.py` | CLI factor decay check |
| `generate_arena_report.py` | Generate arena daily report |
| `generate_weekly_report.py` | Generate weekly summary report |
| `weekly_research.py` | Automated weekly research cycle |
| `export_reports_zip.py` | Archive reports to ZIP |
| `e2e_smoke.py` | End-to-end smoke test |

---

## Non-Goals (Explicitly Out of Scope)

1. **Real-time trading / order execution.** Alpha Engine is a research and backtesting platform. It does not connect to brokerages or execute live trades.
2. **Options, futures, or derivatives.** Only equity (stock) markets are supported.
3. **Multi-tenant SaaS deployment.** The platform is single-tenant; authentication is a gate, not a tenant boundary.
4. **Streaming market data (tick/L2).** All data is daily OHLCV ingested in batch.
5. **Mobile dashboard.** The frontend is desktop-only (1024px+ viewport).
6. **Guaranteed model performance.** All backtest results are historical simulations. Past performance does not predict future returns.
7. **Third-party strategy marketplace.** The plugin system is internal; there is no public plugin distribution mechanism.
8. **Cryptocurrency or FX markets.** Only CN A-shares and US equities are supported.
9. **Automated position sizing / risk limits enforcement in production.** Portfolio constraints are advisory checks, not hard execution gates.
10. **Multi-language internationalization.** The UI and documentation are English-only (with Chinese ticker names where applicable).

---

## Versioning Policy

- **API endpoints** follow semantic versioning. `release` endpoints will not have breaking changes within a major version.
- **MCP tools** follow the same version as the server (`AlphaEngine Trading Assistant`).
- **Dashboard** is versioned with the API server; no independent version.
- **Experimental** surfaces may change or be removed in any minor version.
- **Internal** surfaces have no stability guarantees.
