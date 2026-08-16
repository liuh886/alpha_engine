# Issue #966 Phase 5 — factor evidence and agent discovery

Status: **COMPLETE.**

Phase 5 adds no factor engine and no duplicate formula catalog. Canonical executable definitions remain in `FactorLibrary` sources. The new layer is a **derived research index** for agent discovery and factor-level evidence.

## Canonical registry

`configs/factor_catalog.yaml` registers the maintained definition owners:

- canonical OHLCV factors;
- canonical strategy inputs;
- Issue #966 volume-flow research;
- Phase-4 distribution-risk research;
- package-backed Qlib Alpha158.

It also registers the active US/CN baseline model contracts and normalized evidence sources. No formula is copied into the registry.

## Factor-level evidence

`src/factors/evidence.py` defines immutable evidence records bound to:

- canonical `factor_id` + `implementation_hash`;
- market and use case;
- target horizon where applicable;
- provider identity, universe identity/count and cutoff;
- structural validation summary;
- research metrics;
- final disposition;
- authoritative receipt paths.

The existing feature-quality receipt can normalize directly into this record, including usable rows, first-valid range, observed warm-up range, post-warm-up coverage, inf/constant checks, no-future expression window and deterministic reproduction. Formula execution remains on the existing Qlib/provider path.

## Agent-facing derived index

`src/factors/research_index.py` projects canonical FactorLibraries, active `us_x1_2` / `cn_x1_2` contracts and normalized evidence into one queryable index.

Each factor exposes definition identity, canonical source, category/information family, deterministic mechanism stem, group membership, markets, active models, market-specific status and evidence links. Queries support category, mechanism, market and status.

`model_active` is derived from active model configs and overrides research status only for that market. Research evidence cannot rewrite formula identity.

## Validated build

Authoritative Phase-5 workflow: `31945275276` at head `118f46abda9f51d7197fdb4f345bc95c35a83908`.

The validated derived index contains:

- **201 canonical factors** across five registered libraries;
- **9 normalized Issue #966 evidence records**;
- **24 market-level model-active entries**;
- explicit candidate / validated / rejected / diagnostic-only research dispositions where evidence exists.

Index SHA-256: `408780a13350dffc7b6ba388a1c341c63d269f3b32ae47ba636af06d19884666`.

Artifact: `issue966-phase5-factor-index-31945275276`, ID `9263114323`, digest `sha256:717da8075ceed8b117ea53d14e37bf0d02f7d4618400b82d8029944515368d55`.

`data/research/factor_catalog/manifest.json` pins this build. The 250KB generated index itself is intentionally not checked in; it is deterministically rebuilt from canonical definitions/evidence with:

`uv run python scripts/build_factor_research_index.py --output artifacts/research/factor_index.json`

This avoids making a generated copy another source of truth.

## Issue #966 dispositions now discoverable

- signed-volume: US candidate only as a component of the surviving joint set; CN rejected;
- CORD10: US candidate only as a component of that joint set;
- RANK20: US candidate component; CN rejected;
- skew20: US validated risk-control candidate; CN diagnostic-only;
- kurt20: diagnostic-only in both markets;
- CORD5: CN `model_active` is derived directly from `cn_x1_2`.

## Fail-closed rules

Index construction rejects:

- duplicate canonical factor owners;
- active models referencing unregistered/unknown factors;
- evidence whose implementation hash differs from the canonical formula;
- missing authoritative receipt links;
- evidence for unsupported markets.

Phase 5 therefore establishes one agent entry point while preserving three separate authorities: FactorLibrary owns formulas, model configs own active inputs, and research receipts own evidence.
