# Repository Data Convergence

## Lightweight operating contract

Effective 2026-10-03 by user direction. This section governs simplification;
it does not assert that daily reliability is already achieved. The existing
selected-pool data program and research-only boundary remain in force.

The core operating route is:

```text
Required data at a verified cutoff
    → due evaluation using the active frozen strategy
    → append-only decision evidence
    → generated current state / explanation / health
    → Console and eligible notification
```

Formal historical evidence continues through the existing reviewed atomic
Bundle v2 publication transaction. Current operations must disclose its actual
formal and decision cutoffs when those advance separately.

### Keep the daily loop small

| Activity | Operating rule |
| --- | --- |
| Read status / explain a decision | Read verified evidence; no fetch, training or replay |
| Refresh market data | Fetch required deltas, verify identities and availability boundaries |
| Evaluate a strategy | Respect exchange sessions and its declared cadence; retain required no-change evidence |
| Reuse inputs | Exact contract, cutoff and implementation identity; verify transferred bytes |
| Train / broad factor research | Separate explicit research execution; reuse the existing governed trainer/evaluator |
| Publish | Existing reviewed release boundary; no alternate truth source |
| Notify | Governed eligible decisions; retain health failures separately from allocation changes |

A required validation is not skipped merely because it is expensive. Move it
to the stage where its inputs exist, reuse a valid receipt only under its exact
contract, and measure the remaining cost. Data revision, lifecycle, adjustment,
PIT availability and execution boundaries remain mandatory.

### One authority and a shrinking maintenance surface

Use the existing strategy, data and evidence authorities listed below. Workflow
tiers and required/release/advisory membership come from `.github/ci-policy.json`;
do not maintain another required-workflow list in code. Filename classification
is only a default for workflows not explicitly assigned by policy.

The existing workflow count budget is a ceiling. A proposed permanent workflow,
configuration knob, wrapper, database or service must identify the core user
need, why an existing path cannot serve it, and what maintenance cost it adds.
Prefer merging or replacing existing paths. No new scheduler or governance
service is needed to implement this policy.

Before retiring a path, inspect live callers, scheduled/dispatch entrypoints,
tests and evidence consumers. An unreferenced inventory entry is a cleanup
candidate, not proof that deletion is safe. Preserve immutable evidence and
failure memory; do not preserve obsolete runnable implementations solely to
keep a second execution route alive.

Keep durable manifests and compact decisions with source hashes. Use the
existing storage/retention classes below for bulk evidence and temporary
artifacts. Rebuild projections instead of synchronizing duplicate databases.
Avoid additional full-data copies when an existing durable verified source
reference meets the evidence contract.

### Accept usefulness and reliability, not task counts

The current view should make these facts visible together: usable evidence
cutoff, current governed state, target/change, reason and supporting evidence,
material uncertainty/blocker, and next scheduled evaluation. A user should not
need workflow logs to distinguish unchanged, not due, delayed and broken.

Accept the operating loop over 20 eligible sessions of the existing strategies:
record stage durations, cutoff lag, manual interventions, exact blockers and
delivery/publication receipts in existing diagnostics. A legitimate block is
reported truthfully; it does not count as a successful evidence refresh. A green
notification worker alone is not a fresh decision or an accepted release.

For each simplification, report the removed duplication or measured cost, the
affected contract tests and any remaining production acceptance. Do not claim
system-wide speed from a module import benchmark. Do not adjust model parameters,
costs, factors or pool membership using this acceptance evidence.

### Initial local implementation — 2026-10-03

CI tier inventory now reads the existing CI policy instead of a competing
hard-coded required-workflow list; policy changes trigger the affected checks.
Data recipe catalog/cache paths defer selected-pool provider loading until an
actual refresh. The shared source-manifest path remains unchanged.

Local validation: 73 affected tests, Ruff, the shared publication module's mypy
check, and both CI governance checks passed. One Windows cold module-import
measurement changed from 4.871s to 1.582s; loaded adapter modules fell from 9 to
3. These are local observations, not an end-to-end operating SLA. Workflow count
remains 45; no production deployment or 20-session acceptance is claimed here.

### Structural pruning — 2026-10-03

The CLI now imports only the selected operation's executor and handles its
declared errors; help and recipe discovery do not load providers, Qlib, replay
engines or model operations. Recipe identity parsing is shared in a lightweight
catalog module; the old executor consumes the same validation functions.
Replay identities likewise have one lightweight contract.

Two completed unsupported BYD v2 exploratory scripts (1,779 lines) were deleted
from the maintained runtime. Their exact source revision and Git-blob hashes
are recorded in `scripts/archive/ARCHIVE_MANIFEST.json`; experiment results,
logs and failure evidence remain unchanged. Four unreferenced historical
paradigms moved byte-identically into the existing archive.

The 23-name low-turnover diagnostic and weekly fundamental validation workflows
retain manual dispatch, state continuity and fail-closed gates; their default
schedules were removed. Active fleet and selected-pool data schedules are
unchanged. Permanent workflow count remains 45; scheduled workflows fell from
14 to 12. Local CLI module import changed from 4.734s / 2,468 loaded modules
to 0.169s / 124 modules in a single before/after measurement. This establishes
startup isolation, not production data throughput or reliability acceptance.

Validation: 137 affected tests, Ruff, scoped mypy and both CI governance checks
passed. A real local `alpha ops build` generated all five strategy projections
and their health snapshot under `artifacts/lightweight-acceptance/`; existing
data delays and blocked training profiles remained explicit. No committed
`data/research` evidence changed. These changes have not been deployed.

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
