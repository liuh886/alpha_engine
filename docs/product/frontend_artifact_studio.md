# Alpha Engine Frontend: Research Artifact Studio

Status: approved product direction, implementation tracked by Issue #299.

## 1. Product position

Alpha Engine's Python pipelines remain responsible for data acquisition, data governance, factor computation, model training, backtesting and evidence generation.

The frontend is repositioned as a **research artifact studio**: a local-first application for opening, validating, comparing and explaining the outputs of those pipelines.

It is not:

- a browser-side training environment;
- a broker or order-entry terminal;
- a live-trading control plane;
- a generic infrastructure dashboard;
- a place where missing research evidence is reconstructed heuristically.

## 2. Primary user outcome

A researcher should be able to answer five questions without starting the backend:

1. What bundle of evidence am I looking at?
2. Which data, universe, benchmark and research contract produced it?
3. What did the model or strategy do relative to the benchmark and after costs?
4. Why was the result retained, rejected, blocked or left under monitoring?
5. Where are the exact reports, notebooks, manifests and hashes behind the conclusion?

## 3. Runtime architecture

### Static artifact mode

Default GitHub Pages/PWA deployment.

- read-only;
- no authentication;
- no FastAPI dependency;
- example or exported bundle;
- installable and offline-capable application shell.

### Local artifact mode

The installed or hosted application reads a user-selected Alpha Engine results folder or ZIP directly in the browser.

- read-only;
- local files are not uploaded;
- directory permission is explicit and renewable;
- only files declared by the bundle manifest are consumed.

### Connected research mode

Optional developer workspace connected to the local FastAPI runtime.

- authenticated;
- may expose jobs, refresh, training and system tools;
- operational capabilities are isolated from the public/static product;
- connected evidence never silently replaces a missing local artifact.

## 4. Information architecture

### Library

Open, validate, reconnect, switch and close research bundles.

### Overview

Show scope, evidence cutoff, integrity, latest conclusion, blocked gates, model/backtest count and key benchmark-relative findings.

### Data

Show selected-pool coverage, provider lineage, reconciliation, missing or quarantined symbols, calendar coverage and data readiness.

### Models

Show model contract, training and OOS windows, metrics by window, feature identity, promotion decision and failed gates.

### Experiments

Show hypothesis, frozen contract, evidence run, result, stop rule and relation to preceding/following experiments.

### Backtests

Show benchmark-relative performance, drawdown, costs, turnover, holdings, attribution and a signal/execution ledger.

### Factors

Show factor namespace, formula provenance, field coverage, validation evidence, decay and redundancy status.

### Reports and notebooks

Provide durable access to written interpretation and reproducible notebooks.

### Methodology

Explain the fixed 10-day contract, market isolation, universe rules, evidence boundaries and research-only status.

## 5. Design direction

The visual language should be calm, precise and evidence-first.

- Prefer a professional research workspace over a retail trading aesthetic.
- Use restrained neutral surfaces with one high-contrast signal accent.
- Put conclusion, scope and integrity ahead of infrastructure health.
- Keep provenance and warnings visible without turning every screen into an alert panel.
- Use dense tables where comparison requires them, but give interpretation and conclusions room to breathe.
- Distinguish signal dates from execution dates visually and textually.
- Avoid neon market colors, fake urgency, decorative glassmorphism and animation without analytical value.

## 6. Current frontend audit

The existing frontend has useful components and data normalization, but its framing conflicts with the new product direction:

- startup is guarded by backend authentication;
- bootstrap assumes live `/api/system`, job and data-status endpoints;
- the home screen prioritizes system health, active jobs, sync and agent control;
- navigation mirrors backend subsystems and mixes released, experimental and internal operations;
- GitHub Pages exports static data but the main model API still targets FastAPI;
- a Pages workflow exists, but the product is not yet an explicit static runtime;
- PWA manifest, service worker and install/offline contracts were absent;
- the single-file Vite build is useful for a compact shell, but large research datasets must remain external and lazily loaded.

The first implementation slice therefore establishes explicit runtime capabilities, authentication boundaries, static data loading and PWA installability before the visual redesign.

## 7. Delivery order

1. Versioned research bundle and exporter.
2. Static GitHub Pages and PWA runtime.
3. Local folder and ZIP loading.
4. Research-oriented application shell, Library and Overview.
5. Data, model, experiment, backtest and factor views.
6. Connected developer workspace and product-quality gates.

Each slice uses a separate issue and reviewable PR. Later visual work must not reintroduce backend coupling into static/local modes.

## 8. Product boundaries

Every bundle and screen must preserve:

- `research_only=true`;
- explicit `trade_ready` status;
- evidence cutoff and generated time;
- exact market, universe and benchmark identity;
- immutable contract and artifact hashes where available;
- visible missing, incompatible or blocked evidence;
- no broker or automatic-order capability.
