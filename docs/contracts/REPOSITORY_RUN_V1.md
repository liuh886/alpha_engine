# Repository Research Run v1

## Purpose

A repository run is the durable, immutable unit for accepted Alpha Engine training and backtest evidence. Local workflows may produce many temporary files under `artifacts/`, but only a validated run directory may enter `data/research/runs/` and become available to the Research Artifact Studio.

Do not copy `metadata.db` into Git. SQLite is a derived local index; a run directory is the auditable source record.

## Local staging layout

```text
artifacts/runs/<run_id>/repository-run/
├── run.json                  # required
├── metrics.json              # required
├── equity_curve.json         # optional
├── attribution.json          # optional
├── training_log.json         # optional
├── model.json                # optional model metadata
├── holdings.parquet          # optional, Git LFS after import
├── predictions.parquet       # optional, Git LFS after import
└── model.pkl|bin|joblib|onnx  # optional, Git LFS after import
```

The v1 importer accepts top-level files only. It rejects nested directories, symlinks and undeclared file names so that inventories remain deterministic and path traversal is impossible.

## `run.json`

```json
{
  "schema_version": "1.0.0",
  "run_id": "us-x1-1-2026h2-v1",
  "model_id": "us_x1_1",
  "run_type": "training_backtest",
  "market": "us",
  "benchmark": "QQQ",
  "universe_id": "us_selected_equities_v2",
  "data_snapshot_id": "sha256:<provider-or-data-bundle-identity>",
  "generated_at": "2026-08-02T08:30:00+00:00",
  "windows": {
    "train": ["2021-01-04", "2023-12-29"],
    "validation": ["2024-01-02", "2025-12-31"],
    "reporting": ["2026-01-02", "2026-06-30"]
  },
  "effective_parameters": {
    "family": "xgb",
    "objective": "rank:ndcg",
    "num_boost_round": 200,
    "max_leaves": 31,
    "learning_rate": 0.05,
    "seed": 42
  },
  "costs": {
    "transaction_cost_bps": 20,
    "holding_sessions": 10,
    "rebalance_sessions": 10
  },
  "research_only": true,
  "trade_ready": false
}
```

Required rules:

- schema major version must be `1`;
- `run_id` is immutable and may contain letters, digits, `.`, `_` and `-`;
- `run_type` is `training`, `backtest` or `training_backtest`;
- model, market, benchmark, universe and data snapshot identities are mandatory;
- windows, effective parameters and costs must be explicit non-empty objects;
- `research_only=true` and `trade_ready=false` are mandatory.

## `metrics.json`

A non-empty JSON object containing the decision-grade metrics for this run. Prefer the canonical frontend labels where available:

```json
{
  "Total Return": 1.1044,
  "Benchmark Return": 0.5520,
  "Excess Return": 0.5524,
  "ICIR": 0.2280,
  "Rank IC": 0.0410,
  "Max Drawdown": -0.2715,
  "Turnover": 6.4,
  "Sharpe Ratio": 1.42
}
```

Do not omit weak or failed metrics. A repository run is evidence, not a marketing summary.

## `equity_curve.json`

```json
{
  "run_id": "us-x1-1-2026h2-v1",
  "points": [
    {"date": "2024-01-02", "nav": 1.0, "drawdown": 0.0},
    {"date": "2024-01-03", "nav": 1.01, "drawdown": 0.0}
  ]
}
```

The run ID must match `run.json`. The points list must be non-empty. Additional fields such as benchmark NAV and turnover may be included when supported by the frontend contract.

## Import commands

Validate and copy without publishing:

```bash
alpha research import-run artifacts/runs/<run_id>/repository-run
```

Publish the run to the frontend catalog:

```bash
alpha research import-run \
  artifacts/runs/<run_id>/repository-run \
  --publish
```

Publish it and make it the model's primary frontend run:

```bash
alpha research import-run \
  artifacts/runs/<run_id>/repository-run \
  --publish \
  --set-primary
```

The command writes:

```text
data/research/runs/<run_id>/
├── run.json
├── metrics.json
├── ...accepted files...
└── inventory.json
```

`inventory.json` records each imported file's byte size, SHA-256 and storage class. Reimporting identical bytes is idempotent. Reusing the same run ID with different evidence fails closed.

## Git workflow

After import:

```bash
git status
git add data/research/runs/<run_id> data/research/catalog.json
git commit -m "data: publish <run_id> research evidence"
git push
```

Open a PR and review:

- data snapshot and provider identity;
- declared versus effective parameters;
- windows and holdout status;
- metrics, costs and drawdown;
- inventory and Git LFS pointers;
- catalog publication and primary-run assignment.

Merging `data/research/**` into `main` triggers the path-filtered Pages release. Backend-only changes do not publish the site.

## Storage policy

Ordinary Git:

- JSON manifests;
- compact equity curves;
- metrics;
- attribution summaries;
- SHA-256 inventories.

Git LFS:

- Parquet holdings/predictions;
- model binaries (`pkl`, `bin`, `joblib`, `onnx`).

Never commit:

- credentials or `.env`;
- provider-restricted raw responses when redistribution is prohibited;
- partial downloads;
- caches that can be rebuilt;
- `metadata.db` as the sole research record.
