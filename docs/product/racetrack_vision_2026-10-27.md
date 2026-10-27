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
