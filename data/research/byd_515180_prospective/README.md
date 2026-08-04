# BYD / 515180 prospective sleeve store

This directory is append-only research evidence for Issue #529.

The store is populated by `.github/workflows/byd-515180-prospective.yml` after a sealed BYD prospective observation exists. It contains:

- `observations/YYYY-MM-DD.json` — immutable paired BYD/515180 observations;
- `outcomes/*.json` — immutable 5/10/20-common-open and completed-defense-episode settlements;
- `ledger.csv` — deterministic derived index;
- `scorecard.json` — deterministic prospective summary;
- `manifest.json` — identities, counts and derived-file SHA-256 values.

Existing observation and outcome files may never be rewritten. Secondary market data is audit-only and is never stitched into the primary series.

- `research_only=true`
- `trade_ready=false`
- `shadow_only=true`
