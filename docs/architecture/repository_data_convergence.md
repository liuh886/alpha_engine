# Repository Data Convergence

## Authority model

Alpha Engine now uses a one-way data authority:

```text
Git-tracked data/research
        ├── Research Artifact Studio bundle
        └── local metadata.db query cache
```

`metadata.db` is not synchronized back into Git and is never accepted as the sole copy of training or backtest evidence.

## Training and backtest lifecycle

1. A local or CI workflow writes temporary outputs under `artifacts/`.
2. The workflow assembles a Repository Research Run v1 directory.
3. `alpha research import-run` validates and copies the run into `data/research/runs/<run_id>/`.
4. `--publish` adds it to `data/research/catalog.json`.
5. `--set-primary` binds it to a published model for frontend evidence.
6. The resulting data changes are reviewed and merged through Git.
7. Pages verifies inventories and builds the read-only frontend bundle.
8. Local Python tools rebuild SQLite from the same repository evidence when indexed queries are useful.

## Rebuild the local index

```bash
alpha research rebuild-index
```

Default output:

```text
artifacts/metadata/metadata.db
```

Custom output:

```bash
alpha research rebuild-index \
  --output artifacts/metadata/research-cache.db
```

The rebuild is atomic. A temporary database is fully populated and validated before it replaces the previous cache. The database records:

- published model rows;
- the primary run and run-level metrics;
- published equity-curve points;
- attribution report references;
- the SHA-256 of `data/research/catalog.json`;
- `source=data/research`.

Deleting the SQLite file is safe. Running the command recreates it from Git-tracked evidence.

## Backend migration rule

Existing Python components may continue to consume the SQLite index while they are migrated, but they must observe these rules:

- reads only for models, metrics, curves and report indexes;
- no workflow may create an authoritative model or run only in SQLite;
- successful training/backtest workflows must emit a Repository Research Run v1 directory;
- promotion means a Git-reviewed update to `data/research`, not an SQLite stage mutation;
- caches may be deleted, rebuilt and compared against the catalog hash at any time.

New backend code should prefer repository-store readers for durable facts and use SQLite only where indexed local queries provide measurable value.

## Storage classes

Normal Git:

- catalogs and manifests;
- run and model identity;
- metrics;
- compact curves;
- attribution summaries;
- inventories and hashes.

Git LFS:

- holdings/predictions Parquet;
- model binaries.

Excluded:

- credentials;
- provider-restricted redistributable content where licensing forbids storage;
- replaceable caches and partial downloads;
- runtime databases as authoritative evidence.
