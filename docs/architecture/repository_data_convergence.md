# Repository Data Convergence

## Authority model

Alpha Engine uses one-way evidence authority:

```text
Git-tracked canonical evidence
        ├── disposable local metadata.db index
        ├── generated Strategy Operations read model
        └── generated frontend / Pages projection
```

Only the first layer is authoritative. `metadata.db`, `data/research/strategy_operations/` and `qlib-dashboard/public/data/` are rebuildable projections and are not committed as independent facts.

## Canonical Git state

Git may retain durable research truth such as:

- active strategy identity in `configs/strategies/registry.json`;
- immutable model/run manifests and evidence;
- accepted formal Bundle v2 evidence;
- market evidence and Model Data Bundle components;
- append-only Strategy Decision Ledger records;
- research specs, receipts, factor memory and lineage.

A generated consumer view must never become a second authority simply because it is convenient for the frontend.

## Training and backtest lifecycle

1. Local or CI execution writes temporary outputs under `artifacts/`.
2. Governed validation binds provider, component, model, evaluator and evidence identities.
3. An immutable run/evidence object is retained under the repository research store when review requires durable history.
4. Formal promotion assigns accepted identity through the formal publication contract; it does not authorize trading.
5. Reviewed canonical evidence changes are merged through Git.
6. Pages/build jobs regenerate current read models and frontend projections from that canonical state.
7. Disposable indexes may be rebuilt at any time from repository evidence.

## Strategy operations lifecycle

Current strategy state is deliberately split into fact and projection:

```text
Active Strategy Catalog
        +
Formal Catalog
        +
append-only Decision Ledger
        ↓
alpha ops build
        ↓
Strategy Operations read model
        ↓
frontend / Pages projection
```

The read model contains current/target allocation, cadence, freshness, delivery and driver presentation, but it is not itself the event store. Deleting it is safe; rebuilding it from the same canonical inputs must reproduce the same semantic state.

## Frontend projection rule

`qlib-dashboard/public/data/` is build output.

- CI and Pages create it from canonical repository evidence before Vite builds.
- production code may read the projection but may not write research truth back through it;
- generated files are excluded from reviewed data-refresh diffs;
- a missing projection is fixed by rebuilding, not by adding another data source or fallback reader.

## Rebuild the local index

```bash
alpha research rebuild-index
```

Default output:

```text
artifacts/metadata/metadata.db
```

The rebuild is atomic and the database remains disposable. No workflow may create an authoritative model/run only in SQLite.

## Storage classes

### Normal Git

- strategy/catalog identities;
- manifests and hashes;
- compact immutable evidence;
- append-only decision records;
- research specs/receipts;
- compact curves, metrics and attribution summaries.

### Git LFS

Use only where retained evidence genuinely requires larger binary objects such as model binaries or Parquet holdings/predictions.

### Generated / ignored

- `data/research/strategy_operations/`;
- `qlib-dashboard/public/data/`;
- `artifacts/` runtime outputs except explicitly retained release evidence;
- local SQLite indexes and caches.

### Excluded

- credentials;
- provider-restricted content whose license forbids repository storage;
- replaceable downloads/caches;
- runtime databases as authoritative evidence.

## Invariant

For any user-facing claim there must be a path back to one canonical evidence object or append-only decision record. No browser bundle, workflow-local JSON, SQLite row or generated snapshot may become the sole copy of a quantitative fact.
