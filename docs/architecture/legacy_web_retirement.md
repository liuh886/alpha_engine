# Legacy Web Retirement Policy

Status: **Phase 1 — frontend product cutover in progress**  
Parent: #316  
Frontend delivery: #318

## Decision

Alpha Engine's only supported Web product is the static **Research Artifact Studio** deployed through GitHub Pages and installable as a PWA.

The legacy FastAPI/local-Web stack remains temporarily available only to support controlled backend migration. It is no longer represented as a browser product and must not receive new features.

## Target boundary

```text
Python research pipelines
        ↓
versioned research artifacts
        ↓
GitHub Pages / PWA / local bundle reader
```

The browser consumes `alpha-engine-bundle.json` and files declared by that manifest. Python execution remains in CLI commands, scripts and scheduled workflows.

## Current frontend truth

The frontend route graph contains artifact views only:

- Overview and Library;
- Backtests, Models, Compare, Data, Factors, Experiments and Reports;
- Methodology.

The application root has no authentication provider, login guard, server-health bootstrap, task polling, data refresh, mutation control or Developer navigation group. The two remaining runtime labels describe artifact source only: published or local.

## Frozen legacy surface

The following areas remain legacy migration zones:

- `api_server.py`;
- `src/api/`;
- FastAPI/Uvicorn/SlowAPI imports;
- unused frontend API clients, polling hooks and connected-only pages pending physical deletion;
- PM2 launchers and `ecosystem.config.js`;
- API-oriented Docker/Compose startup;
- local Basic Auth, CORS, API host/port and static-site mounting;
- API contract/router tests and demo-server Playwright flows;
- `make dev`, `make smoke` and localhost Web documentation.

Changes inside these areas are allowed only when they reduce the retirement surface, fix a migration blocker, or extract reusable research-domain logic into a pure Python service/CLI.

## Rules for new work

1. Do not add new HTTP endpoints.
2. Do not add new frontend `/api/*` calls.
3. Do not add new authentication, polling, mutation or system-operation UI.
4. Do not place research-domain logic only inside a router.
5. New read use cases must be represented in the research bundle contract.
6. New execution use cases must be implemented as pure Python services, CLI commands or workflows.
7. Static and local artifact modes remain read-only and must not require localhost services.

## Removal sequence

### Phase 0 — freeze and inventory

Completed in #317:

- Pages/PWA and CLI became the canonical entry points;
- local Web documentation was marked deprecated;
- the migration inventory was recorded;
- CI began blocking new legacy dependencies.

### Phase 1 — remove connected frontend mode

In progress in #318:

- remove `connected_research` from production frontend code;
- remove authentication and server bootstrap from the application root;
- remove backend-only routes from the browser route graph;
- preserve static/local bundle journeys;
- then physically delete the now-unreachable connected UI modules.

### Phase 2 — extract domain services

Classify every endpoint as:

- replaced by artifact reads;
- obsolete mutation/job control;
- reusable research operation requiring CLI/service extraction;
- duplicate or dead code.

No router is deleted until retained domain behavior has a non-HTTP owner.

### Phase 3 — delete server and deployment stack

- delete FastAPI entrypoint and routers;
- remove server dependencies and settings;
- remove PM2/API Docker/Compose paths;
- remove API-only tests and docs.

### Phase 4 — normalize repository language and CI

- remove dashboard-server terminology;
- retain only Python research gates and static artifact/PWA gates;
- publish a final deletion and migration manifest.

## Required evidence for each deletion PR

- affected endpoint/route inventory;
- retained replacement or explicit deletion rationale;
- repository-wide reference scan;
- Python research-contract tests;
- deterministic bundle tests;
- static PWA TypeScript, lint, unit, build and Playwright tests;
- confirmation that static/local modes issue no `/api/*` request.

## Current product truth

- Web: GitHub Pages/PWA Research Artifact Studio.
- Data boundary: versioned research bundle.
- Execution boundary: Python CLI/scripts/workflows.
- Legacy local server: deprecated backend migration-only surface.
- Scope: `research_only=true`, `trade_ready=false`.
