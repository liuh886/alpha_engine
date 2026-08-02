# HTTP Adapter Migration Matrix

Status: **Phase 2 — domain extraction**  
Parent: #316  
Delivery issue: #319

## Decision rule

An HTTP router is not a product boundary. Each router must be assigned one disposition:

1. **artifact-replaced** — read use case is covered by `alpha-engine-bundle.json` and the static/local PWA;
2. **browser-control-retired** — task, mutation or infrastructure control has no place in the browser;
3. **service-owned** — the router delegates to an existing pure Python service, script or workflow and the adapter may be deleted;
4. **extract-first** — material research-domain behavior still lives in the router and must move before deletion;
5. **dead/unmounted** — not part of the application and safe to delete.

## Router matrix

| Router | Read disposition | Write/execution disposition | Domain owner | Migration decision |
| --- | --- | --- | --- | --- |
| `artifacts.py` | Dashboard, comparison and generic JSON reads replaced by the versioned research bundle | none | artifact exporter and `ArtifactGateway` | delete in wave 1 |
| `reports.py` | Report index/files replaced by manifest-declared reports and notebooks | export job replaced by `scripts/export_reports_zip.py` and bundle export | `ReportService`, export scripts | delete in wave 1 |
| `jobs.py` | job status/log UI retired | cancel/rerun browser controls retired | CLI process and workflow owners | delete in wave 1 |
| `system.py` | health, paths and docs are local-server concerns; methodology is exported statically | panic and arbitrary dashboard task execution retired; canonical commands already live in CLI/workflows | `src.workflows.commands`, scripts, Make targets | delete in wave 1 |
| `chat.py` | no retained Web read use case | browser agent dispatch retired | `AgentRouter`, CLI/MCP owners | delete in wave 1 |
| `tools.py` | capabilities are not a Web product | browser tool execution retired | `ResearchAssistant`, MCP/CLI owners | delete in wave 1 |
| `arena.py` | leaderboard is optional research output and may be exported when needed | settle already owned by `scripts/arena_settle.py`; participant mutation is browser-only | `ArenaIndex`, `scripts/arena_settle.py` | delete in wave 1 |
| `strategy.py` | config listing/content and plugin metadata are repository/CLI concerns | browser save/compile/validate controls retired; compiler and registry already independent | `StrategyCompilerService`, `StrategyRegistry`, factor compiler | delete in wave 1 |
| `decision_desk.py` | no mounted route and no supported product use case | none | none | delete as dead code in wave 1 |
| `models.py` | model list/details replaced by bundle model index | promote/delete remain service operations; health diagnostic must move to doctor/report evidence | `ModelService`, `ModelRegistryIndex`, promotion contracts | wave 2: document non-HTTP ownership, then delete |
| `data.py` | status, lineage, completeness and names should be bundle evidence | update is CLI-owned; watchlist mutation and instrument sync are embedded and require extraction | `DataService`, snapshot/quality indexes, update scripts | extract-first |
| `backtest.py` | runs, curves, ledger and attribution should be exported bundle evidence | run/train/delete browser controls retired; services already exist | `BacktestService`, `TrainingService`, orchestrator | wave 2 after export coverage check |
| `walk_forward.py` | persisted result should be a declared artifact | in-memory job/persistence wrapper must become a pure Python runner/export path | `src.research.walk_forward` | extract-first |
| `workflow.py` | workflow status is governance evidence, not a live Web requirement | background execution maps to existing workflow hooks and research workflow | governance service, workflow hooks, research workflow | wave 2 after CLI ownership check |
| `portfolio.py` | portfolio check result should be an exported evidence artifact | no browser execution | portfolio constraint engine is mixed into router | extract-first, high risk |
| `factors.py` | factor evidence should be exported through the bundle | scans/attribution are research executions | factor analysis/scanner/attribution modules | extract request models/cache helpers to service/CLI, then delete |
| `research.py` | research records/results should be bundle evidence | research operations must be CLI/workflow-owned | research service/workflow modules | extract-first |
| `evidence.py` | evidence reads should be bundle-native | evidence generation belongs to research/release workflows | evidence ledger and release modules | verify coverage, then delete |
| `decay.py` | decay reports should be exported artifacts | computation belongs to factor research CLI/workflow | decay research modules | extract-first |
| `stock_analysis.py` | per-symbol inspection should be a generated report/artifact, not a live endpoint | analysis execution belongs to CLI/research workflow | asset inspection/research services | extract-first |

## Wave 1 deletion gates

Wave 1 may delete only adapters whose retained behavior already has a non-HTTP owner or whose browser behavior is explicitly retired.

Required checks:

- remove router imports and registrations from `api_server.py`;
- remove API-specific tests for deleted routes;
- keep underlying indexes, services, agents, scripts and workflows intact;
- do not alter Python research contracts;
- update the retirement inventory after CI passes;
- repository search must show no imports of deleted router modules.

## Target after wave 1

The temporary FastAPI process, while it still exists, exposes only routers awaiting domain extraction. No endpoint may be retained merely because an old frontend once called it.
