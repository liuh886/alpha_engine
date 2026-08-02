# Legacy Web Retirement Policy

Status: **Phase 0 — frozen / deprecated**  
Parent: #316

## Decision

Alpha Engine's only supported Web product is the static **Research Artifact Studio** deployed through GitHub Pages and installable as a PWA.

The legacy FastAPI/local-Web stack remains temporarily available only to support controlled migration. It is not the default product architecture and must not receive new features.

## Target boundary

```text
Python research pipelines
        ↓
versioned research artifacts
        ↓
GitHub Pages / PWA / local bundle reader
```

The browser consumes `alpha-engine-bundle.json` and files declared by that manifest. Python execution remains in CLI commands, scripts and scheduled workflows.

## Frozen legacy surface

The following areas are legacy migration zones:

- `api_server.py`;
- `src/api/`;
- FastAPI/Uvicorn/SlowAPI imports;
- frontend `connected_research` capability and API-only routes;
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

- make Pages/PWA and CLI the canonical entry points;
- mark local Web documentation as deprecated;
- record the migration inventory;
- block new legacy dependencies in CI.

### Phase 1 — remove connected frontend mode

- remove `connected_research` and authentication UI;
- remove API clients, polling hooks and backend-only routes;
- preserve static/local artifact journeys.

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
- Legacy local server: deprecated migration-only surface.
- Scope: `research_only=true`, `trade_ready=false`.
