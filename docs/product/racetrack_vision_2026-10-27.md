# Alpha Engine Racetrack Vision (2026-10-27)

Status: vision / RFC. Docs only. No runtime, data, registry, or workflow change is proposed by this document. `research_only=true`, `trade_ready=false` are unchanged. This document refines the 2026-10-26 investment-research-infrastructure positioning (PRD §6, PRD §7 dated 2026-10-27); it does not restore any retired path.

## 1. Target system in one paragraph

Alpha Engine is personal investment-research infrastructure whose background job is to validate models and indicators, and whose foreground job is to present the validated ones as a trading reference. Data is updated first, strategies are then constructed and run, and the frontend only reads the resulting projections. A human, not the system, makes every real trading decision.

## 2. Domain objects

- **Runner (model / strategy / indicator-as-runner).** A named, falsifiable research object with a written thesis before it races: why it was built, what market phenomenon it bets on, its selection logic, and its rebalance logic. A runner without a thesis does not enter the race, however good its curve looks.
- **Season.** One race round. A season starts when a set of runners starts together and ends when its points are settled. A season has no fixed calendar length; its length is an outcome, not a preset. A one-month period is an example, not a rule. Open: what settles a season (market-state change, pool change, runner invalidation, or an explicit review window).
- **Pool index.** The frozen US pool and the frozen CN pool, each built as a broad index. Pool size is frozen first: an addition requires a removal. Selection and removal are themselves research. The pools race against QQQ and CSI 300 respectively.
- **Track condition (index / indicator).** An environment object, not a runner. It does not race and does not score points, but it explains why runners win or lose in a given period. A track condition may be positively or negatively associated with a runner (for example, a risk factor is a headwind).
- **Benchmark.** QQQ for the US pool, CSI 300 for the CN pool, plus the pool index itself as a reference line on the same chart.

## 3. What "effective" means: a race, not a single backtest

Effectiveness is relative, multi-window, and persistent:

- Every runner is compared over recent 1 month, 3 months, 6 months, and 1 year.
- Past monthly-return rank charts are first-class evidence: they show whether a runner is consistently near the front or merely flashed once.
- Season points accumulate over a season, so a single-day spike cannot win a season; a runner that scores month after month can. This is the mechanism that favours stability over burst performance, without needing a separate stability slogan.
- A runner does not expire on a fixed date. It loses its place on the trading reference by falling in the rankings across windows and seasons. Its former record is retained, not rewritten.

## 4. Data model

Time axis $T$ is the trading calendar shared by every object. Asset axis $S$ is the frozen pool.

- Price matrix $P(t, s)$: market data.
- Holdings matrix $Q(t, s)$: strategy output. A strategy is the rule that computes $Q$ from $P$ and its own selection and rebalance logic.
- Portfolio value $V(t) = \sum_s Q(t, s) \cdot P(t, s) + \mathrm{cash}(t)$.
- Net asset value $\mathrm{NAV}(t) = V(t) / V(t_0)$, with $t_0$ a unified start date normalised to 1. Each season may also be rebased to 1 at its own start; season-end NAV is then that season's score. Season duration must be shown alongside season NAV, or longer seasons will be misread as better seasons.

Slices and reductions of the same model:

- A row $Q(t, :)$ is the holdings snapshot at $t$; a column $Q(:, s)$ is one asset's holding history; non-zero row-to-row differences are rebalance events. The ledger is therefore $Q$ itself, stored sparsely as events and expanded to a dense view only when computed.
- NAV is $Q$ and $P$ reduced over the asset axis.
- An index, as observed, is a two-dimensional time $\times$ attributes array (level, return, volatility, constituent count, turnover, and so on). Underneath, it has a constituent weight matrix $W(t, s)$ and its level is the weighted compression of price changes. A pool index and a strategy portfolio are therefore mathematically similar; they differ in their rule (pool selection/removal versus strategy selection/rebalance), not in their form.
- A market-level track condition is $I(t, k)$ (time $\times$ indicator). An asset-level indicator is $I(t, s, k)$. Both share $T$, which is why they can be aligned as subplots under a NAV chart.

Storage principle (agreed 2026-10-27): store primary quantities only, $P$ and $Q$. Weights, NAV, returns, and indicators are derived and computed, not stored as independent primaries, so derived values cannot drift from their sources. The attribute cube $X(t, s, f)$ is a logical view, not storage truth. Strictly, price also carries a knowledge-time dimension for point-in-time correctness: a research slice fixes that dimension at a publication cutoff, collapsing it back to the $T \times S$ view used above.

## 5. Frontend contract: NAV curve at the centre

The frontend is a racetrack scoreboard, not a status dashboard:

- Centre: multiple NAV curves on one chart, all normalised to 1 at a unified start date, with pool indices and benchmarks on the same chart. The curve shows compounding, drawdown from peak, and when a lead was built slowly versus suddenly.
- Below the centre: selectable track-condition subplots, or a second Y axis where an overlay is genuinely comparable. Subplots share the time axis with the NAV chart; they must not share a misleading price scale.
- Runner detail (click any curve): thesis and logic (why built, what it bets on, when it should fail), selection logic and rebalance logic stated separately, season points and monthly rank trajectory, weather profile (which conditions it thrives in, which it suffers under, positive and negative associations), current holdings, and rebalance details.
- Pool view: pool NAV versus its benchmark (US pool versus QQQ, CN pool versus CSI 300), plus the selection/removal history that produced the current pool.
- Read-only by construction: opening the frontend never starts training, replay, data fetching, or a strategy run. Those run in the background, after a data update, and publish read-only projections.

## 6. Pipeline order

1. Governed data update (frozen pool, PIT-fixed slice, source hashes).
2. Strategy construction and operation (selection and rebalance rules applied to the updated slice, producing $Q$ and its ledger).
3. Projection build (NAV curves, season points, monthly ranks, weather profiles, holdings and rebalance views) as disposable, rebuildable read-only state.
4. Frontend read of the projection only.

No step may silently substitute a security, forward-fill an unavailable statement, mix raw and adjusted prices, or relabel stale evidence as freshly published. Failed runners, blocked studies, and invalidated theses are retained as research memory.

## 7. Guards and non-goals

- No black-box unattended auto-trading. No order is sent by this system. A validated runner is a trading reference for a human decision.
- No multi-tenant SaaS, no cloud copy of private positions or credentials. Local-first.
- No new database, scheduler, registry, or evaluator introduced merely to serve the racetrack view. Reuse the existing governed slice, evaluator, and receipt mechanisms; retire a replaced path rather than wrapping it.
- No runner is promoted on a single window, a single season, or a curve alone. Curve plus points plus thesis plus weather profile are jointly required.
- Private holdings fields (shares, cost, profit and loss, accounts) stay out of research parsing, per the existing personal-lens isolation. The racetrack shows runner and pool behaviour, not a user's private account.

## 8. Open questions (not decided by this vision)

- What settles a season: an event, a pool change, a runner invalidation, or an explicit review?
- Rebalance detail scope: latest rebalance only, or full rebalance history?
- Track conditions: descriptive only (explain a past race after the fact), or also gating (a runner rests when a risk condition is adverse)?
- May different runner types use different season lengths?
- What quantitative threshold, if any, counts as "effective" beyond relative rank and persistence?

## 9. How this relates to what already exists

- The Research Study Workspace is the first runner-execution path: discover a hypothesis, freeze a spec, run the governed slice and evaluator, keep an immutable receipt, compare matched receipts. The racetrack vision gives that path a foreground: receipts become runners, comparisons become seasons, and the frontend becomes the scoreboard.
- The Strategy Console is the formal strategy-observation application. Under this vision it is reframed as one view of the racetrack (formal runners and their current observation), not as the whole product.
- The 2026-10-26 infrastructure charter and roadmap remain the background; this document adds the foreground contract and the scoring semantics they did not yet specify.

## 10. Recommended data stack (2026-10-27 follow-up, docs only)

This section records the follow-up research on which data stack fits this vision. It is a documentation addition only: no runtime, data, registry, workflow, or frontend code is changed by it, and it does not settle the open questions in §8.

**Decision.** For the current Alpha Engine — single user, local-first, daily data, about 217 symbols over about 2,500 trading days — the recommended stack, with the corrections from the second research round, is:

- **Canonical store: immutable partitioned Parquet, with Apache Arrow as the in-memory and interchange format.** A new file is written per ingest; a file is never edited in place. Every ingest carries a JSON content-hash manifest (file list, SHA-256, row counts, schema, code commit, source vintage), verified on read.
- **Semantic point-in-time (PIT): explicit `event_date` and `known_date` columns on every row.** A PIT query filters `known_date <= decision_date`. A version or snapshot is only a reproducibility pointer for a whole run; it is not, by itself, PIT.
- **Compute: Polars as the primary engine, DuckDB for SQL over Parquet and aggregation/catalog.** Polars carries expression pipelines (windows, cross-sectional ranks, NAV derivations); DuckDB carries readable SQL aggregations over partitioned Parquet without materialising it, and acts as a second-opinion engine. There is exactly one derivation authority per artefact: a derivation reads only manifest-pinned Parquet and writes only derived Parquet plus its own manifest, so every projection is rebuildable from canonical data.
- **Ledger: JSONL hash-chained events as the sparse form of Q.** Rebalance and selection events are the truth; the dense Q panel is expanded from them on demand. Each manifest records the ledger tip hash at ingest time (the anchor). A hash chain alone is tamper-evident, not tamper-proof — without the anchor, a full recompute or a tail truncation would go undetected. Ledger payloads reference dataset hashes, never private account fields, shares, cost, or profit and loss.
- **Boundaries, kept narrow.** A pandas shim exists only for plotting and statistics interop at the boundary, not as a parallel compute path. xarray is an opt-in in-memory labelled (field, time, asset) view, rebuilt from Parquet, never storage and never the derivation authority; if no step is genuinely clearer as labelled array math, it is dropped.

**Landing order: minimal stack first.** The five-piece minimal stack is (1) immutable partitioned Parquet, (2) one verified JSON manifest per ingest, (3) `event_date` + `known_date` on every row, (4) Polars alone for compute with one derivation script per artefact, and (5) the anchored JSONL ledger — plus the rebuild rule that deleting all derived artefacts and re-running derivations from canonical Parquet and manifests reproduces them. DuckDB is added when SQL aggregation or a catalog becomes convenient; DuckLake is added only later, when hand-written manifest discipline slips or multi-table snapshots are genuinely needed. Nothing else is added pre-emptively.

**Correction to the earlier recommendation: ArcticDB is demoted.** ArcticDB's `as_of` resolves to write-time versioning (version number, snapshot, or the last version written before a timestamp). It does not supply a queryable per-row `known_date`, and a backfilled vintage ingested today would carry today's `as_of`, not the vintage date. DuckLake 1.0 (April 2026) is therefore the better ready-made versioning upgrade for this stack: the data stays plain Parquet, snapshot time-travel is available in SQL, and a local SQLite or DuckDB catalog needs no server. The same commit-time limitation applies to DuckLake, Iceberg, and Delta time travel, which is why the explicit `known_date` column stays mandatory regardless of engine. ArcticDB remains an option only if per-symbol, pandas-native versioning ergonomics are specifically valued, accepting its Business Source Licence 1.1 terms and LMDB-on-Windows map-size tuning.

**Explicitly not adopted now.** pandas as the primary engine (single-threaded, and its 3.0 string and copy-on-write changes break loose research idioms); HDF5 as canonical store (in-place mutability fights the immutability and rebuildability requirement); Delta Lake or Iceberg as canonical store (multi-engine lake machinery for one user); lakeFS (requires a server); DataFusion-first (a foundation for building systems, not an end-user analysis library); Ibis or Narwhals-first (an abstraction tax with no second backend to justify it).

**Version risks, carried into any future implementation.** Pin Polars and DuckDB minor versions and re-run golden outputs on upgrade: Polars 2.0 made streaming the default and removed row-order guarantees for join, group-by, and unpivot unless order is explicitly maintained, and DuckDB 2.0 files are reported unreadable by earlier versions — another reason projections must stay rebuildable from Parquet. Test any pandas shim against pandas 3.x separately. At this scale (one price matrix is 217 x 2,500 = 542,500 cells), speed benchmarks are not the deciding criterion; PIT correctness, rebuildability, and simplicity are.

**Evidence status.** The second research round was index-sourced with no live-browser verification in that run. Still unverified: whether DuckLake 1.1 shipped as tentatively calendared, Lance's local ergonomics, and some pandas and DuckDB secondary details; no performance measurement was made on Alpha Engine's actual data. Those items are open checks, not claims, and none of them changes the stack decision above.

**Consistency with §7.** This section introduces no new database, scheduler, registry, or evaluator merely to serve the racetrack view. The minimal stack is plain files plus Polars; DuckLake is a deferred upgrade, not a new fact base, and the single-derivation-authority and private-field-isolation guards in §7 continue to apply.

## 11. Landing path and decisions fixed 2026-10-27 (docs only)

This section records the landing path agreed after the §10 data-stack discussion, plus four decisions fixed on 2026-10-27. It is a documentation addition only: no runtime, data, registry, workflow, or frontend code is changed by it. Decisions recorded here are current defaults, versioned like any other rule: changing one later means a new version, not a silent edit to history.

### 11.1 Decisions fixed 2026-10-27

- **Season length, current default: one month.** A season runs for one month and is settled at the close of the last trading day of that month. This supersedes the earlier "no fixed length" formulation as the working default; it is not a permanent lock, and any future change is a new version. The season-points mapping itself remains a versioned rule to be fixed at the start of the first season under this default, not invented retroactively.
- **Track conditions ("weather indicators") are descriptive explanatory indicators only.** A track condition is an indicator built to explain market behaviour; it is not a runner, it does not race, it does not score points, and it does not gate a runner (no "rest when conditions are adverse" rule). The term carries no special meaning beyond that: an indicator may be too weak to stand alone as a runner and still be exactly the right thing to show underneath a NAV curve to explain why runners won or lost in a period. Associations may be positive or negative (for example, a risk factor as a headwind).
- **Effectiveness: benchmark-relative, no separate absolute standard for now.** A runner is judged against its benchmark — QQQ for the US pool, CSI 300 for the CN pool. No absolute "effective" threshold is pursued at this stage, and the question is not to be over-engineered. Monthly rank charts and season points remain the tools for judging persistence (consistently near the front versus a single flash), not a second, competing effectiveness standard.
- **Corporate actions: dividend-reinvestment, total-return, as simple as possible without harming return accuracy.** Dividends are treated as reinvested, in the manner of a fund dividend-reinvestment strategy, so returns are total returns. Operationally this means the adjustment that carries reinvested dividends is part of the derived adjusted price; there is no separate per-dividend cash流水 to maintain for the research calculation, provided the reinvestment assumption is stated in the runner version. Splits and bonus shares are handled by the same adjustment-or-quantity rule as in §10, never both. Price-return figures may be published alongside as a labelled对照, but the default research return is total return.

### 11.2 Landing order

Work proceeds in this order, and each phase keeps the guards in §7 (single derivation authority per artefact, private-field isolation, research_only, no new database/scheduler/registry merely to serve a view):

1. **Minimal stack first.** Raw prices plus corporate-action events, content-hash manifests, Polars derivation, and the Q event ledger. One derivation script per artefact; deleting all derived artefacts and re-running from canonical data plus manifests reproduces them.
2. **Runner registry and race scoring.** Thesis-gated runners, monthly cross-sectional ranks, and season points settled under the §11.1 monthly default. Existing study templates migrate as thesis-bearing runners; historical one-off experiments stay as history, out of the active race path.
3. **Pool indices versus benchmarks.** Frozen US and CN pools built as broad indices, raced against QQQ and CSI 300 respectively, with the selection/removal history that produced each pool version. The pool weight rule and cost model are versioned rules fixed before the first pool index is published, not defaults chosen by accident.
4. **Daily self-maintenance.** One scheduled local script: ingest new partitions, verify manifest/schema/calendar, recompute projections, publish a new projection version. On any failure, nothing is published and the previous projection stays live; re-running the same ingest is idempotent. Pool membership changes are not part of daily maintenance — they require a new pool version.
5. **Racetrack frontend by replacement, not addition.** The NAV-centred scoreboard (§5) replaces the old observation view once stable; the two navigations do not run in parallel. DuckDB is added when SQL aggregation or a catalog becomes convenient; DuckLake only when manifest discipline slips or multi-table snapshots are genuinely needed.

### 11.3 Still open, explicitly not blocking phase 1

- Corporate-action data source: whether the current governed-slice source supplies corporate-action events or only adjusted prices, and therefore whether history can be rebuilt as raw plus events or must be accepted as versioned adjusted-price snapshots.
- Backfill scope for corporate actions across the US and CN pools: full history in one pass, or record from now onward with earlier seasons labelled accordingly.
- Edge-case defaults for corporate actions: rights issues (participate or not), spin-offs (cash distribution or new-asset treatment), mergers and delistings (termination rule).
- Tax assumption for research returns (pre-tax is the working assumption to be confirmed, not yet recorded as decided).
- Pool weight rule, per-runner cost model, and cash treatment details, to be fixed before phase 3.
- Season-points mapping detail, to be fixed at the start of the first season under the monthly default.

None of these blocks phase 1. Each is recorded here so that when its phase arrives, the decision is made once, written down as a versioned rule, and never mixed with a different rule in the same comparison.

## 12. Minimal Stack implementation specification (Phase 1 Spec)

The concrete technical specification for Phase 1 landing is published in:
[`docs/architecture/racetrack_minimal_stack_spec.md`](../architecture/racetrack_minimal_stack_spec.md).

This specification formalises the §4 data model and §11.2 landing order into four machine-checkable contracts:

1. **Market Price Matrix $P(t, s)$ Contract**:
   - **Time Axis $T$**: Linked to official `exchange_calendars` (`XNYS` for US, `XSHG` for CN), enforcing continuous session integrity and fail-closed handling for holidays/weekends.
   - **Asset Axis $S$**: Strictly bound to candidate pool `configs/research_universes/us_selected_equities_v2.yaml` (87 symbols) plus benchmark reference `QQQ` from `configs/pools/reference_instrument_registry_v1.yaml` (total 88 assets).
   - **Price Source & Return Model**: Extracted from `data/research/market_evidence/us/symbols/{symbol}.json`, specified as dividend-reinvested adjusted total-return price (reproducing §11.1 corporate action decision). Missing/unlisted bars are represented as `NaN` without silent forward-fill.
   - **Manifest & Cryptographic Identity**: Packaged as immutable partitioned Parquet with an accompanying `manifest.json` carrying `matrix_sha256` and individual security evidence source hashes.

2. **Holdings Event Ledger $Q(t, s)$ Contract**:
   - **Sparse JSONL Event Stream**: Stored at `data/racetrack/ledgers/{runner_id}_v{version}.jsonl`, recording only deliberate rebalances.
   - **Schema Contract**: Every event specifies `event_id`, `parent_hash`, `timestamp_utc`, `effective_session`, `runner_id`, `runner_version`, `target_weights` ($\sum w_i \le 1.0$), `cash_weight` ($1.0 - \sum w_i$), `reason`, and `event_hash`.
   - **Tamper-Evident Hash Chain**: Genesis event begins with `parent_hash = "0" * 64`; subsequent events bind the SHA-256 hash of the canonical JSON of their predecessor, with the ledger tip hash anchored in the runner's manifest.
   - **Strict Personal Lens Privacy Isolation**: Enforces fail-closed blocking if any live account field (`shares`, `total_cost`, `broker`, `account_id`, `cash_balance`, `executed_price`, `realized_pnl`) appears in the research ledger.

3. **Asset Value & Unified NAV Conversion Engine (V & NAV Engine)**:
   - **Normalised Origin**: $V(t_0) = 1.0, \mathrm{NAV}(t_0) = 1.0$.
   - **Daily Weight Drift**: $w_{i, t}^{drift} = \frac{w_{i, t-1}(1 + r_{i, t})}{1 + r_{gross, t}}$, tracking natural market drift between rebalances.
   - **One-Sided Turnover**: $\mathrm{Turnover}_t = \frac{1}{2} \sum_{i \in S \cup \{\mathrm{cash}\}} |w_{i, t}^{target} - w_{i, t}^{drift}|$, conserving turnover across rebalances.
   - **Transaction Friction**: $\mathrm{Friction}_t = \mathrm{Turnover}_t \times \mathrm{friction\_rate}$ (baseline 8 bps, with 0 bps and 15 bps sensitivity analyses).
   - **Continuous Compounded NAV**: $r_{net, t} = r_{gross, t} - \mathrm{Friction}_t$, $\mathrm{NAV}(t) = \mathrm{NAV}(t-1) \cdot (1 + r_{net, t})$.
   - **Key Metrics**: Evaluated over rolling windows for continuous Maximum Drawdown ($\mathrm{MDD}$), Annualized Excess Return over QQQ ($\mathrm{CAGR}_{runner} - \mathrm{CAGR}_{QQQ}$), and Annualized Sharpe Ratio.

4. **Internal Primary Benchmark: US 87 Equal-Weighted Pool Index**:
   - **Role**: Serves as the racetrack's internal primary benchmark line to isolate selection alpha from pool beta.
   - **Rule**: Rebalanced to equal weights ($w_i = 1/87 \approx 0.01149425, w_{cash} = 0.0$) on the first trading session of each calendar month, with natural drift throughout the rest of the month ($\mathrm{Turnover} = 0$).
   - **Uniform Evaluation**: Converted into continuous NAV through the exact same V & NAV Engine with identical 8 bps friction on rebalance days.

## 13. Frontend work design (2026-10-28, docs only)

This section turns the trading-frontend research into engineering requirements for Alpha Engine's own dashboard. It is a documentation addition only: no runtime, data, registry, workflow, or frontend code is changed by it. It refines the §5 frontend contract and the §11.2 landing order, and it is written against the §12 Phase 1 contracts — where this section and §12 appear to differ, §12 governs the data and calculation, and this section governs only how the resulting projection is displayed.

### 13.1 Decisions fixed 2026-10-27

- **Desktop-first.** Layout, density, and interaction are designed for a desktop browser. Wide tables scroll horizontally rather than collapsing into a mobile layout; no mobile layout is built first.
- **Main view shows the window Top 10.** For the selected window (1M / 3M / 6M / 1Y), the scoreboard chart shows the pool index, the benchmark(s), and the top 10 runners for that window — 12 series in the US case including the internal benchmark below. Other runners are reached through the leaderboard and runner detail, not by drawing every runner at once.
- **Modify the existing dashboard directly.** The scoreboard is a new view inside the existing dashboard shell, reusing its routing and theme system where possible. No separate new application is built, and no long-term parallel navigation is created: once the scoreboard is stable it replaces the old observation view, per §11.2 step 5.
- **Read-only, always.** No trading execution, no order controls, no live ticking, no runner editing in the frontend. Runner creation and execution remain in the background Study Workspace path.

### 13.2 Views

- **Scoreboard (main view).** Header: market toggle (US / CN), season-month selector, window switcher (1M / 3M / 6M / 1Y), projection version, data-as-of date, and data-vintage badge. Centre: one chart instance with a NAV pane plus dynamic indicator panes. Below: leaderboard table (season points, monthly-rank trajectory, window return, maximum drawdown, annualised excess return, Sharpe — only where the projection ships them) and a season strip of settled months; clicking a settled month pins the window to that month.
- **Runner detail (lazy-loaded route).** Order is fixed: thesis first (why built, what phenomenon it bets on, when it counts as failed), then selection logic and rebalance logic stated separately, then current holdings, rebalance history, monthly-rank trajectory, and indicator-association profile (association sign, window, and sample count — never a bare correlation coefficient). No detail view may infer a thesis or a logic statement that the projection does not carry.
- **Pool-versus-benchmark view.** The same chart component with a series filter (pool index plus benchmark only) and a spread/drawdown pane. It is a filter on the scoreboard chart, not a second chart implementation.

### 13.3 Charting stack decision

- **Adopt: TradingView Lightweight Charts v5 (canvas, Apache-2.0 plus attribution).** It is financial-native, canvas-fast, small, actively maintained, and natively multi-pane with a shared time scale — the NAV pane plus indicator panes below it, with one crosshair spanning panes, without synchronisation glue. The attribution requirement is mandatory: keep `attributionLogo` enabled or an equivalent prominent TradingView link on user-facing pages; do not silently disable it.
- **Fallback only: Apache ECharts (canvas, Apache-2.0).** Adopt ECharts instead only if the existing dashboard already uses it, or if its wider chart catalogue is genuinely needed. Its multi-grid plus linked axis-pointer pattern achieves the same layout with more configuration. Never run ECharts alongside Lightweight Charts.
- **Reserve: uPlot (MIT) and D3 (ISC).** uPlot is a reserve engine only if Lightweight Charts ever proves too heavy at this scale (12 series; it will not on the evidence in §13.6) — it is a toolkit with no built-in financial chrome, parsing, or aggregation, so adopting it means building panes, markers, and legend behaviour by hand. D3 is a supplement for bespoke visuals only (rank trajectory, drawdown shading, season strip), never the main NAV chart engine.
- **Do not adopt:** Highcharts (not free for commercial/internal-company use; its pricing and commercial-use boundary are unverified and must be checked on highcharts.com before any reconsideration), trading-vue-js (explicitly unmaintained, Vue 2 only), react-stockcharts / react-financial-charts (unmaintained original, fragmented breaking fork). KLineChart (Apache-2.0) is a credible reserve if built-in indicator panes are wanted, subject to verifying its Pro/core boundary first.
- **One charting stack, enforced.** Only the chart component (and the small bespoke D3 visuals, if any) may import a charting library. Any other component receives data and never draws. A second charting import in a change is treated as the over-engineering signal.

### 13.4 Data contract and frontend architecture

- **Three layers, no shortcuts.** (1) `ProjectionClient`: fetches the projection manifest and chunks, validates version and hash, caches by version, and exposes typed accessors (`getSeries(id, window)`, `getLeaderboard(window)`, `getRunnerDetail(id)`). It knows about files, versions, and caching, and nothing about pixels. (2) `ScoreboardStore`: UI state only — window, season, selection, hover date, visible series, theme. It never computes a return, rank, point, drawdown, or indicator value. (3) `Presentation`: chart wrapper, table, and detail components that transform projection data for display only.
- **Projection file is the single calculation authority.** The frontend receives versioned, static, columnar projection data (shared date index plus one array per series, with a manifest carrying version, generation timestamp, data-as-of date, and file hashes) and never recomputes NAV, returns, ranks, season points, drawdowns, Sharpe, or indicator values. That includes the §12 engine outputs: the frontend displays the §12 V & NAV engine's NAV series, maximum drawdown, annualised excess return over QQQ, and Sharpe exactly as shipped, including the friction baseline label (baseline 8 bps; 0 bps and 15 bps are labelled sensitivity views, never averaged or mixed with the baseline in one series).
- **Display-only transforms, explicitly allowed:** slicing to the selected window, rebasing a curve to 1 at the window start (`display = nav / nav[windowStart]`), converting NAV to percentage change since window start, formatting numbers, and pixel decimation for rendering (collapsing points that map to the same pixel with min/max aggregation). **Forbidden in the frontend:** computing NAV from prices, returns from NAVs other than the labelled display percentage above, ranks, season points, drawdowns for judgement, or indicator values. If a value is missing from the projection, fix the projection generator; do not patch it in the frontend.
- **Version handling.** Every view shows projection version, data-as-of (month-end close) date, and generation timestamp. Switching versions reloads all chunks; a leaderboard from one version is never mixed with series from another. Settled seasons are pinned to the version that settled them, so a settled month's points never move when a new projection is published. Cache key is the projection version or content hash; versioned files are immutable, and only the manifest itself is short-lived.
- **Loading shape.** Eager-load only what the scoreboard needs: date index, pool and benchmark series, Top 10 series for the current window, and leaderboard rows. Runner detail (full history, holdings, rebalance history, rank trajectory, association profile) loads on click as a separate chunk. Do not load all runners' full histories on first paint. Virtualise the leaderboard only if rows exceed roughly 1,000 or gain per-row sparklines; below that, a plain table with stable keys is faster and easier to make accessible. Table sparklines, if any, use the same charting library's smallest instance or plain SVG paths from the same series data, capped to visible rows.
- **Shared time state and linkage.** One time state drives the main pane, indicator panes, and leaderboard highlight: `{ window, visibleRange, hoverDate, selectedRunnerId, visibleSeriesIds }`. Curve click, legend click, and leaderboard-row click all dispatch the same selection; hover on any of them highlights the others. Hover state must not re-render table rows: highlight via class or attribute on the already-rendered row, or a separate highlight layer, throttled to animation frames. Zooming the main pane sets the shared visible range; subplots follow because they share the time scale. No subplot may carry an independent zoom. Window and runner selection are reflected in URL parameters for deep-linking and back/forward restoration.
- **Scale arithmetic (why no streaming or WebGL stack is needed).** The full universe is 217 symbols × ~2,500 trading days ≈ 542,500 daily values, which fits a few megabytes only as columnar arrays with a shared date index — never as one JSON object per point. Rendered at any moment: pool plus benchmark(s) plus Top 10 = 12 series; a 1Y window is about 252 points per series (≈3,000 points), full history is 12 × 2,500 = 30,000 points. That is trivial for any canvas library; the bottleneck is parsing, rebasing, and DOM re-rendering on window change, not drawing. DuckDB-WASM or Parquet-in-browser is therefore deferred: consider it only if the projection file grows past roughly 20–50 MB or if arbitrary-window, arbitrary-runner slicing becomes a requirement. No WebSocket, tick handler, or streaming downsampler is built for a static versioned file.

### 13.5 Time axis, scales, colour, and accessibility

- **Trading-day index axis, with the omission footnoted.** Feed the chart the projection's trading-day index (official exchange calendars per §12: XNYS for US, XSHG for CN), label ticks with real dates, and footnote on the chart that weekends and holidays are omitted and the x-axis is trading days, not calendar days. A calendar time axis would spend roughly a quarter of a 1Y chart's width on empty weekends and stretch holiday gaps; a calendar axis on one pane and an index axis on another would misalign the shared crosshair, so the index axis is used on every pane.
- **One scale for NAV curves, separate panes for indicators.** All NAV curves are normalised to the same unit (multiple of 1 at window start) and share one axis, which is stated on the axis itself ("1.00 = window start"). No second price axis is ever overlaid on the NAV pane. An indicator with a different unit gets its own pane with its own scale, never a second axis over the NAV pane.
- **Benchmarks pinned and visually dominant.** Pool index and benchmark lines are non-toggleable and drawn underneath the Top 10 lines. In the US view there are two benchmark lines to distinguish: the external benchmark (QQQ) and the §12 internal primary benchmark (US 87 equal-weighted pool index, rebalanced to equal weights on the first trading session of each month, cash weight 0, evaluated through the same V & NAV engine with identical friction) — the internal line exists to isolate selection alpha from pool beta, and the two lines must be labelled as such, never merged. In the CN view, only the external benchmark (CSI 300) is shown until a CN pool-index rule is defined; no CN internal benchmark is invented here.
- **Colour and direction.** NAV lines use a categorical palette (for example Okabe-Ito) with pool and benchmark in reserved, dominant styles (thick line for pool, dashed line for benchmark) so they stay findable in a 12-line tangle; line width, dash, and legend order do more work than hue. Up/down is never encoded by colour alone: direction always carries ▲/▼, a +/− sign, and the numeric percentage, and a colourblind mode (blue/orange instead of red/green) is provided. Muted, similar-brightness colours are used on dark backgrounds.
- **Accessibility.** The leaderboard table is the accessible equivalent of the chart: full keyboard navigation, sortable headers with `aria-sort`, and each row as a link or button to runner detail. Legend toggles are real buttons. Hover values are also shown in a persistent hover-readout row (date, pool, benchmark, hovered runner) so a keyboard user can read values without a mouse. Text contrast meets at least 4.5:1. Desktop density is compact (small table text, compact row height, sticky header, frozen runner-name column on horizontal scroll) with a compact/Zen toggle for screenshots.

### 13.6 Trading-specific display rules (what a generic dashboard does not do)

- **Benchmark always visible, normalised comparison with the base stated.** Every curve starts at 1.00 at the window start, and the chart states the base on the axis. Window changes rebase all curves to the new window start, and the window return is shown in the legend so the eye does not have to estimate it. Normalisation hides volatility scale and absolute size, which is why drawdown and window return are shown separately.
- **Drawdown as a default-on subplot.** The §12 maximum-drawdown series is offered as a default-on indicator subplot, because a NAV that ends higher after a deep trough is a different runner from one that rose steadily.
- **Event markers on the time axis.** Rebalances, pool entries and exits, suspensions, and corporate actions are markers on the chart and rows in the rebalance-history table, with the same dates. Month-end settlement points for the monthly season are annotated explicitly.
- **Missing and suspended data as gaps with reasons, never silent interpolation.** Per §12, missing or unlisted bars are `NaN` without silent forward-fill. The frontend renders a gap in the line, the leaderboard cell says "suspended" (not 0, not carried forward), and the detail view states the suspension dates. If the projection forward-fills for a calculation reason, the frontend still renders the gap and footnotes it.
- **Data vintage and limitations on the page, not in a README.** Every view carries: projection version, data-as-of (month-end close) date, generation timestamp, universe size, window definition, friction baseline label, and a limitations line (read-only display of precomputed projections; not live prices; past NAV does not predict future NAV; season points are settled at month-end close and do not change when a new projection is published). The current PIT status is shown honestly: until PIT certification exists, the page states that source availability does not yet constitute full PIT certification.
- **Settled versus provisional states.** A month in progress is visually distinct (marked provisional, or simply not yet in the season table) from a settled month. Once settled, its points never move.
- **Privacy fail-closed in the frontend payload.** If any live account field from §12's personal-lens list (`shares`, `total_cost`, `broker`, `account_id`, `cash_balance`, `executed_price`, `realized_pnl`) appears in a projection payload, the frontend treats the payload as invalid and does not render it. Research artefacts display runner and pool behaviour only, never a user's private account.

### 13.7 Work order (tailored to modifying the existing dashboard)

1. Confirm the existing dashboard's framework and current charting library, if any — this is the pre-implementation check in §13.8, and it decides between the Lightweight Charts adoption and the ECharts fallback in §13.3.
2. Define the projection manifest and chunk schema and build `ProjectionClient` (versioned, cached, hash-validated).
3. Build display-only rebase and slice helpers, unit-tested against projection fixtures.
4. Build the chart component with pool plus benchmark(s) plus Top 10 plus one indicator pane.
5. Wire leaderboard linkage both ways (hover and click, curve ↔ row ↔ detail).
6. Build runner detail as a lazy-loaded route.
7. Build the pool-versus-benchmark view as a series filter on the same chart component, plus a spread/drawdown pane.
8. Add the season strip, vintage footer, and accessibility pass (table as chart equivalent, keyboard legend toggles, hover-readout row).

### 13.8 Non-goals and still open before implementation

- **Non-goals:** trading execution; live ticking, WebSockets, or polling; a second charting stack; client-side recomputation of any judged number; arbitrary date pickers, custom ranges, or intraday granularity before the four fixed windows and the monthly season are solid; dual axes on the NAV pane; truncated axes; interpolated gaps; silent forward-fills; copying GPL-3.0 or AGPL-3.0 dashboard code (FreqUI, Ghostfolio) without a licence check.
- **Open before implementation:** (a) the existing dashboard's framework and current charting library are unknown from the research — confirm them before step 1, or the §13.3 choice cannot be finalised; (b) no CN internal benchmark rule is defined in §12, so the CN scoreboard shows CSI 300 only until one is defined; (c) the season-points mapping detail is still to be fixed at the start of the first season under the §11.1 monthly default; (d) vendor performance and bundle claims in the research (frame rates, bundle sizes) were not reproduced and are not needed at 12-series scale; (e) Highcharts pricing and commercial-use boundary remain unverified, which is moot unless Highcharts is reconsidered.
