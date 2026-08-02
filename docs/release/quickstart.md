# Alpha Engine Quickstart

Alpha Engine is a Python research engine with a static GitHub Pages/PWA viewer. A local FastAPI server is no longer the canonical product path.

> **Legacy notice**
>
> The FastAPI/local-Web, PM2 and API-container paths are frozen and scheduled for staged removal under [#316](https://github.com/liuh886/alpha_engine/issues/316). They remain available only for migration compatibility.

## 1. Use the Research Artifact Studio

Open the static application:

- <https://liuh886.github.io/alpha_engine/>

The application:

- requires no backend and no login;
- can be installed as a PWA;
- opens the published bundle or a local directory/file set/ZIP;
- reads only files declared in `alpha-engine-bundle.json`;
- does not upload selected local files;
- reopens its application shell offline after the first successful visit.

Use **Library** to select a research bundle.

## 2. Install the Python research engine

Prerequisites:

| Tool | Requirement |
| --- | --- |
| Python | >= 3.10 |
| `uv` | current release |
| Git | current supported release |
| Node.js/npm | only required for frontend contribution |

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
uv sync --extra dev
```

Run the environment check:

```bash
make doctor
```

## 3. Run research tasks

Common commands:

```bash
make data
make train-us
make train-cn
make backtest
```

These commands execute Python research workflows. They do not require a browser or local Web server.

The fixed methodology is documented in [`docs/methodology.md`](../methodology.md).

## 4. Export a versioned research bundle

After the required metadata, reports and model artifacts exist:

```bash
make research-bundle
```

Equivalent explicit commands:

```bash
uv run python scripts/export_static_site_data.py \
  --market all \
  --output artifacts/site/data

uv run python scripts/export_research_bundle.py \
  --source artifacts/site \
  --output artifacts/research-bundle
```

Expected output:

```text
artifacts/research-bundle/
  alpha-engine-bundle.json
  data/
  reports/
  notebooks/
  docs/
```

The exporter validates referenced paths, records byte sizes and SHA-256 digests, and fails closed when required source evidence is missing.

Open `artifacts/research-bundle/` from the PWA Library. A ZIP of the same folder is supported as a fallback.

## 5. Frontend development

Frontend development uses the static artifact runtime by default:

```bash
cd qlib-dashboard
npm ci
VITE_RUNTIME_MODE=static_artifact npm run dev
```

This Vite server is a contributor tool, not a required production service. It must not depend on FastAPI.

Run frontend validation:

```bash
npx tsc --noEmit
npm run lint
npm test
VITE_RUNTIME_MODE=static_artifact npm run build
npx playwright test --config=playwright.static.config.ts
```

## 6. Repository validation

Run the local quality gates:

```bash
make ci
```

The first gate checks that no new FastAPI, Uvicorn, SlowAPI, `connected_research` or `api_server.py` dependency appears outside the explicit retirement inventory.

Retirement governance:

- [`docs/architecture/legacy_web_retirement.md`](../architecture/legacy_web_retirement.md)
- [`docs/architecture/legacy_web_inventory.json`](../architecture/legacy_web_inventory.json)

## 7. Deprecated compatibility path

The old local Web stack can still be started temporarily:

```bash
make legacy-web-dev
```

`make dev` is a compatibility alias and prints a deprecation warning.

The legacy stack includes:

- FastAPI and `api_server.py`;
- local Basic Auth and CORS;
- Vite proxying to `/api`;
- PM2 launchers;
- API-serving Docker/Compose configuration;
- connected frontend routes, job polling and mutation controls.

Do not add new features to this path. A retained operation must first be moved into a pure Python service, CLI command, scheduled workflow or versioned artifact before its HTTP adapter is removed.

## 8. Troubleshooting

### Bundle export cannot find metadata

Confirm the research pipeline has produced `artifacts/metadata/metadata.db`, then rerun the required data/training/backtest tasks.

### The PWA rejects a bundle

Check that:

- `alpha-engine-bundle.json` is at the selected root;
- every declared file exists;
- files have not changed after the manifest was generated;
- the schema major version is supported;
- the bundle does not contain path traversal or unsupported ZIP features.

### Local directory permission expired

Reopen the bundle from Library and grant read permission again. The application never requires write permission.

### Frontend development accidentally enters connected mode

Set:

```bash
VITE_RUNTIME_MODE=static_artifact
```

Static and local modes must make zero `/api/*` requests.

## Product boundary

- Web product: GitHub Pages/PWA Research Artifact Studio.
- Frontend data contract: `alpha-engine-bundle.json`.
- Research execution: Python CLI/scripts/workflows.
- Legacy local server: deprecated migration-only surface.
- `research_only=true`, `trade_ready=false`.
