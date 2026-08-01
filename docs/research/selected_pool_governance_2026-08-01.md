# Selected-Pool Research Governance

Date: 2026-08-01  
Decision issue: #263

## Final membership decision

The user approved every deletion candidate in Issue #263 except `TIGO`.
`TIGO` is retained specifically as **Millicom International Cellular**. It must
never be interpreted as Tigo Energy or placed in an energy-infrastructure basket.

The authoritative selected universes are:

- US: `configs/research_universes/us_selected_equities_v2.yaml` — 87 candidates.
- CN: `configs/research_universes/cn_selected_equities_v2.yaml` — 163 candidates.

All new experiments, validations and backtests must bind to one of these
versioned files and record the pool identity and membership hash. The former
broad curated v1 universes remain available only for historical reproduction and
diagnostics.

## Data actions

### Removed from active CSV data

- US: 46 approved redundant candidates.
- CN: 58 approved redundant candidates.
- `ALBA.csv`: previously removed as orphan/corrupt data.

### Retained with explicit identity or lifecycle boundaries

- `TIGO`: retained as Millicom. No `csv_clean` file existed at selection time, so
  a verified provider refresh is required before authoritative use. The selected
  pool guard blocks authoritative US runs until that data-readiness blocker is
  cleared; silent exclusion is prohibited.
- `TYGO`: retained as Tigo Energy; unavailable before 2023-05-24.
- `SNDK`: forward-only from 2025-02-24; `WDC` is the historical storage proxy.
- `600837` and `601989`: historical rows retained for reproduction, but neither
  is eligible for a new authoritative run after its terminal listing date.

The lifecycle contract is
`configs/data_quality/symbol_identity_and_lifecycle_v1.yaml`.

## Active paths

The selected-pool registry is
`configs/pools/selected_pool_registry_v1.yaml`.

- General US research resolves to `us_selected_equities_v2`.
- General CN research resolves to `cn_selected_equities_v2`.
- The existing US hierarchical rotation strategy remains bound to its narrower
  strategy pool, `us_small_pool_v2`, which is a subset/strategy-specific pool and
  does not reclassify Millicom as an energy company.

`src/data/universe.py` now resolves the selected-pool registry before any legacy
watchlist file. A broad-universe fallback is therefore not valid for new
authoritative work.

## Change control

1. Membership changes require a new immutable version.
2. Membership must be frozen before performance is inspected.
3. Weak performers cannot be removed retrospectively from an observed version.
4. Benchmarks, ETFs and reference instruments remain separate from candidate
   equities.
5. Every run manifest must record pool path, pool identity and membership hash.

## Repository-size policy

Deleting current CSV files reduces future working-tree size but does not remove
objects already stored in Git history. Market-data migration, Git LFS/object
storage, or a history rewrite remains a separate operation requiring explicit
approval.
