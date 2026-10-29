# Strategy detail: return evidence scope

Implemented from [frontend audit #1315](https://github.com/liuh886/alpha_engine/pull/1315),
P0-2 and P0-3. Baseline: `main@228f318b0cd8e4eb5905bc4ee995b77793c8ba67`.
This changes the existing detail presentation and default comparison selection.
It does not change sealed bundles, source metrics, active strategies or scoring.
`research_only=true`, `trade_ready=false`.

## Diagnosis and resulting behavior

US x1.3's retained summary has a total return of 511.233% with 68 observations.
Its declared run window is 2024-01-02 through 2026-10-27. The chart payload has
69 wealth observations: 68 non-provisional records through 2026-10-23 and one
2026-10-27 provisional mark. Its first holding-end observation is 2024-01-17,
with account 0.9250323481126265. The chart payload does not retain opening
`account_before` or `bench_qqq_before` on that first row.

The chart therefore compares the first observed wealth with the last, including
the provisional mark: 593.70%, rather than the source total return. The source
builder explicitly initialized wealth to 1, but that field is absent from the
sealed chart payload. This patch does not hardcode an opening value in a generic
reader or reverse-engineer one from the headline. Instead:

- Source cards retain their values and sample counts, with the declared run
  window visibly labelled. A shared scope section distinguishes that window
  from each metric's own observation set and identifies provisional chart rows.
- The chart labels its actual observation window/count as a **chart comparison**,
  explains its strategy/benchmark anchor, and identifies selected provisional
  marks as unsettled. It explicitly distinguishes the comparison from source
  metrics. Existing explicit opening-wealth fields still include the first
  interval; a subrange starts at the first selected observation.
- Missing benchmark/excess values have a visible reason. A different available
  comparison is not silently substituted for a missing declared benchmark.

BYD declares **BYD v1.2**, a prior strategy version, as its formal benchmark.
All 1,664 rows retain `bench_byd_v1_2`. The loader incorrectly forced the chart
benchmark to BYD stock, whose separate optional price series did not provide the
declared comparison. The loader and panel now use the declared benchmark; the
stock series remains an optional comparison. With the same source bundle:

| Rendered chart result | Before | After |
| --- | --- | --- |
| BYD default comparison | BYD stock | BYD v1.2 strategy |
| BYD benchmark return | unavailable | 510.57% |
| BYD relative excess | unavailable | 9.75% |
| US comparison return | 593.70%, insufficient basis explanation | 593.70%, explicit observation anchor/window/provisional explanation |

The US summary and curve are **not numerically reconciled by this patch**.
Unifying their basis requires a new source projection with explicit opening
wealth and metric observation boundaries, bound to the source identity. Old
sealed artifacts must remain immutable. Other #1315 work, including loading
states, fleet windows and driver presentation, remains separate.

## Verification

Browser plugin not available; used the repository's regular Playwright path.
Flow: strategy detail → published source metrics → chart comparison/window →
declared benchmark selection and optional stock comparison.

- 245 frontend unit tests passed, including synthetic negative cases for absent
  benchmark boundaries and declared initial wealth; focused tests: 27 passed.
- TypeScript, changed-file ESLint, production build and diff checks passed.
  JavaScript gzip size: 381.92 KB, within the existing 480 KB budget.
- New actual-artifact US/BYD browser flow passed on desktop, tablet and mobile:
  no page errors or horizontal overflow, declared BYD v1.2 selected, optional
  stock comparison retained, source-vs-chart explanation visible.
- A separate before/after browser read reproduced the values above from the
  same formal source artifacts without mocking a formal-data endpoint. Only the
  optional account widget was isolated; no protected operations were enabled.
- Screenshots of the source metrics and comparison panels were inspected;
  browser evidence remains in the existing test artifacts. Full-suite results
  and hosted checks are recorded in the implementation PR.

No new dependency, route, service, registry or workflow was added. The original
operator workspace's uncommitted changes were not used or modified.
