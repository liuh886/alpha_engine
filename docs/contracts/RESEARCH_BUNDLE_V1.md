# Alpha Engine Research Bundle v1

## Purpose

`alpha-engine-bundle.json` is the stable, read-only boundary between governed Alpha Engine research pipelines and the GitHub Pages/PWA frontend. The browser must not discover arbitrary files, infer missing evidence, or depend on private FastAPI response shapes.

The durable publication source is the Git-tracked repository research store under `data/research/`. Files under `artifacts/` are generated staging outputs and are not authoritative.

## Root layout

```text
research-bundle/
├── alpha-engine-bundle.json
├── data/
│   ├── manifest.json
│   ├── models.json
│   └── curves/...
├── reports/...
├── notebooks/...
└── docs/...
```

`data/manifest.json` and `data/models.json` are required compatibility inputs for v1. Other files are indexed when present. The exporter copies bytes unchanged and records their SHA-256 identities.

## Repository source

`data/research/catalog.json` is the publication allow-list. Named models, accepted runs and reports are visible only when the catalog explicitly references them. Candidate files, local SQLite rows and temporary Actions artifacts are not public evidence by default.

The repository exporter validates:

- safe relative paths;
- catalog/model identity agreement;
- `research_only=true` and `trade_ready=false`;
- declared report existence;
- provider/data snapshot identity where supplied.

Run-level curves, holdings and attribution enter the bundle only after they are promoted into immutable repository run records.

## Reader behavior

- Accept major schema version `1` only.
- Read the root manifest before loading large artifacts.
- Resolve only manifest-declared relative paths.
- Reject absolute paths, `..` traversal, missing files and digest mismatches.
- Treat `research_only=true` and `trade_ready=false` as hard product boundaries.
- Load large series and tables lazily.
- Never silently substitute backend evidence for missing local/static evidence.

## Artifact kinds

The first schema supports `model_index`, `static_export_manifest`, `backtest_series`, `report`, `notebook`, `methodology`, `table`, and `supporting_artifact`. New additive kinds may be introduced in v1 minor revisions. Readers must preserve unknown kinds but may omit unsupported renderers.

## Determinism

The bundle ID is the SHA-256 of the ordered `path:sha256` inventory. With unchanged source bytes, two exports produce the same bundle ID and manifest ordering. Timestamps are inherited from the authoritative repository catalog rather than generated as research evidence.

## CLI

```bash
python scripts/export_static_site_data.py \
  --source repository \
  --repository-catalog data/research/catalog.json \
  --output artifacts/site/data
mkdir -p artifacts/site/docs
cp docs/methodology.md artifacts/site/docs/methodology.md
python scripts/export_research_bundle.py \
  --source artifacts/site \
  --output artifacts/research-bundle
```

The command fails closed when required inputs are missing or when the output directory is placed inside the source directory.

A local metadata database remains an explicit migration source only:

```bash
python scripts/export_static_site_data.py \
  --source metadata-db \
  --metadata-db artifacts/metadata/metadata.db
```

## Compatibility policy

- Major version: breaking reader contract.
- Minor version: additive fields or artifact kinds.
- Patch version: clarifications and validation fixes.
- Legacy `metadata.db` or `dashboard_db.json` may be used only as explicit migration inputs; neither is the canonical browser contract or durable research store.
