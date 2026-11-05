# P2 — Conditional Strategy Validation Framework (local authority, Colab-ready compute)
> Architecture decision / implementation handoff · 2026-11-04; **2026-11-06 Colab-first compute location amendment** · **DESIGN ONLY / NOT IMPLEMENTED**

## 0. Owner decision: the non-negotiable product boundary

Alpha Engine is a **single-operator investment hypothesis validation platform constrained to governed, versioned selected stock pools**. This P2 extends local research, not live trading or the browser runtime.

1. **Daily or slower only**: supported signal bars are completed daily sessions (and aggregations of daily sessions such as weekly or monthly). **No 1m/5m/30m intraday data, micro-pullback execution, tape reading, or intraday backtest roadmap** for this P2. A daily momentum proxy must never be described as a reproduction of Ross Cameron's intraday strategy.
2. **Local research authority, portable compute**: the owner / local Agent authors, freezes and reviews specifications and evaluator code, and runs local baseline/parity checks. **After explicit data-provider private cloud-compute rights review, owner-initiated Google Colab handles model exploration, training, hyperparameter optimization and walk-forward batches using the same Python CLI.** No browser strategy creation, parameter editor, submit/run button, remote service API, persistent Colab worker or unattended scheduling. The concrete staged compute plan is [P2 Colab-first research compute](colab_first_research_compute_p2_2026-11-06.md) and [#1373](https://github.com/liuh886/alpha_engine/issues/1373).
3. **Browser = read-only presentation**: Today / Strategies / Research Lab / System retain the PR #1357 task boundaries. Research Lab may **read** locally reviewed, precomputed summaries and explain hypotheses, conditional evidence, failures and next reviews. It must never infer validation status from a chart. No private Q-ledger, research source bars or owner account state may be copied to public Pages.
4. **Closed selected pools**: US87 = `us_selected_equities_v2`, CN130 = `cn_selected_equities_v3` through `configs/pools/selected_pool_registry_v1.yaml`; no web-scale discovery, dynamic substitution or new public universe. QQQ/CSI300 and governed ETFs are external benchmarks/references, not pool candidates. Version and hash the pool, identity/lifecycle, source/adjustment policy and effective cutoff.
5. **Research-only by default**: `research_only=true`, `trade_ready=false`, `pit_certified=false` unless a separately authorized evidence contract proves otherwise. P2 does not modify four formal strategies, operations, account access, scheduled alerts, A0–A7 release gates, RDI readiness or the formal promotion pipeline.
6. **No new source of truth**: reuse existing authoritative data readers, evaluator paths and immutable receipts; no second market data cache/database, standalone backtest engine, second strategy registry, new GitHub Actions workflows or speculative frontend APIs.

These are **scope and negative-path acceptance criteria**, not optional implementation preferences. This architecture is subordinate to AGENTS.md, ADR-0003, active strategy / selected-pool registries and the authoritative next-stage plan. P2 has its **own independent research acceptance** and does not change product GO/NO-GO.

## 1. Baseline verified at main@bed095eb52d1 (2026-11-04)

| Existing authority | Current behavior / intended reuse | Missing P2 capability |
| --- | --- | --- |
| `src/data/research_slice.py` | One governed data-slice reader with cutoff and blocked-reason receipts | Daily-only source qualification across independent conditional studies |
| `src/research/study_workspace.py` | Four executable families: US volatility/reversal WFO, US XGB ranker, CN factor IC, A-share RDI; CLI `study list/init/run/show/compare` | New hypothesis needs real implementation, not merely a changed natural-language description |
| `src/research/experiment_harness.py` | Frozen window roles, selection/report separation, cost stress and decision gates | Reusable, cross-family conditional-evaluation contract |
| `src/research/backtest_execution_policy.py` and existing WFO/Qlib | Distinguish fast diagnostic and authoritative evidence | No replacement engine or promotion bypass |
| `src/racetrack/engine.py`, `runner.py`, `challenger.py` | Q-ledger / NAV / benchmark compare; independent US87 low-vol challenger via PR #1361 | Standard condition-aware comparisons; keep runner identities distinct |
| `src/research/study_review.py` | PR #1364 frozen hypothesis, counterevidence, review lifecycle | Connect condition-level evidence and prospective failures back into review receipts |
| `qlib-dashboard` Research Lab | PR #1357 read-only task area with local Racetrack and RDI; PR #1364 Review Desk | Auditable read-only **summary** presentation after local research and privacy review |

Important correction: the older README still describes one initial research family; current `docs/product/research_study_workspace.md` and `study_workspace.py` implement **four**. All four are specialized; the product is **not** yet arbitrary-code/no-code strategy validation. Likewise, compare currently enforces a common study family. P2 must not falsely claim cross-family equality before normalization is implemented.

## 2. Scientific question and evaluation levels

**User story**: "Within my *frozen selected pool*, does an explicitly specified signal have a persistent, tradable daily-horizon effect? Under which ex-ante market conditions does it persist or fail, after costs, compared with the pool itself?"

Separate three noninterchangeable questions:

- **Signal efficacy**: conditional forward return / excess return after a signal, before calling it a portfolio strategy. For overlapping horizons report event dependence. This is the recommended **P2 first vertical slice**.
- **Executable strategy efficacy**: well-defined next-session execution, allocation, rebalance, exposure/turnover and portfolio NAV. Use a supported existing executor with identical assumptions for the compared candidate and its baseline.
- **Prospective validity**: truly new post-freeze observations, after parameter and regime definitions are locked. OOS windows used for tuning or inspecting this PR's historical examples do not count as prospective.

A signal-study result cannot become a Racetrack runner, formal strategy, alert or trade-ready action merely by having positive forward returns.

## 3. Proposed locally governed, portable compute contract (v0 design, not an executable spec)

Create a typed, validated `ConditionalStudySpec` adapter around existing Study Workspace; **do not introduce a second study registry**. Store versioned specs alongside research experiments; generated receipts live in the existing immutable local research-artifact lineage. The included file `docs/product/examples/conditional_daily_momentum_p2_design.json` is a **non-executable example for implementation and schema review**. Do not put it in the live discovered `configs/research_experiments/` until a runner and tests exist.

Minimum fields:

| Contract field | Meaning / validation |
| --- | --- |
| `id, hypothesis, rationale, falsification` | Stable study identity, predeclared economic mechanism and null / rejection criteria |
| `market, pool_id, pool_hash` | Existing governed selected-pool identity, immutable membership and lifecycle |
| `bar_frequency, signal_as_of` | `1d` or coarser; signal based strictly on completed session data |
| `data_source, data_snapshot, cutoff, price_role, adjustment` | Exact source bytes/manifest and honest PIT qualification; no synthetic OHLC high/low |
| `signal_definition, condition_axes` | Explicit deterministic event rule and ex-ante regime labels; all features available at signal cutoff |
| `execution, horizon, capital, costs` | `next_session_open` where genuine source open exists, otherwise fail; forward-return observation is **not** a simulated fill |
| `benchmarks` | Both pool EW baseline and market benchmark when comparable; cash, delisting and missing-data semantics explicit |
| `development, selection, untouched_test, prospective_start` | Ordered nonoverlapping windows; purge >= max holding/label horizon and embargo as specified |
| `metrics, uncertainty, multiple_testing, minimum_effect` | Effect size, counts, sensitivity, intervals and frozen decision policy |
| `code_hash, data_hash, receipt_id` | Engine evaluator identity, input version and immutable output provenance |

**Acceptance gate**: reject an unsupported signal grammar, incompatible executor, nonclosed pool, insufficient timestamp/price evidence, lack of independent comparison window, failed cost stress, missing data or a result that silently changes the candidate's original hypothesis. Report `BLOCKED` with exact reason; never "green" by substituting source, forward-filling unavailable executions, relaxing thresholds after seeing outcomes or returning stale receipts as current.

## 4. Conditional analysis semantics

For each ex-ante condition group (for example bull/bear defined by **prior completed** QQQ 200-session SMA; signal RVOL threshold computed with historical eligible sessions):

1. Report **eligible universe size, events, distinct symbols, distinct sessions, independent event clusters**, date coverage, exclusions and missingness. Avoid declaring an inferential result from five overlapping observations.
2. Estimate event-horizon return, equal-horizon matched-pool return, market excess and **incremental effect over an identical baseline**. Distinguish event-study excess from portfolio alpha. Market regime effects are not causal treatment effects.
3. Produce uncertainty intervals using time-appropriate block or clustered resampling by calendar session and/or symbol (pre-specify the method and dependence assumptions). Include no-signal, no-coverage and zero-event states instead of blank charts.
4. Evaluate turnover and **base + stressed spread/slippage/commission** assumptions for actual strategy-level execution. On thin/small-cap names, daily OHLCV cannot certify a stop fill, intraday path, queue position or microstructure slippage; mark such claims unsupported.
5. Control data mining: immutable candidate family; fixed predeclared threshold grid, negative controls, number of trials and multiple-hypothesis discipline (e.g. adjusted p-values, Deflated Sharpe only when its assumptions fit). Report all attempted variants and failed gates.
6. Conduct chronological walk-forward / holdout with purge and embargo for overlapping 1/5/10-day labels. Regime definition and thresholds must be frozen using development data only; never reclassify historical regime with future data.
7. Test stress cohorts: bull/bear, high/low market volatility, years, sources when independently covered, and transaction-friction bands. A winning aggregate that fails most cohorts is conditional or weak, not "validated".
8. Enforce survival controls: today's manually curated US87/CN130 membership is **not historical whole-market representativeness**; if the pool did not exist as selected at time T, explicitly label `current_pool_historical_replay`, disclose survivorship/selection bias and prohibit general market-alpha claims. Enforce IPO/delist/tradability gates and the pool EW cash-slot policy.

### Required evidence verdicts

- `BLOCKED_DATA`: missing/unqualified input, source or PIT availability.
- `INSUFFICIENT_EVIDENCE`: low effective N, weak coverage or no untouched holdout.
- `NO_EDGE_DETECTED`: effect incompatible with practical minimum after proper uncertainty/cost adjustments.
- `CONDITIONALLY_SUPPORTED`: certain frozen regimes show a robust *historical* effect, with precise caveats.
- `SUPPORTED_OOS`: predeclared independent test passed; **not** equivalent to prospective, certified alpha or trade-ready.
- `UNDER_PROSPECTIVE_REVIEW`: immutable frozen contract accumulates new sessions.
- `REFUTED`: falsification criterion crossed; keep evidence rather than deleting the hypothesis.

These verdicts are **P2 research conclusions**, not current `src/research/study_review.py` lifecycle enum values. The adapter maps them explicitly, preserving the original review states and avoiding another state authority.

## 5. First genuine vertical slice (P2-V1)

**Hypothesis**: "A close-confirmed 20-session high breakout plus abnormal daily volume within fixed US87 has a positive 5-session **conditional** forward excess return versus frozen US87 EW and QQQ, potentially stronger in an ex-ante bullish QQQ regime."

Freeze before looking at results:
- Pool `us_selected_equities_v2`; signal `close_t > max(close_{t-20 ... t-1})`; `RVOL20_t = volume_t / mean(volume_{t-20 ... t-1})`. Require complete valid lookback and explicitly declare source adjustment and market session boundaries.
- Example threshold `RVOL20_t >= 2.0`; **illustrative design parameter, not previously validated**. Signal only after official completed close. If a portfolio trade is simulated, enter **next session open** with true unadjusted/compatible next-open evidence and costs. If only forward closes exist, publish an observational event study and no executable NAV.
- Horizon 5 sessions, with overlapping-event handling; split development/test chronologically, purge and embargo at least the longest overlapping lookahead; do not change split/threshold after viewing results.
- Conditions: QQQ close relative to **past-observable** SMA200, plus an all-regimes comparator. Do not label the regime retroactively from realized future drawdowns.
- Control comparisons: **(A)** no-signal matched pool return, **(B)** US87 EW, **(C)** QQQ; the independent low-vol Racetrack challenger can be compared **only once the result is converted to identical execution/time/cost/NAV definitions**. A stand-alone event return vs a monthly low-vol NAV is not a valid comparison.
- Deliverables: immutable local spec/hash, point-in-time eligibility/missingness receipt, candidate event rows, conditional effects with uncertainty and effective event counts, chronological OOS report, cost stress, study_review links and exact `BLOCKED`/unsupported statuses.

This is a **daily signal-mechanism proxy**; it is deliberately NOT Ross Cameron's minute-level breakout/micro-pullback rule. Do not promise his reported hit rate, risk/reward or returns.

## 6. Extension points: reuse, don't rewrite

```text
local owner / Agent -> versioned local Study Spec -> CLI "alpha research study ..."
                                                |
                                 src/data/research_slice.py
                                                |
                     existing daily candidate evaluator / signal-study adapter
                                                |
                 existing experiment_harness + WFO / Qlib / Racetrack (as eligible)
                                                |
                     standardized conditional evidence / immutable receipt
                                                |
                         src/research/study_review.py
                                                |
                 optional locally reviewed, read-only Research Lab projection
```

- Signal-study adapter can be a narrow `src/research/conditional_evaluation.py` with shared outcome schema and tests. **No parallel general-purpose portfolio simulator.**
- Candidate strategy implementations continue in local Python; parameter schema is validated and source-bound. Arbitrary natural language **does not** compile itself into an executable strategy.
- Cross-family comparison is **not automatically permitted**: a normalizer may compare event outcomes only with event outcomes, and NAV only with NAV under same calendar, universe membership, pricing, exposure, fees and execution contract. Else refuse with a reason.
- Reuse Study Workspace's atomic write + hash-bound compare; store both failed and successful evidence. Study Review may annotate a verdict but cannot rewrite existing receipts.
- Research Lab is a **consumer of precomputed published summaries**, not a producer. Existing private transport/permissions and local review (not Pages) must be reused; any new projection must pass source-path, entitlement, data-leak and fallback/denied tests before being visible. No UI extension is required for the V1 research acceptance.

## 7. Work packages and acceptance (local Agent ownership)

| Package | Change set | Exit criteria |
| --- | --- | --- |
| **P2-0 / architecture (this PR)** | Owner boundary, reuse map, frozen v0 contract, negative paths, roadmap linkage | Architecture reviewable; explicitly **not** counted as implemented runner or research result |
| **P2-1 / daily V1 evidence** | Small separate code PR: daily conditional signal adapter + schema validator, US87 momentum case, local CLI + receipts | Real governed eligible data or honest BLOCKED; one command runs frozen case; deterministic rerun same bytes/hashes; no site changes |
| **P2-2 / comparable evaluation** | Separate PR: group matrix, clustered/block intervals, N, OOS folds, costs, negative controls and multiple-testing ledger | Baseline/effect same sample; deliberate leakage, 0-event, high cost, survivorship and incomparable execution negatives all blocked/labeled; per-condition confidence stated |
| **P2-3 / reuse other families** | Separate PR: adapter for an **existing** daily strategy family, cross-family gated comparison; no new engine | Event-vs-NAV incompatibility rejected; comparable NAV under equivalent assumptions succeeds; regression tests for all four study families |
| **P2-4 / browser review (optional, later)** | Optional separate PR: locally reviewed precomputed research summary reader in existing Research Lab | Pure read-only UI, no author/run/compute APIs, exact evidence cutoff/limitations, private-path negative tests; no public research data leak |

**Ordering**: P2-1 then P2-2 are the minimal useful research capability; do not start P2-4 to imitate product progress before the backend evidence is independently reproducible. P2 work is **independent of** and must not falsely mark product A0–A7 or RDI gates complete. Avoid new schedules.

### Acceptance tests that must be supplied with implementation PRs

- Frozen pool/hash and reference-role enforcement; IPO/delist/halts and missing-bar/fallback denial.
- Two inputs with identical snapshot/code/spec yield bit-identical receipts; changed snapshot causes a new receipt, never silent overwrite.
- No lookahead: signal bar at completed T can produce next-session entry only; T+1 high/close inaccessible at T; regime SMA excludes future observations.
- Non-overlapping temporal splits / purge and embargo; synthetic fixtures intentionally leaking future state must fail.
- Data roles: open vs adjusted close vs synthetic OHLC, stale coverage or PIT uncertainties must be visible.
- Cost sensitivity and low-liquidity proxies; forbid fabricated intraday fills and daily stop-path inference.
- Sampling: zero/low independent N, correlated events, repeat symbols, multiple-testing family and negative outcomes remain inspectable.
- Parity: identical benchmark/calendar/price/fees for any cross-strategy comparison or explicit `not_comparable`.
- Security and UI: no experiment run endpoint, no browser submission controls, no account/Q-ledger disclosure; local read-only failure/denied paths.

## 8. Explicit exclusions

No intraday data investment, no minute-level strategies, no broker order submission, no automated strategy generation from web forms, no browser research IDE, no optimizer "always picks winner", no new formal fleet member, no use of current signal as a trading instruction, no hard claim of causal alpha from selected-pool historical replay.

## 9. Implementation-agent instructions

Start from **main + this architecture PR**, inspect the actual current module signatures (do not copy pseudocode blindly), implement **only P2-1 in a separate working-code PR**. Include:
1. The failing and passing test matrix + exact reproduction CLI commands on Windows/local Agent environment.
2. A real (or honestly blocked) US87 study receipt with cutoff and source/version hashes.
3. The limitations/next validation needed for this observed result; no fabricated sample sizes, returns, p-values or source attestations.
4. Proof that `qlib-dashboard`, four formal strategies, selected-pool registries, schedules and A0–A7 have not been widened.
5. A short diff-aware handoff identifying reused and newly written functions, plus migration/rollback notes. Stop before P2-2 or site work unless a subsequent scope is approved.

**Definition of done for this architecture PR only**: the decision and implementation plan are reviewable and linked from the product plan; no claim that the experimental evaluator or read-only frontend extension already exists.
