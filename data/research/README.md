# Repository Research Store

`data/research/` is the durable, Git-backed source of truth for research evidence that may be consumed by Alpha Engine tools or published to the Research Artifact Studio.

## Authority boundary

- `data/` contains governed, durable repository data.
- `artifacts/` contains generated local/CI scratch state and is disposable.
- `artifacts/metadata/metadata.db` is a reconstructible query cache. It must never contain the only copy of a model, run or performance claim.
- `data/research/catalog.json` is the publication allow-list. A file is not public evidence merely because it exists elsewhere in the repository.

## Layout

```text
data/research/
├── catalog.json
├── models/<model_id>/model.json       # future normalized model records
├── runs/<run_id>/
│   ├── run.json
│   ├── metrics.json
│   ├── equity_curve.json
│   ├── attribution.json
│   ├── holdings.parquet               # optional, Git LFS when large
│   └── inventory.json
└── releases/<release_id>/
    ├── release.json
    └── selected_runs.json
```

Named model contracts enter the frontend only when allow-listed in `catalog.json`. Imported runs enter only when added to `published_runs`; a model uses a run as its main frontend evidence only when its catalog entry declares `primary_run_id`.

## Storage policy

Use ordinary Git for:

- catalog and release manifests;
- model/run identity;
- metrics and gates;
- compact equity curves;
- attribution summaries;
- SHA-256 inventories.

Use Git LFS for accepted Parquet and model binaries. Pages checks out LFS objects before building the research bundle. Provider-restricted raw responses, credentials, unbounded caches and temporary training files must not be committed.

Every durable run must bind:

- run ID and model ID;
- market, benchmark and universe;
- provider/data snapshot identity;
- training, validation and test windows;
- effective model parameters;
- transaction-cost convention;
- `research_only=true` and `trade_ready=false`;
- an inventory of every referenced file and SHA-256 digest.

## Import workflow

Training and backtests first produce a standard local run directory under `artifacts/`. Import without publishing:

```bash
alpha research import-run artifacts/runs/<run_id>/repository-run
```

Publish to the frontend catalog and assign as the model's primary run:

```bash
alpha research import-run \
  artifacts/runs/<run_id>/repository-run \
  --publish \
  --set-primary
```

The importer validates identity, windows, effective parameters, costs and the research boundary; calculates byte sizes and SHA-256 hashes; then copies the accepted files to the immutable `data/research/runs/<run_id>/` directory. Reusing the same run ID with different bytes fails closed.

See `docs/contracts/REPOSITORY_RUN_V1.md` for the exact files and schemas.

## End-to-end workflow

1. Data preparation, training and backtests write staging outputs under `artifacts/`.
2. `alpha research import-run` validates the staged run.
3. Accepted evidence is copied into `data/research/runs/<run_id>/`.
4. `--publish` updates `catalog.json`; `--set-primary` binds the run to a published model.
5. Review and merge the resulting Git changes through a PR.
6. GitHub Pages validates all inventory hashes and builds the browser bundle.
7. Local SQLite indexes may be rebuilt from repository evidence for query speed.

Deleting `artifacts/` must not delete accepted research history.
