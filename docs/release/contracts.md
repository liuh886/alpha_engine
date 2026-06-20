# API / MCP / Dashboard Contract Freeze

Status: frozen for release candidate
Date: 2026-06-19

## API Endpoints

All endpoints are under `/api/` unless noted.

### Release (stable, contract-tested)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check, returns version |
| `/api/system/paths` | GET | Basic | System path info |
| `/api/system/exec` | POST | Basic | Execute safe commands (train/backtest/data_update/arena_settle) |
| `/api/system/panic` | POST | Basic | Stop all running jobs |
| `/api/research/runs` | GET | Basic | List research runs |
| `/api/research/run` | POST | Basic | Start research workflow |
| `/api/research/runs/{id}` | GET | Basic | Get run details |
| `/api/decay/check` | GET | Basic | Check factor decay |
| `/api/decay/factor/{name}` | GET | Basic | Check single factor |
| `/api/decay/apply` | POST | Basic | Apply decay changes |
| `/api/portfolio/check` | POST | Basic | Check portfolio constraints |
| `/api/portfolio/config` | GET | Basic | Get constraint config |
| `/api/data/status` | GET | Basic | Data freshness status |
| `/api/backtest/submit` | POST | Basic | Submit backtest job |
| `/api/backtest/jobs` | GET | Basic | List backtest jobs |
| `/api/backtest/jobs/{id}` | GET | Basic | Get job status |

### Experimental (may change)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/evidence/...` | Various | Basic | Evidence ledger queries |
| `/api/factors/...` | Various | Basic | Factor registry CRUD |

### Internal (not for external consumption)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/system/docs/main` | GET | Basic | Internal docs |
| `/api/system/docs/methodology` | GET | Basic | Methodology doc |
| `/api/thought_stream` | GET | None | Agent thought logs |

## MCP Tools

All tools require `ALPHA_DEVELOPER_TOKEN`.

### Release

| Tool | Description |
|------|-------------|
| `check_factor_decay` | Check factor IC decay |
| `get_portfolio_risk` | Get portfolio risk analysis |
| `run_research_workflow` | Run full research pipeline |
| `get_research_status` | Get research run status |
| `query_experiments` | Query experiment journal |

### Experimental

| Tool | Description |
|------|-------------|
| `discover_factor` | Discover and evaluate new factors |
| `scan_factor_pool` | Batch scan factor pool |
| `register_factor_for_strategy` | Register factor for strategy |
| `compile_strategy_with_factors` | Compile strategy with active factors |
| `attribute_factor_returns` | Attribute returns to factors |

## Dashboard Pages

### Release

| Page | Route | Description |
|------|-------|-------------|
| Overview | `/` | Main dashboard with key metrics |
| Models | `/models` | Model performance comparison |
| Backtest | `/backtest` | Backtest submission and results |
| Arena | `/arena` | Strategy competition |
| Data | `/data` | Data status and freshness |
| Docs | `/docs` | Documentation viewer |

### Experimental

| Page | Route | Description |
|------|-------|-------------|
| Factors | `/factors` | Factor registry browser |
| Attribution | `/attribution` | Factor attribution analysis |
| System | `/system` | System health and research runs |
| Compare | `/compare` | Side-by-side model comparison |

## Contract Tests

Release endpoints have contract tests in:
- `tests/test_api_contract.py`
- `tests/test_architecture_contract.py`
- `tests/test_research_workflow_contract.py`
- `tests/test_strategy_execution_contract.py`
- `tests/test_evidence_ledger.py`

## Breaking Change Policy

- Release endpoints: no breaking changes within a release version
- Experimental endpoints: may change with deprecation notice
- Internal endpoints: no stability guarantee
