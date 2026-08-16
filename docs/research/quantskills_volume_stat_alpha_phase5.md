# Issue #966 Phase 5 — factor evidence and agent discovery

Status: **implementation in progress**.

Phase 5 does not create another factor engine or another formula catalog. Canonical executable definitions remain in `FactorLibrary` sources. This phase adds one **derived research index** so agents can discover factors and evidence without reading model configs, research receipts, and source modules separately.

## Canonical source registry

`configs/factor_catalog.yaml` registers the maintained definition owners:

- canonical OHLCV factors;
- canonical strategy-input factors;
- Issue #966 volume-flow research factor;
- Phase-4 distribution-risk research factors;
- package-backed Qlib Alpha158 definitions.

It also registers the active US/CN research baseline model contracts and normalized evidence sources. The registry contains no copied formula.

## Factor evidence record

`src/factors/evidence.py` defines the factor-level evidence contract. Every record binds:

- canonical `factor_id` + `implementation_hash`;
- market;
- evidence status/use case;
- target horizon when applicable;
- provider identity, universe identity/count and cutoff;
- structural validation summary;
- research metrics when available;
- final disposition;
- paths to authoritative receipts.

The existing feature-quality receipt can be normalized directly into this contract, including usable rows, first-valid range, observed warm-up, post-warm-up coverage, inf/constant checks, expression window and determinism. Formula execution remains in the existing Qlib/provider path.

## Derived agent index

`src/factors/research_index.py` builds one queryable read model from:

1. registered canonical FactorLibraries;
2. active `us_x1_2` / `cn_x1_2` model factor contracts;
3. normalized research evidence.

For each factor it exposes definition identity, source, category/information family, deterministic mechanism stem, group membership, supported markets, active models, market-specific status, and evidence links.

The index is queryable by:

- category;
- mechanism;
- market;
- status.

`model_active` is derived from active model contracts and therefore overrides research-candidate status in the corresponding market. Research evidence never rewrites formula identity.

## Issue #966 normalized evidence

`data/research/factor_evidence/issue966.json` converts the Phase-1/2/4 decisions into factor-level records without replacing the raw gate receipts.

Important market distinctions are preserved:

- signed-volume: US candidate only as a component of the surviving joint set; CN rejected;
- CORD10: US candidate only as a component of the joint set;
- RANK20: US candidate component; CN rejected;
- skew20: US validated risk-control candidate; CN diagnostic-only;
- kurt20: diagnostic-only in both markets;
- CORD5: CN `model_active` is derived directly from `cn_x1_2` rather than duplicated into evidence.

## No new source of truth

The checked/generated factor index is a **derived read model**. The validation rules fail closed when:

- a factor ID has multiple registered canonical owners;
- an active model references an unregistered/unknown factor;
- evidence implementation hash differs from the current canonical formula;
- evidence links point to missing receipts;
- evidence market is unsupported by the canonical factor.

This keeps formula identity, model identity, and research evidence separate while giving agents one entry point for discovery.
