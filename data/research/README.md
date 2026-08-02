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

The first repository-backed release reads named model contracts from the exact paths allow-listed in `catalog.json`. Run-level evidence will move into `data/research/runs/` through the local import and workflow-promotion slices of Issue #367.

## Storage policy

Use ordinary Git for:

- catalog and release manifests;
- model/run identity;
- metrics and gates;
- compact equity curves;
- attribution summaries;
- SHA-256 inventories.

Use Git LFS only when a large Parquet or model binary must remain in the repository. Provider-restricted raw responses, credentials, unbounded caches and temporary training files must not be committed.

Every durable run must bind:

- run ID and model ID;
- market, benchmark and universe;
- provider/data snapshot identity;
- training, validation and test windows;
- effective model parameters;
- transaction-cost convention;
- `research_only=true` and `trade_ready=false`;
- an inventory of every referenced file and SHA-256 digest.

## Workflow

1. Training and backtests write staging outputs under `artifacts/`.
2. A promotion/import command validates the staged run.
3. Accepted evidence is copied into an immutable `data/research/runs/<run_id>/` directory on a branch.
4. The catalog is updated through review.
5. GitHub Pages builds the browser bundle from the repository store.

Deleting `artifacts/` must not delete accepted research history.
