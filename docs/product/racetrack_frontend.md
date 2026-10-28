# Racetrack in the existing Dashboard

Scope: 2026-10-28 user-authorized frontend for the merged research publication
contract. This view is not a fifth formal strategy or a release acceptance gate.

Open Overview, then **Racetrack research**. Strategy monitor remains the default;
Overview and Status remain the primary navigation destinations. The view offers
US/CN selection, 1M/3M/6M/1Y display windows, one NAV chart, the published Top 10,
and a focus-managed Runner detail dialog. Closing the dialog preserves selection.
Overview mode, market, window, selected Runner and dialog state are encoded in
the existing hash-route query parameters. Links, reload and browser history
restore the same view; invalid market/window parameters use US/3M defaults.
Changing market clears the prior Runner selection. A link never bypasses local
access or artifact validation, and an unknown Runner does not open a detail.

## Evidence path and local operation

1. Use the existing `uv run --frozen alpha racetrack publish --market us`
   command from the repository root, with the intended cutoff/start-date options.
   This is the explicit research operation; the browser never invokes it.
2. Run `npm run dev -- --host 127.0.0.1` in `qlib-dashboard`, or build and run
   Vite preview on loopback. Open that local Dashboard. No additional service,
   scheduler, database, registry, model or provider is introduced.
3. The existing Vite server reads `data/racetrack/projections/{market}` through
   `/__racetrack/{market}/manifest.json` and declared immutable artifact URLs.
   Only GET, loopback clients and same-origin requests are accepted. Arbitrary
   paths, symlink escapes, invalid identities, size/hash mismatches and other
   markets' artifacts fail closed. Responses are `no-store` with no CORS grant.
4. Published research files are ignored by Git and never copied to `public/`
   or `dist/`. Hosted Pages displays the local-reader explanation and makes no
   Racetrack request. Existing account entitlements/current-operations readers
   remain independently enforced; localhost is not an entitlement bypass.

An empty registry is an honest benchmark-only view. This PR does not add default
competitors or reinterpret the four formal strategies as research runners.
Interactive test data is explicitly synthetic and stays in `e2e/fixtures`.

## Reused and extended publication contract

The frontend reads pipeline v1.1, schema v1.0, including its exact pool, market,
cutoff, season, release ID, cost settings, artifact sizes and SHA-256 digests.
It validates the scoreboard's ordered dates, series lengths, finite metrics,
published ranks, model identities and research-only boundary before rendering.
An in-memory cache holds only verified artifacts at an exact market/vintage/hash;
manual refresh re-reads the manifest. Abort guards prevent late market/detail
responses from replacing the current view. There is no background polling.

The existing publisher now optionally adds `runner_details` references and one
hash-bound JSON artifact per evaluated Runner, in the same immutable vintage:
full thesis, selection/rebalance logic, hypothetical replay-cutoff model weights,
monthly ranks and explicit limitations. These come from the same RunnerContract
and SimulationResult; no runner is evaluated a second time. Detail content is
part of release identity, including thesis edits beyond the truncated summary.
Old projection vintages without details remain readable as summary-only data.
Rebalance ledgers and measured indicator associations are absent and labelled
accordingly; the frontend does not manufacture them from turnover or prose.
The admitted Runner contract allows empty selection/rebalance descriptions;
these display as undocumented without discarding the verified thesis and weights.

Only the scoreboard and its Top 10 NAV series load initially. A detail artifact
loads on selection and remains bound to that pinned vintage even if the current
manifest advances. Detail failure leaves verified rankings and NAV readable.

## Display and interpretation

- Rankings are the publisher's **cumulative** ranks. Window changes do not
  re-rank runners; per-window Top 10 ranking is not present in the merged
  contract. Returns use the corresponding precomputed period fields.
- Display-only slicing follows calendar-month buckets, including partial first
  or last months. Curves rebase to 1 at the first displayed session. Available
  month counts and starting dates remain visible. Missing starts cannot be
  rebased; null gaps remain disconnected line segments, never interpolations.
- Season points are provisional until complete-window review. Chart rebasing
  can differ from a published return that includes inception friction. Excess
  comparisons use the published 1Y period when available, otherwise full replay;
  they do not follow the chart's selected window.
- Market/pool, actual evidence dates, recorded generation timestamp, friction,
  vintage and revision-uncertified qualification stay visible. Reading/refreshing
  is not proof of a fresh research run, PIT certification or live availability.
- Table, legend and curve selection share one Runner identity. A keyboard date
  control provides a textual NAV readout. Existing chart consumers remain
  maintained; only the Racetrack wrapper imports its new charting engine.

## Charting and validation

Uses pinned [TradingView Lightweight Charts v5](https://tradingview.github.io/lightweight-charts/docs/5.0)
(5.2.1), following the existing confirmed chart decision. Its attribution logo,
visible TradingView link and [NOTICE](https://github.com/tradingview/lightweight-charts/blob/master/NOTICE)
are retained. No replacement of maintained instrument-history charts is implied.

Validation uses the existing backend CI, frontend unit/build checks, a Node
test of the local read boundary, and repository Playwright static acceptance.
The Browser plugin is not available in this session, so repository Playwright
is used for rendered QA. Tests cover default-monitor isolation, chart/legend/
table/detail interactions, missing/history-short/baseline states, hash and
identity rejection, late-response isolation, desktop/tablet/mobile, keyboard
access and overflow. This does not close #1288 or Direction A live release gates.

Local acceptance on 2026-10-28: 85 relevant Python tests, 234 frontend unit tests,
5 local-reader boundary tests and 102 browser tests passed. TypeScript, ESLint,
Ruff, dependency audit, bundle budget and repository governance checks passed.
The follow-up contract/URL restoration changes passed all 18 Racetrack browser
cases, including reload, browser back/forward and invalid query parameters.
A real local publication smoke check loaded the manifest and scoreboard through
Vite without mocking the research endpoint; the empty registry displayed its
two benchmarks and an empty leaderboard.

Review screenshots use explicitly synthetic test fixtures, not investment
results: [desktop NAV](../evidence/racetrack_frontend/synthetic-desktop.png) and
[mobile detail](../evidence/racetrack_frontend/synthetic-mobile-detail.png).

## Landing status against the original frontend vision

This is the bounded NAV/Top 10/detail delivery requested for PR #1311. The older
vision's larger list is not a statement that every item is implemented here:

- Delivered: existing-shell integration, pinned chart engine, verified projection
  client, window slicing/rebasing, chart/legend/table selection, lazy details,
  provenance/limitations, keyboard readout and URL/history restoration.
- Requires future source contracts: per-window rankings/NAV membership, settled
  month snapshots, judged drawdown/indicator series, event markers, rebalance
  ledger chunks and measured association profiles. Do not calculate these in
  the browser or infer settlement from the current provisional monthly ranks.
- Deferred presentation work: benchmark-only filter and reciprocal row-hover
  chart highlighting. No model/readiness promotion depends on these controls.

The authoritative four-strategy monitor remains maintained. Neither this PR nor
the older vision's proposed observation-view replacement authorizes retiring it.
