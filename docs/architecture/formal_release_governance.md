# Formal release governance

Alpha Engine exposes one active formal model per stable product strategy. Historical research evidence may retain superseded models, but **active identity is owned only by `configs/strategies/registry.json`**.

The stable product strategy families are `qqq_rotation`, `us_x`, `cn_x` and `byd`. Their current `model_version_id` values are not copied into this document; every production consumer must resolve them from the Active Strategy Catalog.

All active strategies remain `research_only=true`, `trade_ready=false` unless the governing product contract is explicitly changed.

## Evidence layers

### Repository research catalog

`data/research/catalog.json` may retain active and superseded research runs when their immutable evidence remains useful. Historical presence does not make a model active.

### Active Strategy Catalog

`configs/strategies/registry.json` answers the product question:

> Which stable strategies exist now, and which model version currently represents each one?

Formal publication, Strategy Operations and frontend current-state policy must agree with this catalog exactly. README text, workflow names and old model registries are not identity authorities.

### Formal Model Run Bundle v2 catalog

`data/research/formal_model_runs/catalog.json` is the active formal evidence catalog exposed to Strategy Console. Its model-version set must equal the Active Strategy Catalog exactly.

An active strategy's formal evidence may currently be produced from either:

- a governed deterministic source package that is projected into Bundle v2; or
- a native Bundle v2 run that is validated and promoted into the formal catalog.

The partition is executable implementation detail and must be enforced by the formal sync path; documentation must not become a second model-to-source registry.

There is no active v1→v2 migration registry, compatibility reader or projector layer. Any internal flat source package is a deterministic input until that strategy becomes native Bundle v2; it is not the public evidence contract.

## Promotion means identity over immutable evidence

A formal promotion should preserve the already-observed economic evidence and assign accepted formal identity through a reviewed contract. It must not silently retrain, reopen model selection or substitute newer provider bytes.

For native Bundle v2 runs, promotion is a validated reference/materialization of the immutable run into the formal catalog.

For source-backed models, the Bundle v2 builder maps only retained source evidence into the canonical sections. Missing evidence stays `not_retained` / `not_applicable`; the builder does not invent metrics, fills, PnL, IC or diagnostics.

## Reviewed refresh transaction

The reviewed refresh transaction owns evidence extension, not model selection.

Required sequence:

1. resolve provider/component identity and common market cutoffs;
2. enforce exact incumbent replay gates where applicable;
3. extend only accepted source/native evidence using governed execution semantics;
4. build the complete active Bundle v2 catalog from the Active Strategy Catalog;
5. verify immutable historical prefixes, source hashes, freshness and catalog parity;
6. open a review PR containing **canonical evidence only**;
7. merge only after required checks pass;
8. regenerate Strategy Operations and frontend projections from the reviewed canonical state;
9. deploy the exact reviewed merge SHA and pass live Pages acceptance.

A reviewed refresh PR does not commit generated `data/research/strategy_operations/` or `qlib-dashboard/public/data/`.

## Superseded model retirement

A superseded model is historical evidence only after its successor becomes the accepted active model for the same stable strategy.

- superseded versions are not in the Active Strategy Catalog;
- they are not active formal source packages;
- they are not refreshed to satisfy current product state;
- no compatibility adapter relabels predecessor evidence as the successor;
- useful historical lineage may remain referenced by immutable successor evidence.

Promotion replaces active execution identity instead of growing a parallel compatibility path.

## Strategy decisions are companion evidence

Formal historical evidence and current decisions are intentionally separate:

```text
Formal Bundle v2          append-only Decision Ledger
       │                            │
       └────────────┬───────────────┘
                    ↓
            Strategy Operations
              generated read model
```

A formal run does not embed mutable Telegram/GitHub delivery state. The browser does not reconstruct current holdings from backtests.

## Pages publication impact

Pages impact detection follows canonical publication dependencies, including:

- frontend source;
- Active Strategy Catalog;
- active formal Bundle v2 evidence;
- repository research/model/market/model-data evidence used by the public product;
- append-only Strategy Decision Ledgers;
- static exporters, contract validators and deployment workflows.

Generated Strategy Operations and `public/data` are outputs, not change-authority inputs.

The detector fails closed when the dependency graph or commit range cannot be resolved.

## Production acceptance gates

A required Pages release must verify:

- exact deployed commit;
- active strategy/model identities exactly match the Active Strategy Catalog;
- formal manifest and section hashes;
- research-only / not-trade-ready boundary;
- regenerated Strategy Operations parity with formal identity;
- no superseded model appearing as current through fallback;
- no required resource failures or page-level runtime errors;
- desktop/mobile browser acceptance.

## Formal promotion provenance

Retained historical promotion manifests/archives remain evidence of previously accepted baselines where they are still required for byte-exact reproduction. They are provenance, not an alternate active catalog.

Do not add new archive/migration machinery automatically for models that can be promoted from immutable Bundle v2 evidence directly. Prefer the native current contract and delete superseded promotion plumbing once it is no longer an evidence dependency.

## Invariants

- one stable strategy has one active model version;
- one Active Strategy Catalog owns current identity;
- Bundle v2 is the formal frontend evidence contract;
- no model selection during refresh;
- no historical evidence recomputation during promotion;
- no compatibility fallback for superseded active versions;
- missing evidence stays missing rather than synthesized;
- generated frontend/read-model projections are rebuildable outputs;
- formal acceptance never implies broker execution or trade readiness.
