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
