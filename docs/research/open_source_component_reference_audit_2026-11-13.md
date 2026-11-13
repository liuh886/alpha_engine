# Open-source component reference audit — 2026-11-13

> **RESEARCH ONLY.** This document authorizes **no dependency, workflow, scheduler, page or
> navigation change**. Every proposed dependency needs explicit Owner approval. Alpha Engine
> remains `research_only=true`, `trade_ready=false`; nothing here is a live-trading or
> investment recommendation. References were fetched and license-checked on 2026-11-13;
> anything not fetched is listed under **Unverified**.

Scope: maintained/upcoming components vs. the smallest OSS project that already solves the same
problem. Local state audited at `1f701c438d` (clean tree). **P0** blocks/materially improves
Today or the correctness of returns/excess/evidence; **P1** low-risk quality uplift; **P2** later.

## Summary

| # | Area (our code) | Best OSS reference (license) | Smallest move | Pri |
|---|---|---|---|---|
| 1 | Evidence writes (`src/artifacts/**`, `snapshot_manifest.py`) | `untitaker/python-atomicwrites` (MIT) | adapt ~12 lines | P0 |
| 2 | Canonical identity (`model_run_bundle_v2.py:69`) | RFC 8785; `in-toto/attestation` v1 (Apache-2.0) | pattern + version bump | P0 |
| 3 | Markdown brief (`research-summary.ts`) | `mdast-util-to-markdown` `lib/unsafe.js` (MIT) | adapt ~20 lines | P0 |
| 4 | Returns horizons (`performancePeriods.ts`, `StrategyFleet.tsx`) | `quantopian/empyrical` (Apache-2.0) | pattern + boundary tests | P0 |
| 5 | Instrument chart lifecycle (`SecurityLightweightChart.tsx`) | `lightweight-charts` 5.2.1 (Apache-2.0) | config + ~60-line refactor | P0 |
| 6 | Comparison table (`PositionsTable.tsx`, fleet) | `TanStack/table` virtualized-rows + sorting (MIT) | pattern | P1 |
| 7 | Equity-curve downsampling | `d3fc/d3fc` `largestTriangleThreeBucket.js` (MIT) | adapt ~40 lines | P1 |
| 8 | Data-quality reporting (`validation/schema.py`) | `pandera` lazy validation (MIT) | pattern | P1 |
| 9 | Revision/as-of history (`fundamentals/event_store.py`) | dbt snapshot semantics (Apache-2.0) | pattern only | P1 |
| 10 | CI path filters (`.github/ci-policy.json`) | `dorny/paths-filter` v3 (MIT) | wording only, no workflow | P1 |
| 11 | Sparkline column (not built) | `tremorlabs/tremor` SparkChart (Apache-2.0) | **do not copy** | P1 |
| 12 | Sampling alternatives | `apache/echarts` `dataSample.ts` (Apache-2.0) | pattern only | P2 |
| 13 | Null-gap lines | `leeoniya/uPlot` `paths/linear.js` (MIT) | pattern only | P2 |
| 14 | Corporate-action factors | `zipline-reloaded` `adjustments.py` (Apache-2.0) | reference only | P2 |
| 15 | Trial dedupe on resume | `optuna` `study.py` 3.6.1 (MIT) | pattern only | P2 |
| 16 | Clipboard fallback (`DailyResearchBrief.tsx:19`) | `feross/clipboard-copy` (MIT) | no change | P2 |
| 17 | Dataset fingerprinting | `huggingface/datasets` `fingerprint.py` (Apache-2.0) | **do not copy** | P2 |

No copyleft reference is recommended; every cited license is permissive. A citation is not an
authorization to add a dependency.

## P0

### 1. Atomic, durable evidence writes
`https://github.com/untitaker/python-atomicwrites/blob/master/atomicwrites/__init__.py` (MIT).
Verified: `AtomicWriter.get_fileobject()` uses `mkstemp(..., dir=parent)`; `sync()` does
`flush()` + `_proper_fsync(fileno())`; POSIX replaces with `os.rename`, Windows `MoveFileExW`
with `_MOVEFILE_REPLACE_EXISTING`; `_sync_directory()` fsyncs the parent after commit;
`rollback()` unlinks the temp file. Atomicity requires same-filesystem, same-parent temp files.
Our code: `model_run_exporter.py:244-255` already stages a bundle directory then `os.replace`
(good). `resumable_score_artifacts.py:65-73` has a single-file helper (temp, flush, fsync,
replace) but no parent-dir fsync and no cleanup on exception. `snapshot_manifest.py:89-92`
(`SnapshotManifest.write`) and `operating_acceptance.py:35,162,202,222` use plain
`path.write_text`; many `write_bytes` sites (`formal_provider_cache.py:94`,
`model_run_decision.py:126,255`, `strategy_signal_ledger.py:295`) share the exposure. A crash
or full disk can leave a truncated manifest that downstream verification reads as authoritative.
Move: promote one shared write helper and use it for every single-file evidence write; fsync the
directory after replace on POSIX (~12 lines, attribution). Risk: Windows cannot fsync a directory
handle; guard with `os.name != "nt"`. Do not copy `move_atomic`'s hard-link path or legacy
permission handling.

### 2. Canonical identity is not externally canonical
RFC 8785, `https://www.rfc-editor.org/rfc/rfc8785.txt`. Verified: numbers follow ECMAScript
`Number::toString`; `-0` becomes `0`; `NaN`/`Infinity` MUST error; strings escape only
U+0000–U+001F, `"` and `\`; keys sort recursively by **UTF-16 code units**; output is UTF-8.
`https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md` (Apache-2.0):
`subject[].digest` is `{algorithm: hex}`, `predicateType` is a URI, `predicate` optional.
Our code: `model_run_bundle_v2.py:69-85` uses
`json.dumps(sort_keys=True, separators=(",",":"), allow_nan=False)`. Deterministic among Python
processes, but **not** JCS: Python sorts by code point (differs for non-BMP keys) and renders
floats by `repr`, so a JS/Go verifier cannot reproduce `bundle_id`. `snapshot_manifest.py:44-52`
shares this property for `snapshot_id`.
Move: either document "canonical-form-v1 (Python)" and keep hashes internal, or implement JCS
for our subset (strings, finite floats, small ints) with golden vectors. Pattern-only. Risk:
changing the canonicalizer rewrites every `bundle_id`; gate behind `identity_version` and keep
old readers. Statement-v1 shape is additive and must not be used to claim SLSA compliance.

### 3. Markdown brief escaping
`https://github.com/syntax-tree/mdast-util-to-markdown/blob/main/lib/unsafe.js` (MIT).
Verified construct model `{atBreak: true, character, before, after}`: `#`, `*` (followed by
space/tab/newline/`*`), `-` (space/tab/newline/`-`), `+`, `>`, `=`, `~`, backtick, `_`, `[`, and
`\d+` followed by `.`/`)` — escaped only at line start.
Our code: `research-summary.ts:21-23` `sanitize()` collapses whitespace but does not escape
Markdown; dynamic text is emitted into headings/list items at `:70-76` and `:96-97`. A title or
reason beginning with `- `, `# ` or `1. ` breaks the copied brief's structure.
Move: `escapeMarkdownInline()` (~20 lines) applied after whitespace collapse, with a unit test
for `- x`, `# x`, `1. x`, `` `x` ``, `> x`. Risk: over-escaping; restrict to first character and
the `after` lookaheads. Do not add remark/unified to the bundle for one string builder.

### 4. Multi-horizon returns and excess share one measured-window contract
`https://github.com/quantopian/empyrical/blob/master/empyrical/stats.py` (Apache-2.0).
Verified: `cum_returns` (L219) zero-fills NaNs before `cumprod`; `cum_returns_final` (L280) uses
`nanprod` for arrays but not DataFrames, so the two disagree; `max_drawdown` (L352) seeds
`cumulative[0] = 100`, returns `nanmin((cumulative-max)/max)`; `sharpe_ratio` (L651) uses
`nanmean`/`nanstd(ddof=1)` × `sqrt(ann_factor)`; `alpha_beta_aligned` (L1082) masks pairwise.
Tests `empyrical/tests/test_stats.py`: `test_cum_returns*`, `test_max_drawdown*`,
`test_alpha_beta_with_nan_inputs`, `test_cagr_with_nan_inputs`.
Counter-example: `quantstats@0.0.62 quantstats/stats.py` (Apache-2.0) `monthly_returns`
L1010-1086 fills missing months with `0` at L1040; `compare` L963-1007 is a ratio, not geometric
excess. Never copy the fill-zero into formal evidence.
Our code: `performancePeriods.ts:53-66` computes calendar bounds with end-of-month clamping;
`:76-97` starts subranges at the first settlement and refuses interpolation;
`PerformanceCharts.tsx:37-43` computes geometric period return; `:198-199` and
`StrategyFleet.tsx:292-295` compute `(1+r)/(1+b)-1` with `b > -1` guards. Stricter than
empyrical already. The gap is the upcoming multi-horizon comparison: one `PERIOD_OPTIONS` list
(`StrategyFleet.tsx:32-38`) and one measured window per row, with no shared
`{1w,1m,3m,1y,2y,3y}` helper.
Move: pure `horizonSummaries(report, horizons)` over `strategyPeriodSummary` returning
`measured | expired | insufficient | benchmark-unavailable`, no zeros, no forward fill. Use the
empyrical tests as the boundary checklist. Risk: 1w/2y were never validated against settlement
dates; never compare an expired window (we already detect it at `StrategyFleet.tsx:269-276`).

### 5. Instrument chart lifecycle and marker semantics
Installed `lightweight-charts@5.2.1` typings
(`qlib-dashboard/node_modules/lightweight-charts/dist/typings.d.ts:938-948,3958-4010`;
upstream Apache-2.0). Verified: `autoSize` watches the container via `ResizeObserver` and makes
`width`/`height` fallbacks; `SeriesMarkerBase` has `id`, `text`, `size` (default 1) and `price`
for exact Y positioning; `SeriesMarkersOptions` has `autoScale` (default true, markers expand
the price scale) and `zOrder`; docs confirm `createSeriesMarkers(series, markers?, options?)`.
Our code: `SecurityLightweightChart.tsx:45` reads dark mode once; `:140-147` listens to
`window.resize`, not the container; `:154` recreates the whole chart when `bars`, `events` or
`onSelect` change, so selecting a marker (parent state → new `events`) destroys pan/zoom;
`:105-119` omits `id`/`size` and `autoScale:false`, so markers can shift the visible price range.
Move: one chart instance; create series/markers once; update via `setData`/`setMarkers`;
`autoSize:true`; pass `id`, `size`, `autoScale:false`; re-read theme via `MutationObserver` or a
`useTheme` value. No new dependency. Risk: `autoSize` is ignored without `ResizeObserver`; keep
the canvas guard and explicit fallback width.

## P1

### 6. Comparison table: sorting contract and virtualized-table semantics
`https://github.com/TanStack/table/blob/main/examples/react/virtualized-rows/src/main.tsx` (MIT)
and `https://tanstack.com/table/v8/docs/api/features/sorting` (verified). The example keeps
semantic table elements but lays out with grid/flex: sticky `display:grid` thead (34px),
`position:relative` tbody with `height:getTotalSize()`, absolute rows translated by
`virtualRow.start`, explicit `<th>/<td>` widths, `measureElement` via `getBoundingClientRect`
(disabled on Firefox). Sorting: `sortUndefined` defaults to `1`, accepts
`'first' | 'last' | false | -1 | 1` (`'first'`/`'last'` since v8.16.0).
Our code: `PositionsTable.tsx:272-292` copies the absolute-row pattern but sets no
`aria-rowcount`/`aria-rowindex`, so assistive tech sees a partial table; `:283` gives tbody a
pixel height without a grid role. `StrategyFleet.tsx:245-254` is a CSS grid with no sort
affordance, labelled "Stable watchlist order" at `:520`.
Move: `role="table"` + `aria-rowcount` + per-row `aria-rowindex` (or the ARIA grid pattern);
for the multi-horizon table use a column model and `sortUndefined:'last'` so unavailable metrics
never sort as best. Pattern-only (`@tanstack/react-virtual` already installed). Risk: do not
copy `display:block` into the mobile stacked layout.

### 7. Equity-curve downsampling
`https://github.com/d3fc/d3fc/blob/master/packages/d3fc-sample/src/largestTriangleThreeBucket.js`
(MIT). Verified: interior buckets only (`slice(1,length-1)`), endpoints always kept
(`[data[0], ...subsampled, data[last]]`), selection by triangle area
`0.5*|(lastX-nextAvgX)*(y-lastY) - (lastX-x)*(nextAvgY-lastY)|` using the next bucket mean.
Our code: `PerformanceCharts.tsx:454-488` feeds the full report to `ResponsiveContainer` /
`ComposedChart` with no sampling; 3y daily is ~750 points and recomputes on range changes.
Move: adapt as a pure helper (~40 lines), apply only above a measured threshold (~1,200 visible
points), keep exact endpoints, and compute drawdown/metrics on full data before sampling.
Risk: sampling before `max_drawdown` changes the metric; label as "display sampling".

### 8. Data-quality failure reporting
`https://pandera.readthedocs.io/en/stable/lazy_validation.html` (MIT; `pandera` already at
`pyproject.toml:28`). Verified: `validate(lazy=True)` raises `SchemaErrors`;
`failure_cases` fields are `schema_context`, `column`, `check`, `check_number`,
`failure_case`, `index`; `exc.data` is the original frame.
Our code: `src/data/validation/schema.py:10-58` defines OHLC checks (including a 50% one-day
move guard named `no_unadjusted_splits`) and validates lazily, but `:62-71` reduces every
failure to `"[ticker] Schema Error: {check} failed."`, discarding column/index/value.
Move: return structured failure rows and carry them into
`selected_pool_event_population.py:325-443` / `coverage_report.json`. Risk: cap serialized
failure values; never embed whole frames.

### 9. Revision and as-of history
`https://docs.getdbt.com/docs/build/snapshots` (dbt-core Apache-2.0; docs verified). Strategies:
`timestamp` (`updated_at`) and `check` (`check_cols`); `unique_key`; `hard_deletes` is
`invalidate|ignore|new_record` in v1.9+ (replacing `invalidate_hard_deletes`); current rows have
`dbt_valid_to = NULL` unless `dbt_valid_to_current` sets a sentinel.
Our code: `fundamentals/event_store.py:17-45` carries `revision_sequence`,
`supersedes_event_id`, `reported_at`, `available_at`, `retrieved_at`, `source_hash`;
`sec_companyfacts.py:103-107` sets `available_at = filed + 1 day`. This is stronger than a
snapshot table because the supersession chain is explicit.
Move: no code; align vocabulary in docs and add tests that a restatement creates a new
`event_id` with `supersedes_event_id`, and that an `as_of` query cannot see
`available_at > as_of`. Risk: do not adopt a sentinel `dbt_valid_to_current`; our explicit
`available_at` is unambiguous.

### 10. CI path filters
`https://github.com/dorny/paths-filter/blob/v3/README.md` (MIT). Verified: picomatch globs;
`predicate-quantifier` defaults to `some`, `every` requires all patterns; `list-files` is
`none|csv|json|shell|escape`; `dot:true`; untracked files ignored for `HEAD` comparisons.
Our code: `.github/ci-policy.json` already scopes checks; `AGENTS.md` and
`docs/ci-governance.md` cap the workflow budget, so no new workflow.
Move: only if a filter becomes ambiguous, add `predicate-quantifier: every`, quote globs, and
use `list-files: json` instead of shell interpolation. Risk: `every` silently skips jobs when a
filter mixes positive and negative patterns.

### 11. Sparkline column (not built)
`https://github.com/tremorlabs/tremor/blob/main/src/components/SparkChart/SparkChart.tsx`
(Apache-2.0). Verified: one `ResponsiveContainer` per sparkline (L87-103),
`connectNulls={false}` default (L54, L149), no `aria-*` or `role`.
Move: do **not** mount 50 Recharts trees/`ResizeObserver`s in a table. Render one inline
`<svg viewBox>` per row with a null-breaking path and text labels (period, last value), capped
at ~60 sampled points. Risk: a sparkline must not imply an unmeasured window; reuse the
"unavailable" status from `PerformanceCharts.tsx:443-445`.

## P2

- **12. Sampling vocabulary:** `apache/echarts@5.5.1 src/processor/dataSample.ts` (Apache-2.0) —
  sampling only when `count > 10`; `average` skips NaN and returns NaN when none valid; `sum`
  coerces falsy to 0 (do not copy); `min`/`max` return NaN unless finite; LTTB delegates to
  `lttbDownSample`.
- **13. Null gaps:** `leeoniya/uPlot src/paths/linear.js` (MIT) — `yVal === null` sets
  `hasGap`; `findGaps` + `clipGaps` when `!spanGaps`; `decimate` when
  `idx1-idx0 >= xDim*4`, storing min/max per pixel. Use as the spec for inline sparkline paths.
- **14. Corporate-action math:** `zipline-reloaded src/zipline/data/adjustments.py`
  (Apache-2.0) — splits multiply earlier OHLC and divide volume; mergers multiply price and
  leave volume; cash dividend ratio `1 - amount/close_before_ex_date`, requires `date_ix > 0`,
  drops NaN/non-positive ratios, `effective_date` in epoch seconds. We ingest explicit events
  (`yfinance_events.py:78-103`) and apply vendor factors
  (`adjustment.py:84-166`, with OHLC relationship validation), so there is no current gap.
  Reference only if a future provider supplies raw actions without factors; never silently
  replace vendor factors with self-derived ones.
- **15. Trial dedupe:** `optuna@v3.6.1 optuna/study/study.py` (MIT) —
  `load_if_exists=True`, storage-assigned ids, `enqueue_trial(skip_if_exists=True)` comparing
  keys/types/values with `np.isclose`, WAITING-only reuse, `tell` skip-if-finished, documented
  concurrent-enqueue race. Our `colab_experiment_batch.py:145-206` (pinned index SHA, inventory,
  readback) is stronger; keep it and add a single-writer guard if workers ever multiply.
- **16. Clipboard:** `feross/clipboard-copy index.js` (MIT) — API path then span +
  `execCommand`, throws `NotAllowedError`, does not restore selection. Our readonly textarea
  (`DailyResearchBrief.tsx:19-50`) avoids the iOS keyboard and is reported via `aria-live`
  (`:98-100`). No change; no dependency.
- **17. Fingerprinting (avoid):** `huggingface/datasets@3.0.2 src/datasets/fingerprint.py`
  (Apache-2.0) hashes `dataset.__dict__` plus `getmtime` of cache files with xxh64 — no size,
  no content hash. Our `snapshot_manifest.py:44-52` + `file_checksums` avoid this.

## We are already at best practice

- **Geometric excess, guarded:** `PerformanceCharts.tsx:198-199`, `StrategyFleet.tsx:292-295`
  use `(1+r)/(1+b)-1` with `b > -1`; quantstats' `compare` is a ratio, many dashboards subtract.
- **Measured windows only:** `performancePeriods.ts:76-97` refuses interpolation;
  `PerformanceCharts.tsx:392-401` states the anchor/exclusion rule in the UI. empyrical's
  `cum_returns` zero-fills NaNs; ours does not.
- **Benchmark integrity:** `performanceBenchmarks.ts:94-102` breaks the chain on a missing day
  instead of treating it as zero; `:104-122` rejects a benchmark identical to account equity;
  `:169-172` dedupes aliases with identical normalized series.
- **Chart/table parity:** `lightweight-chart-adapter.ts:70-122` asserts bars, OHLC, volume,
  ordering and marker counts against the Recharts view — rare in OSS dashboards.
- **Point-in-time fundamentals:** `event_store.py:17-45` + `sec_companyfacts.py:103-107` keep
  `reported_at`/`available_at` separate and retain revision chains.
- **Append-only reproduction:** `append_only_store.py:15-46` tolerates only last-bit float
  noise (`1e-12`) while comparing every structural field exactly — better than byte equality
  across BLAS versions.
- **Sealed checkpoints:** `colab_experiment_batch.py:176-206` verifies an independently pinned
  SHA-256, inventory and readback before copying; `:228-262` rejects zip-slip and CRC mismatch.
- **Chart accessibility:** `recharts@3.10.1` `CartesianChart` defaults `accessibilityLayer:true`
  (`node_modules/recharts/es6/chart/CartesianChart.js:24`), so our `ComposedChart` already has
  keyboard navigation; `DailyResearchBrief.tsx:89,98` uses `aria-busy`, `role="status"`,
  `aria-live`. Do not add a second layer.
- **Honest availability:** `evidence-availability.ts:3-9` separates `not_applicable`,
  `not_computed`, `not_retained`, `blocked_by_source`, and treats a missing status as a contract
  violation rather than "0".
- **Honest copy failure:** `DailyResearchBrief.tsx:12-13` tells the operator to copy manually
  rather than claiming success.
- **Path-scoped CI:** `.github/ci-policy.json` + workflow ceiling matches good
  `paths-filter` practice without adding a workflow.

## Unverified / needs network access

- `quantopian/pyfolio` `performance_attribution.py` returned 404 on the guessed path; pyfolio is
  archived. No claim made and nothing taken from it.
- `api.github.com` content listings returned 403; all paths were verified by fetching raw files
  at pinned tags, not by tree listing.
- `recharts.org` API pages returned 404; the `accessibilityLayer` claim is from installed
  typings, not docs.
- `ghostfolio` TWR calculator on `main` is a stub throwing `Method not implemented`; no TWR
  reference was taken.
- `WebSearch` returned no usable results this session; every finding is from direct `WebFetch`.
- `quantstats` line numbers are from tag `0.0.62` as fetched. `ffn` was fetched but could not be
  line-pinned and is not cited.
