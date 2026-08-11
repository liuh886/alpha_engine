# Repository Research Store

`data/research/` is the durable, Git-backed source of truth for research evidence consumed by Alpha Engine tools and the Research Artifact Studio.

## Authority boundary

- `data/` contains governed, durable repository data.
- `artifacts/` contains generated local/CI scratch state and is disposable.
- `artifacts/metadata/metadata.db` is a reconstructible query cache. It must never contain the only copy of a model, run or performance claim.
- `data/research/catalog.json` is the publication allow-list. A file is not public evidence merely because it exists elsewhere in the repository.

## Layout

```text
data/research/
├── catalog.json
├── runs/<run_id>/
│   ├── run.json
│   ├── metrics.json
│   ├── equity_curve.json       # present only when an exact trace was retained
│   ├── attribution.json
│   ├── training_log.json
│   ├── model.json
│   ├── optional large files
│   └── inventory.json
└── releases/<release_id>/
    ├── release.json
    └── selected_runs.json
```

Named model contracts remain under `configs/models/`. The catalog binds each published model to one primary immutable run.

## Historical backfill boundary

The accepted source artifacts for US x1.1, US x1.0 and CN x1.0 retained exact provider identities, effective contracts, window metrics and final selections, but did not retain portfolio-value traces or complete provider bytes.

Those artifacts are normalized into Repository Run v1 without fabricating missing evidence:

- exact metrics and selections are retained;
- source workflow, artifact ID and digest are retained;
- `equity_curve.json` is absent;
- `run.json` explicitly records `unavailable_source_artifact_did_not_retain_trace`;
- US exact replay remains blocked by Issue #358;
- CN exact replay remains blocked by Issue #345.

A historical period or daily curve must never be inferred from half-year returns or regenerated against a different provider identity.

## Forward evidence contract

New governed fixed-horizon workflows must retain, in the same artifact:

- complete provider snapshot bytes and provider identity;
- declared and effective model parameters;
- aggregate and per-window metrics;
- exact non-overlapping period NAV and benchmark trace;
- target holdings and name contributions for every rebalance period;
- model/run identity and research boundaries.

The fixed-10D evaluator writes `backtest_traces` into every completed window artifact. These traces are explicitly **period traces**, not daily NAV claims. Optimization workflows fail closed when a completed candidate lacks trace points or holdings, and they upload the complete provider directory.

## Storage policy

Use ordinary Git for:

- catalog and release manifests;
- model/run identity;
- metrics and gates;
- compact period or daily curves;
- attribution summaries;
- SHA-256 inventories.

Use Git LFS for accepted large Parquet or model binaries. Provider-restricted raw responses, credentials, unbounded caches and temporary training files must not be committed.

Every durable run binds:

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
2. The workflow retains provider bytes, metrics and exact period traces.
3. `alpha research import-run` validates the staged Repository Run v1 directory.
4. Accepted evidence is copied into immutable `data/research/runs/<run_id>/` through a PR.
5. `data/research/catalog.json` binds the run to a published model.
6. GitHub Pages builds the browser bundle from the repository store.
7. `alpha research rebuild-index` reconstructs local SQLite indexes from the same Git data.

Deleting `artifacts/` must not delete accepted research history.

## Local formal replay contract

An accepted model must not depend on GitHub Actions YAML as the only description of how its economic path is produced. CI may supply credentials or caches, but the maintained repository code must expose the same replay contract locally.

The current rules-based baselines use:

```bash
uv run alpha research replay qqq_v4_3
uv run alpha research replay byd_v1_3
uv run alpha research replay all
```

QQQ v4.3 prepares or reuses the existing `qqq-rotation-sgov` governed data recipe at the accepted evidence cutoff and requires the professional ETF source identity. Set `TIINGO_API_TOKEN` before the first exact replay; use `--refresh-data` when an older non-professional cache must be replaced. The runner then executes the maintained v4.3 state/allocation implementation and compares `report`, `positions`, `trades`, and the portfolio contract against the accepted formal package.

BYD v1.3 is offline-replayable from a clean checkout. The runner extracts the committed BYD/515180 canonical bases, extends them through the accepted cutoff from the committed prospective stores, executes the maintained v1.3 low-vol-recovery implementation, and performs the same formal trace comparison.

A material mismatch returns `invalid_evidence`. Missing governed inputs or required provider access returns `data_blocked`. Neither state is repaired by a fallback provider, simplified evaluator, aggregate-return proxy, or compatibility runner.
