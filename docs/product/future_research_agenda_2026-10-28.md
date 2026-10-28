# Future research agenda — what #1305, #1306, and #1307 do not yet cover

Status: agenda / RFC. Docs only. No runtime, data, registry, workflow, or frontend code is changed by this document. `research_only=true`, `trade_ready=false` are unchanged. Nothing in this document is a decision, a commitment, or a roadmap promise: each item is an open research direction with a reason it matters, a question to answer, and a test for what would close it. An item is closed only by a dated decision or by a separate, evidenced implementation PR — never by being listed here.

## 0. How to read this agenda, and what is already covered

This agenda separates proposed design, implementation awaiting acceptance, and verified delivery. As of 2026-10-28 the current authorities remain [AGENTS.md](../../AGENTS.md) and the [Strategy Console contract](strategy_console.md). An open PR's design choices do not supersede those authorities or authorize a new product surface.

| Proposal baseline | What exists | What is not delivered or accepted |
| --- | --- | --- |
| #1305 at `52be20e4f61a60445be36f6c714afeaaa807b4fd` | Docs TODO using existing Brief and verified evidence readers | Top-three Brief and Evidence Review implementation; runtime acceptance |
| #1306 at `3e014f4351b15d51d71a842c8dd9d2a96ef8c542` | Proposed P/Q/NAV backend, runner/scoring, US/CN benchmarks and publication CLI; frontend design | Integrity/CI closure, certified historical PIT and scoreboard frontend; design choices such as Lightweight Charts are not installed capabilities |
| #1307 at `d861dd9cd8f16e58f83635736d2305200abff151` (draft) | Bottom Detection & Capture research specification and source-audit notes | Feature/state-machine implementation, independent OOS results and shadow validation |

These are dated inspection baselines, not the current PR heads. Subsequent fixes require their own evidence. This agenda can be reviewed independently: it does not wait for all three PRs, nor make all its questions prerequisites for their bounded delivery.

The gaps below fall into three kinds, and the kind matters for how each item should be worked: **(a) product-experience gaps** — the user can see a number but cannot complete a decision with it; **(b) trust gaps** — a number is shown but its provenance, vintage, or limits are not yet strong enough to act on; **(c) evaluation gaps** — a result looks good but has not yet survived the test that would falsify it.

## A. Product experience: from seeing a scoreboard to completing a decision

### A1. Information architecture: Daily Brief (top 3) versus Scoreboard (Top 10)

**Why it matters.** #1305 gives the user a brief of at most three meaningful items; #1306 gives a scoreboard of the window Top 10. Two different "top" lists, on two different surfaces, will eventually disagree — different windows, different ranking rules, different staleness — and the user will not know which one to trust. This is the single most likely source of confusion in the combined product.

**Research questions.** When is the brief the right entry point and when is the scoreboard? Do brief items link into scoreboard rows and runner detail with one click, and does the brief state the window, season, and projection version its three items came from? If a runner is in the brief but not in the Top 10 (or vice versa), is that difference explained on the page or hidden?

**What would close it.** A one-page information-architecture note: entry points, linking rules, and a rule that a brief item and a scoreboard row never show the same runner with different ranks, returns, or points for the same window and version. If they must differ, the reason is displayed.

**What it must not become.** A third surface, a unified "super dashboard", or a ranking that merges brief judgement and scoreboard points into one opaque score.

### A2. Decision Journal (private) — the missing half of "human decides"

**Why it matters.** The whole racetrack is built on "background validates, foreground references, human decides" — but today there is nowhere for the human decision itself to live. A runner can be validated and displayed, yet the decision it informed, the reason, and the later outcome are not recorded anywhere, so the system cannot learn whether its references actually helped the user become a better trader. That is the product's stated first goal.

**Research questions.** What is the smallest decision record that is still useful: date, runner(s) referenced, thesis version, what was decided, what would prove it wrong, and a later review date? How is it kept strictly private and separate from research artefacts, so no account field, position size, or execution price ever enters a projection, ledger, or manifest (the personal-lens boundary in #1306 §12)? Is the journal a local file, a dashboard view, or a note template — and does it need any backend at all?

**What would close it.** A design note with the record schema, the privacy boundary stated as a fail-closed rule (the same field list as #1306 §12), and a review ritual: how often past decisions are revisited against settled seasons, and what counts as "this reference helped" versus "this reference misled".

**What it must not become.** A trading log that reconstructs positions, a recommendation engine, or an auto-trading trigger. Recording a decision is not executing one.

### A3. Runner thesis authoring and lifecycle

**Why it matters.** #1306 states the thesis gate — no thesis, no race — but not how a thesis is written, reviewed, versioned, or retired. Without an authoring workflow, the gate will either be bypassed with one-line theses or become a bottleneck that stops new runners entering.

**Research questions.** What is the minimal thesis template that still falsifies: phenomenon bet, selection logic, rebalance logic, failure conditions, and cost model? Who reviews a thesis, and what changes require a new runner version versus a correction? What retires a runner — sustained rank decline, thesis invalidation, pool exit, or an explicit review — and is its history retained read-only after retirement?

**What would close it.** A thesis template plus a lifecycle state machine (candidate → racing → rested → retired), with versioning rules that match the Q ledger's versioning, and a migration note for the existing experiment corpus (see B5).

### A4. Season review ritual (monthly) and pool review ritual

**Why it matters.** A season is now defined (one month, settled at month-end close), but a settlement is not a review. Without a ritual, settled points accumulate and nobody asks what they mean, and pool selection/removal — declared to be research in itself — happens ad hoc.

**Research questions.** What does a month-end review actually check: points audit (do stored points match recomputation from the pinned projection version?), weather explanation (which indicators explain this month's winners and losers?), thesis invalidation (did any runner fail its stated failure condition?), and pool-change proposals (with reasons, not just a new list)? How often is the pool itself reviewed — monthly with the season, or on a slower cadence — and what evidence is required to propose an addition-with-removal?

**What would close it.** A one-page review checklist for each ritual, with inputs (pinned projection version, season points, weather profiles, rebalance history) and outputs (a dated review note, a list of invalidated theses, pool-change proposals or an explicit "no change" decision). The checklist is a document first; automation comes only after the checklist has been used by hand.

### A5. Combined-market view: is there one, and what would it honestly show?

**Why it matters.** Research is per market (US pool versus QQQ, CN pool versus CSI 300), but the user's own risk framework is combined (Nasdaq plus A-shares, drawdown from a combined peak). A per-market scoreboard alone leaves the combined question unanswered; a naive combined scoreboard would mix benchmarks, currencies, and calendars and produce a number that means nothing.

**Research questions.** Is a combined research view wanted at all, or is the combined view strictly a private-account view that must stay outside research artefacts? If a combined research view is wanted, what is it combined over — normalised NAVs, ranks, or points — and what does it hide (currency, market beta, calendar differences)?

**What would close it.** An explicit decision: either "no combined research view; combined risk stays in the private account view" with reasons, or a combined-view definition with its normalisation, currency, and calendar rules stated and its limits footnoted on the page.

## B. Data and trust: what still cannot be fully verified

### B1. PIT certification path: from `pit_certified=false` to certified

**Why it matters.** The governed slice today is cutoff-only PIT and explicitly uncertified: source availability is not certification. Until a certification path exists, every rank, NAV, and season point carries a caveat that limits how much weight it can bear — and the frontend (§13.6) must keep displaying that caveat honestly.

**Research questions.** What evidence would constitute certification: vendor vintage files with announcement dates, a test that replays a historical decision date using only data known then and compares it against the stored slice, a catalogue of known revision events and how each was handled? Which data sources can supply announcement dates at all, and which cannot? What is the smallest certified subset (for example, one market, one pool, one window) that could be certified first, rather than certifying everything at once?

**What would close it.** A certification checklist with pass/fail tests, a per-source verdict (certifiable / partially certifiable / not certifiable with reasons), and a rule for what the frontend displays for certified versus uncertified slices. Certification is never claimed by removing the caveat; it is earned by passing the tests.

### B2. Corporate-action source and backfill

**Why it matters.** #1306 §11 fixed the corporate-action rule (dividend-reinvestment total return, as simple as possible without harming accuracy), and §12 specifies dividend-reinvested adjusted total-return prices — but the source question was left open: does the current governed-slice source supply corporate-action events, or only adjusted prices? If only adjusted prices, history cannot be rebuilt as raw prices plus events, and the fallback is versioned adjusted-price snapshots. That choice changes what "raw" means in the whole stack.

**Research questions.** What does the current source actually supply, field by field? If events are missing, which event source (exchange announcements, vendor factor files) covers US and CN, at what cost and latency, and with what announcement-date quality? Is backfill across the US and CN pools a one-pass project, or is recording from now onward with earlier seasons labelled accordingly the honest scope?

**What would close it.** A source verdict per market, a backfill scope decision (full history versus from-now-onward, with labelling consequences), and edge-case defaults recorded as versioned rules: rights issues (participate or not), spin-offs (cash distribution or new-asset treatment), mergers and delistings (termination rule), and the tax assumption for research returns (pre-tax is the working assumption to be confirmed, not yet recorded as decided).

### B3. CN pool index and internal benchmark

**Why it matters.** §12 defines the US internal primary benchmark precisely (US 87 equal-weighted, rebalanced on the first trading session of each month, cash weight 0, same engine and friction). PR #1306 proposes a CN130 equal-weight implementation alongside CSI 300. Code presence does not settle whether its eligibility, suspension, cash and cost rules have been accepted; there is no delivered scoreboard UI to infer acceptance from.

**Research questions.** What is the CN pool's weight rule, rebalance cadence, and cash treatment, and why? Is it equal-weighted like the US internal benchmark, or does the CN market's structure (suspensions, price limits, turnover) argue for a different rule? What is the CN pool's constituent universe and version, and how do suspensions and price-limit days enter the index calculation?

**What would close it.** A CN pool-index rule written with the same precision as the US rule in §12, plus a frontend note (already in §13.5) that no CN internal benchmark is shown until that rule exists.

### B4. Pool weight rule, cost model, and cash treatment (general)

**Why it matters.** §12 fixes the US internal benchmark's weight and friction, but the general pool-index weight rule, per-runner cost model, and cash treatment are still versioned rules to be fixed before the first pool index is published (see §11.3). These are not details: a different weight rule or cost model changes every NAV, rank, and point the scoreboard shows.

**Research questions.** Is the pool index equal-weighted, capitalisation-weighted, or something else, and what does each choice imply for turnover and concentration? Is the 8 bps baseline friction the right default for both markets, or does CN need its own? Is cash an explicit weight with its own return series, or a residual plug — and what return does cash earn in the calculation?

**What would close it.** One versioned rule per item, fixed before the first pool index publication, with sensitivity views (0 bps / 15 bps for friction, as in §12) labelled as sensitivities, never averaged into the baseline.

### B5. Triage of the existing experiment corpus (about 244 entries)

**Why it matters.** `src/research/` holds roughly 244 entries, many of them one-off historical experiments. The racetrack cannot race 244 runners, and it cannot honestly pretend they do not exist. Without triage, the runner registry will either inherit the whole corpus as noise or lose research memory by deleting it.

**Research questions.** What are the triage criteria: thesis present, spec frozen, receipt retained, matched comparison possible, code still runnable? Which entries migrate as thesis-bearing runners, which stay as history out of the active race path, and which are archived with a reason? Who decides, and is the decision itself recorded?

**What would close it.** A triage table (entry → runner / history / archived, with reason), produced once, reviewed, and then frozen — new runners after that point enter only through the A3 authoring workflow.

### B6. Track-condition (weather) indicator library: which indicators, and how associations are judged

**Why it matters.** Track conditions are now defined as descriptive-only explanatory indicators (§11.1), which settles what they are not (not runners, not gates) but not which indicators belong in the library, where they come from, or how an association is judged strong enough to display. Without that, the subplot shelf will fill with whatever indicator was easiest to fetch, and weak associations will be read as explanations.

**Research questions.** What is the initial catalogue: market breadth, volatility, rates, credit, sector rotation, sentiment — and for each, what is the source, the lag, the window, and the sample-count threshold below which no association is shown? How are associations computed (correlation with indicator changes, beta, conditional means in indicator terciles — all already in the research design) and, critically, how is multiple testing handled when many indicators are tried against many runners? When is an indicator retired from the library?

**What would close it.** A catalogue table (indicator, source, lag, window, minimum sample count, display rule) plus a multiple-testing note: associations are descriptive, always shown with window and sample count, and never promoted to a causal claim or a gating rule without a separate, dated decision.

## C. Evaluation science: surviving the test that would falsify a result

### C1. General out-of-sample and multiple-testing discipline (beyond #1307)

**Why it matters.** #1307 sets the standard for one family (causal signals, untouched out-of-sample, shadow release). The same standard has not yet been generalised: what stops the next family from being selected because it looked good in-sample, or from being one of fifty tried indicators whose best result is reported alone?

**Research questions.** What is the shared OOS protocol: fixed walk-forward folds with purged margins (as in the existing walk-forward engine), a held-out period that no selection decision may touch, and a shadow period before any read-only launch? How are multiple comparisons counted and reported — number of models, indicators, windows, and parameter sets tried, not just the winner? What is the baseline each family must beat (benchmark, equal-weighted pool, and a naive rule), and is the baseline fixed before results are seen?

**What would close it.** A short evaluation protocol document, applied to every new family, with a reporting template (tried / selected / OOS result / shadow result / baseline) that makes cherry-picking visible by construction.

### C2. Metric discipline: what is judged, and what is not shopped

**Why it matters.** NAV, window return, season points, monthly ranks, drawdown, Sharpe, and annualised excess return are all available — which is an invitation to pick whichever metric flatters a runner. §11.1 already fixes benchmark-relative effectiveness as the standard, but the metric set around it is not yet governed.

**Research questions.** Which metrics are primary (benchmark-relative return and season points), which are diagnostic (drawdown, Sharpe, turnover, association profile), and which are never used alone to promote a runner? How are metrics reported together so that a high return with a deep drawdown cannot be presented without the drawdown? What happens when metrics disagree — is there a tie-break rule, or is disagreement itself the signal to rest a runner?

**What would close it.** A metric hierarchy note, enforced in the frontend by always showing primary and diagnostic metrics together in runner detail, never a single headline number alone.

### C3. Regime robustness and sensitivity beyond friction

**Why it matters.** Friction sensitivity (0 / 8 / 15 bps) is specified in §12, but a runner that works only in one regime, one volatility environment, or one pool composition has not been tested — it has been fitted. The weather indicators in B6 are the raw material for this test, but the test itself is not yet defined.

**Research questions.** How is a runner's performance broken down by regime (using the descriptive track conditions, with windows and sample counts stated)? What sensitivity analyses are standard: friction, rebalance cadence, pool composition (leave-one-sector-out), and cost-model variants? At what point does regime dependence rest a runner rather than merely qualify it?

**What would close it.** A regime-and-sensitivity report template, produced for each racing runner at season review (A4), with rest-versus-qualify criteria stated in advance, not chosen after seeing the breakdown.

### C4. The five research directions: scope or examples, and in what order

**Why it matters.** The five directions from the earlier positioning (cross-sectional, RDI, timing, fundamentals, position/risk) are still undecided as first scope versus illustrative examples (§6, §11.3). Without a prioritisation, new work defaults to whatever is most interesting this week, and the infrastructure is judged by a scattered set of one-off studies instead of a coherent programme.

**Research questions.** Are the five the first batch to cover, or examples of a wider set — and if wider, what is the rule for adding a sixth? In what order are they pursued, and what is the falsification test for each direction as a whole (not just for one model inside it)? How does #1307's bottom-detection family relate to these five — is it inside one of them, or a sixth direction in its own right?

**What would close it.** A one-paragraph positioning decision per direction (in scope now / example only / deferred, with reason) plus an ordering, recorded as a dated decision. Until then, new families are accepted only with an explicit statement of which direction they belong to, or why they create a new one.

## D. Operations: keeping a local-first system honest over time

### D1. Daily self-maintenance: monitoring, alerting, and failure handling

**Why it matters.** §11.2 step 4 defines the daily script (ingest, verify, recompute, publish; on failure, publish nothing and keep the previous projection live). What it does not define is how a failure is noticed, how long a stale projection may stay live before it is itself a problem, and how a missed day is recovered without rewriting history.

**Research questions.** What is the daily exception report (failed ingest, schema drift, calendar mismatch, missing symbols, manifest verification failure) and where does it go? What is the staleness rule: after how many missed days is the scoreboard marked stale, and does a stale scoreboard still show settled seasons? How is a backfilled day inserted — as a new vintage, never as an edit to the missed day's file?

**What would close it.** An operations note: exception-report format, staleness thresholds and display rules, and a recovery procedure that preserves the append-only, versioned invariants.

### D2. Backup, restore, and dependency upgrades

**Why it matters.** A local-first system has no cloud to fall back on. The canonical Parquet files, manifests, ledgers, and projection versions are the system; losing them, or upgrading a dependency that silently changes a result, is a data-loss or a correctness event, not an inconvenience.

**Research questions.** What is backed up, where, and how often — and has a restore from backup ever been tested by actually rebuilding all projections from canonical data plus manifests? What is the upgrade policy for pinned dependencies (Polars, DuckDB, Lightweight Charts): how are golden outputs re-run on upgrade, and who approves a major-version move (Polars 2.0 row-order semantics and DuckDB 2.0 file-format changes are the concrete warnings here)?

**What would close it.** A backup-and-restore test record (date, scope, rebuild result) and an upgrade checklist (pin, golden-output rerun, approval) that is followed before any major-version upgrade, not after a surprising result.

### D3. Frontend integration: existing dashboard framework and Lightweight Charts

**Why it matters.** The existing dashboard package.json records React 19, Vite, react-router-dom and Recharts. Lightweight Charts v5 is a design proposal in #1306, not an installed dependency. Remaining integration risks concern attribution, component lifecycle, pane/series behaviour and the effect of replacing maintained charts.

**Research questions.** Given the existing React/Vite/router stack, how does the proposed chart library integrate with the theme and existing chart consumers (including its attribution requirement and its pane/series component model) or does it need a wrapper? Are there existing charting imports that must be removed to enforce the one-charting-stack rule, and what breaks if they are removed?

**What would close it.** A short integration note: framework, build, and theme facts; wrapper design if needed; and a list of charting imports to retire, with the old views they served.

## E. Explicitly deferred: research only if the goal changes

These are not on the agenda to build. They are listed so that a future proposal for one of them must argue against this deferral explicitly, rather than slipping in as an assumed next step:

- **Multi-user or SaaS expansion.** The maintained product serves one operator. This deferral does not remove existing account entitlements, server-enforced access or protected current-data readers; these remain mandatory under AGENTS.md and the Strategy Console contract.
- **Live trading or execution.** No order is sent by this system, under any future item in this agenda, without a separate, explicit decision that revisits the research-only guard.
- **A new mobile-first product.** A proposed desktop-focused research view does not retire the maintained Console’s desktop/tablet/mobile readability and acceptance tests. Preserve those existing journeys while evaluating any chart integration.
- **Public sharing of research projections.** Work in Public (Builder) is a separate project with its own voice and scope; research projections are not published from Alpha Engine by default, and any future publication needs a privacy review against the personal-lens boundary first.

## F. Proposed order for review (not a commitment)

For discussion only — the order below is a proposal for which items to investigate first, not a schedule. Near-term outputs are limited to A1/D3 integration facts and B1/B2 source/PIT evidence. A Decision Journal, corpus-wide migration and additional indicators remain questions, not dependencies to add to the current PRs. If the order is wrong, the correction belongs in review, not in silent reordering during implementation:

1. **A1 (Brief versus Scoreboard architecture)** and **D3 (dashboard integration facts)** — both are cheap, both unblock frontend work, and A1 prevents the most likely user confusion.
2. **B1 (PIT certification) and B2 (corporate-action source and backfill)** — both block how much weight any number can bear; they are the trust foundation for everything else.
3. **A3 (thesis authoring) and B5 (experiment triage)** — both unblock the runner race itself: without them, the scoreboard has too few real runners or too much noise.
4. **A4 (season and pool review rituals)** — makes the monthly settlement useful rather than merely recorded.
5. **C1–C3 (evaluation discipline)** and **B6 (indicator library)** — in parallel with the above, as the standards every new family must meet.
6. **C4 (five directions)** — only after the standards in (5) exist, so that prioritisation is a choice between evidenced directions, not between interesting ideas.
7. **D1–D2 (operations)** — as the daily script ( §11.2 step 4) is built, not after it has been running unmonitored.

## Review focus

Please check, in review, that: (1) no item here contradicts a decision already recorded in #1305, #1306 (including §§10–13), or #1307; (2) no item here is secretly a decision — every item is phrased as a question with a closing test, and anything that reads as decided should be flagged and either removed or moved into a decision PR; (3) the proposed order in §F is the right order, or say what should move; (4) the deferred list in §E is complete — anything missing from it that should also be explicitly deferred should be added.
