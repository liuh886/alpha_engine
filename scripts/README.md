---
path: scripts/README.md
version: 3.0.0
last_edit_date: 2026-08-12
status: active
---

# Scripts Catalog

`scripts/` contains maintained domain utilities and bounded research executors. It is **not** the control plane for Alpha Engine.

Cross-system lifecycle commands belong to the installed `alpha` CLI:

```text
alpha data ...                 governed data preparation / readiness
alpha research ...             governed research, replay and run import
alpha ops record-decision ...  append one immutable active-strategy decision
alpha ops build ...            materialize the current Strategy Operations read model
```

GitHub Actions should call these maintained entrypoints whenever the task crosses data/research/operations boundaries. Once a CLI command replaces a wrapper script, the wrapper is deleted; no compatibility alias is retained.

## Maintained domain utilities

Some model/data operations remain explicit Python utilities because they own narrow domain semantics rather than a general product lifecycle. Examples include:

- selected-pool provider construction and validation under `scripts/data/`;
- QQQ/BYD/ranker model-specific current-target calculation;
- formal-source deterministic builders/refresher utilities;
- evidence audits and bounded research executors tied to committed specs.

A domain utility may calculate its declared model/data result. It may not create a second evaluator, active-strategy registry, publication catalog or frontend data source.

## Formal refresh boundary

The reviewed formal refresh workflow may invoke model-specific builders, but the durable publication contract is shared:

```text
provider / component identity
  -> exact replay gate
  -> governed source or native Bundle v2 evidence
  -> Active Strategy Catalog parity
  -> formal Bundle v2 catalog
```

Strategy Operations and frontend `public/data` are generated after canonical evidence validation; scripts must not treat those projections as research truth.

## Decision boundary

Current strategy decisions are appended through:

```bash
alpha ops record-decision ...
```

The existing append-only ledger enforces model identity, factor evidence, workflow/commit provenance and duplicate protection. Do not create per-model persistence scripts or parallel signal databases.

Current UI state is materialized with:

```bash
alpha ops build --generated-at <ISO-UTC>
```

The resulting Strategy Operations JSON is rebuildable and ignored by Git.

## Controlled research utilities

Research utilities must remain bound to their committed evidence contracts. They may be used for deterministic diagnosis/replay, but they do not become permanent product entrypoints merely because an experiment succeeded.

Examples include exact provider builds, frozen candidate replays, factor diagnostics and PIT/static decomposition utilities. The governing rule is more important than the filename:

- one falsifiable mission;
- immutable provider/universe/evaluator identity;
- no post-result parameter search;
- no validation-only fallback;
- retain evidence/receipt, then delete superseded execution paths.

## Output rules

- persist configuration, commit SHA, provider identity, data cutoff, universe identity and benchmark identity;
- retain immutable evidence under the governed repository evidence contract when it must survive review;
- write temporary/generated material under `artifacts/`;
- do not commit generated Strategy Operations or frontend projections;
- do not silently overwrite a prior run/decision identity;
- do not bypass coverage, cost, embargo, exact replay, walk-forward or promotion gates;
- keep `research_only=true` and `trade_ready=false` unless a separately governed process changes that status.

## Legacy policy

Deprecated scripts are not an API. When a maintained path replaces them, delete them rather than moving them into a compatibility directory. Historical evidence belongs in specs, manifests, receipts and Git history—not in executable fallback code.
