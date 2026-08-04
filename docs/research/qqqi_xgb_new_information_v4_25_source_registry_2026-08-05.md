# v4.25 new-information official source registry

Date: 2026-08-05

This registry is source evidence only. It contains no returns, labels, model fitting or portfolio decisions.

## Cboe put/call archives

Official historical-options page:

- `https://www.cboe.com/us/options/market_statistics/historical_data/`

Canonical public CSVs identified from the official page:

- total exchange put/call: `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv`;
- equity put/call: `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv`;
- index put/call: `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/indexpc.csv`;
- ETP put/call: `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/etppc.csv`.

The official page describes the recent CSV range as 2006-11-01 through 2019-10-04 and directs later/custom history to the current daily statistics page or Cboe DataShop. A family that requires continuous 2011-current history must therefore reject the archive unless a single authoritative post-2019 continuation with stable timestamp semantics is established.

The Phase 0 contract applies a one-QQQ-session safety lag because the ratios summarize the completed options session and are not assumed observable before that same session's equity close.

## Cboe SKEW

Official dashboard and governance documents:

- `https://www.cboe.com/us/indices/dashboard/SKEW/`;
- `https://cdn.cboe.com/api/global/us_indices/governance/Consultation-Regarding-Proposed-Changes-to-the-Cboe-SKEW-Index.pdf`;
- `https://cdn.cboe.com/resources/release_notes/2025/Consultation-Results-Regarding-Proposed-Changes-to-the-Cboe-SKEW-Index-SKEW-.pdf`.

Cboe states that SKEW is calculated once per day at the close of US trading. The 2025 consultation also states that a methodology change could recalculate index history. Without an immutable vintage history and a confirmed public numeric endpoint, SKEW is classified as documentation-only and revision-unsafe for Phase 0.

## FRED / ICE BofA option-adjusted spreads

Canonical series:

- high yield OAS: `BAMLH0A0HYM2`;
- US corporate OAS: `BAMLC0A0CM`.

Public CSV endpoints:

- `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`;
- `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A0CM`.

FRED identifies both as daily close series sourced from ICE Data Indices. Current series notes state that from April 2026 the public FRED series retain only three years of observations. That cannot satisfy the governed 2011 history requirement.

The series are also subject to ICE top-level-data use restrictions. Phase 0 stores source hashes and date availability but does not commit or publish the numeric values. Current revised history is not treated as vintage-safe without a documented vintage contract.

## Breadth and option-positioning families

No canonical, public, survivorship-safe 2011-current breadth source or transparent historical dealer-positioning source is configured in AlphaEngine at the start of v4.25. These families remain `unresolved` and must fail rather than be reconstructed from today's constituents, screenshots or opaque vendor scores.

## Admission boundary

A later XGBoost feature contract requires at least one complete family to pass all of the following before outcomes:

- documented source identity and publication timing;
- continuous 2011-current coverage on QQQ decision dates;
- safe revision/vintage status;
- acceptable use restrictions;
- no survivorship reconstruction or synthetic backfill;
- non-empty coverage in every governed fold and 2024+ quarantine window.
