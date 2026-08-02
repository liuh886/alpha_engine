# Frontend Governance Closeout

Status: completed  
Product: Alpha Engine Research Artifact Studio  
Scope: `research_only=true`, `trade_ready=false`

## Final product boundary

Alpha Engine has one browser product: a read-only Research Artifact Studio distributed through GitHub Pages/PWA or opened against a local research bundle.

The browser may:

- load published or local `alpha-engine-bundle.json` evidence;
- review data lineage, models, comparisons, backtests, factors, experiments, reports and methodology;
- validate bundle paths, byte sizes, hashes and schema compatibility;
- reload the application shell offline after a successful visit.

The browser may not:

- refresh data, train models or run backtests;
- create, cancel or monitor Python jobs;
- mutate model, strategy or promotion state;
- authenticate against or call an Alpha Engine Web API;
- place or simulate orders through a connected runtime.

Python CLI commands, scripts and workflows remain the execution boundary. Versioned research bundles remain the browser data boundary.

## Completed rebuild and retirement sequence

- PR #306 established the static Pages/PWA foundation.
- PR #307 introduced the versioned research bundle.
- PR #308 added local directory, file-set and ZIP loading.
- PR #311 rebuilt the information architecture around evidence review.
- PR #312 converted evidence pages to artifact-native readers.
- PR #313 added static browser quality gates and runtime isolation.
- PR #317 froze the legacy Web boundary.
- PR #329 cut the production product over to artifact-only runtime modes.
- PR #334 physically deleted legacy frontend modules and HTTP clients.
- PR #336 retired the first browser-only HTTP adapters.
- PR #337 removed the remaining FastAPI adapters and temporary server.
- PR #346 removed the server dependencies, PM2, API containers, localhost operations and legacy deployment stack.

Issues #316 and #318–#320 are complete. No compatibility layer is retained.

## Pages publishing policy

The production Pages workflow runs only after a push to `main` changes a publish-relevant path:

- `qlib-dashboard/**`;
- the static-site or research-bundle exporters;
- the research-bundle implementation;
- published methodology or bundle schema;
- the zero-server boundary policy;
- the Pages workflow itself.

Backend-only research, data, model and operational commits do not trigger Pages publishing. `workflow_dispatch` remains available for an intentional manual rebuild.

Pull requests validate through normal frontend and repository CI; they do not deploy the production site.

## Required release gates

A Pages release must pass:

1. zero-server boundary validation;
2. locked frontend dependency installation;
3. production static build;
4. PWA output checks;
5. deterministic static export and research-bundle verification;
6. site assembly checks for the application, manifest, model index, methodology and bundle schema;
7. GitHub Pages artifact upload and deployment.

A clean CI runner has no private runtime metadata database. The Pages exporter therefore publishes an explicitly blocked empty evidence bundle when no governed database is present. That bundle must declare:

- `promotion_decision=blocked`;
- warning or gate `metadata_db_missing`;
- zero inferred models or performance claims.

This permits product and navigation testing without fabricating research evidence. Publishing real evidence requires a separate governed artifact handoff.

## Permanent architecture guards

The repository rejects:

- FastAPI, Uvicorn or SlowAPI as direct product dependencies;
- browser `/api/*` endpoints and HTTP clients;
- connected runtime or authentication modes;
- PM2 and API-serving container entrypoints;
- UI credentials, CORS and application host/port configuration;
- reintroduction of retired operational routes.

MCP remains an independent JSON-RPC research integration and must not become a frontend runtime dependency.

## Remaining work

Frontend reconstruction and legacy retirement are complete. The only active product-governance work is UAT in Issue #349:

- published Pages journey;
- local directory/file-set/ZIP journey;
- evidence interpretation;
- desktop/tablet/mobile and offline behavior;
- fail-closed bundle cases.

New frontend work should be opened as a concrete UAT defect or a separately scoped product enhancement. It must not reopen the retired connected-Web architecture.
