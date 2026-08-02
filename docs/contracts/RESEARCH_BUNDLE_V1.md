# Alpha Engine Research Bundle v1

## Purpose

`alpha-engine-bundle.json` is the stable, read-only boundary between governed Alpha Engine research pipelines and the GitHub Pages/PWA frontend. The browser must not discover arbitrary files, infer missing evidence, or depend on private FastAPI response shapes.

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

The bundle ID is the SHA-256 of the ordered `path:sha256` inventory. With unchanged source bytes, two exports produce the same bundle ID and manifest ordering. Timestamps are inherited from the authoritative static export rather than generated as research evidence.

## CLI

```bash
python scripts/export_static_site_data.py --output artifacts/site/data
mkdir -p artifacts/site/docs
cp docs/methodology.md artifacts/site/docs/methodology.md
python scripts/export_research_bundle.py \
  --source artifacts/site \
  --output artifacts/research-bundle
```

The command fails closed when required inputs are missing or when the output directory is placed inside the source directory.

## Compatibility policy

- Major version: breaking reader contract.
- Minor version: additive fields or artifact kinds.
- Patch version: clarifications and validation fixes.
- Legacy `dashboard_db.json` may be used only as an exporter input; it is not the canonical browser contract.
