# HTTP Adapter Migration Matrix

Status: **Completed**  
Parent: #316  
Delivery: #319, PRs #336 and #337

## Final decision rule

The browser is not an execution boundary. Every former HTTP use case was resolved as one of:

1. **artifact-replaced** — read use case is represented in `alpha-engine-bundle.json`;
2. **browser-control-retired** — mutation, task and infrastructure controls were removed;
3. **service-owned** — retained behavior has a Python service, CLI, script or workflow owner;
4. **dead/unmounted** — unused adapter code was deleted.

## Final disposition

| Former area | Read disposition | Execution disposition | Retained owner |
| --- | --- | --- | --- |
| Artifacts and reports | Manifest-declared bundle files | Export scripts and workflows | `ArtifactGateway`, `ReportService`, bundle exporter |
| Jobs and system controls | Not a browser product concern | CLI process, scheduler or workflow owner | Python scripts, Make targets, GitHub Actions |
| Chat, tools and agent controls | No browser execution surface | Optional CLI/MCP research tools | `ResearchAssistant`, MCP JSON-RPC integration |
| Arena and strategy administration | Export only when research evidence requires it | Standalone scripts and services | `ArenaIndex`, strategy services |
| Models | Bundle model index and metrics | Promotion and registry operations remain Python-owned | `ModelService`, `ModelRegistryIndex`, promotion contracts |
| Data | Bundle scope, lineage, coverage and quality evidence | Refresh and repair via CLI/workflows | `DataService`, Snapshot and quality indexes |
| Backtests and walk-forward | Curves, holdings, metrics and validation artifacts | Orchestrator and research modules | `BacktestService`, `TrainingService`, `src.research.walk_forward` |
| Portfolio and factors | Exported constraints, importance and diagnostics | Python research modules | Portfolio constraint engine, factor scanner/evaluator/attribution |
| Research and evidence | Bundle records, reports and notebooks | Spec-bound workflow and evidence ledger | Research workflow, Evidence Ledger |
| Decay and stock analysis | Generated research artifacts | Python scripts/workflows | Factor decay and asset-inspection modules |

## Verification evidence

- all HTTP router and schema files are deleted;
- the temporary Python Web host is deleted;
- frontend source contains no data endpoint literals or HTTP clients;
- full test collection prevents hidden imports of retired adapters;
- service, CLI, artifact and research-domain tests replace endpoint tests;
- static PWA browser acceptance verifies zero data requests and offline reload.

## Architecture after migration

```text
Python services / CLI / scripts / workflows
                  ↓
     versioned research artifact bundle
                  ↓
       static/local read-only PWA
```

No new adapter may be introduced to restore browser execution. New reads require an artifact contract; new execution belongs to Python CLI, scripts or workflows.
