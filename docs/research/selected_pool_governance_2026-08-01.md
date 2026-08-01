# Selected-Pool Research Governance

Date: 2026-08-01  
Decision issue: #263

## Decision

All new AlphaEngine experiments, validations and backtests must use an explicit,
versioned selected stock pool. The previous broad curated universes remain only
for historical reproduction, coverage diagnostics and universe-design work.
They are not valid fallbacks for new authoritative results.

## Immediate data corrections

### US

- `TIGO` is not Tigo Energy. It is excluded from the energy and AI-infrastructure
  basket. The intended Tigo Energy security is `TYGO`.
- `SNDK` began independent regular-way trading on 2025-02-24. It is not permitted
  to carry an artificial pre-2025 standalone history. `WDC` is used as the
  historical storage-industry representative; `SNDK` remains forward-only.
- `ALBA.csv` was an orphan, sparse and invalid series and has been removed from
  active data.

### CN

- `600837` and `601989` are terminal listings following absorption mergers.
  Their historical rows remain available for reproduction, but neither may enter
  a new run after its terminal date.

The authoritative lifecycle rules are stored in
`configs/data_quality/symbol_identity_and_lifecycle_v1.yaml`.

## Pool state

### US

`configs/pools/us_small_pool_v2.yaml` is the active selected pool. It is a
correction-only child of v1 and preserves the same seven-basket, 23-candidate
structure while correcting the two identity/history errors.

The active research path is
`configs/research_paradigms/us_structured_pool_hierarchical_rotation_v3.yaml`.
It prohibits broad-universe fallback and binds every run to a pool version and
membership hash.

### CN

CN selection is intentionally blocked until the user approves the membership
choices in Issue #263. Before activation, only data-quality diagnostics,
coverage checks and selection design without performance review are allowed.

The two terminal listings are mandatory exclusions. All other removals are
selection decisions, not data repairs.

## Activation sequence

1. User checks the US/CN removal candidates in Issue #263.
2. Create a new immutable pool version for each market from those decisions.
3. Record parent version, additions, removals, reasons and effective date.
4. Bind the pool path and hash into the experiment specification and manifest.
5. Run identity, lifecycle, coverage and benchmark checks before any backtest.
6. Freeze membership before inspecting performance.
7. Never remove a weak performer retrospectively from an observed pool version.

## Repository-size policy

Removing current CSV files reduces the size of future working trees but does not
remove objects already stored in Git history. After pool selection stabilizes,
market data should move out of the source repository. The repository should keep
only versioned manifests, source identities, hashes, coverage reports and
reproducible acquisition scripts. A history rewrite or object-storage migration
must be a separate, explicitly approved operation.
