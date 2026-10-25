# Alpha Engine v1.0 — Direction A Product Completion Charter

**Product positioning RATIFIED by owner 2026-10-25:** Direction A — a
**personal, single-operator professional quantitative research workstation**.
Detailed acceptance and implementation remain **DRAFT PR #1276** until review.
This confirms accepted [ADR-0003](../adr/0003-single-user-local-quant-research-platform.md),
not a new multi-user or trading architecture. This document does **not**
override `AGENTS.md`, `docs/product/strategy_console.md`, existing frozen
research/evidence contracts, the strategy registry or CI governance. Related
prioritization: Issue #1074. No new operating surface is authorized here.

## Product thesis: complete the existing loop, not enlarge the feature list

Alpha Engine v1 should let one researcher/investor answer reliably:

1. Did each accepted strategy evaluate on its governed cadence, and at which
   verified market/decision/formal-evidence cutoffs?
2. What changed, what remained unchanged or not due, and **why**?
3. How does its historical performance, drawdown, risk, trading and attribution
   compare with the exact declared benchmark, with source and cost semantics?
4. When an input, release, permission or delivery is blocked, is the cause,
   affected strategy, last valid evidence, and the existing recovery action clear?
5. Can the single operator locally reproduce an accepted US and CN reference
   research result with pinned data, model/evaluator identity, PIT and cost
   contracts, or see exactly why a required input is blocked?
6. Which independent research hypotheses have genuinely earned promotion, and
   which are only diagnostic / insufficiently evidenced?

This is a **governed research-and-strategy-observation product**,
`research_only=true`, `trade_ready=false`. Not an auto-trading platform,
general-purpose trading terminal, new factor playground, or a portfolio SaaS
expansion. The two complementary v1 modes are **local CLI-based reproducible
research** and a **read-only web Strategy Console** for accepted strategy
monitoring/explanation. The retired in-browser research IDE is NOT a v1 gap.
External onboarding, payments/subscriptions, multi-tenant RBAC, collaborative
hosting and external support/SLA are **out of scope**. Preserve existing public
formal evidence and the Supabase RLS/Pro boundary for protected current signals:
single-user scope does not authorize weakening existing security.

### Maintained scope (read from authorities, never duplicate as runtime source)

- 4 active strategies: QQQ Rotation v4.3, US x1.3, CN_27 v1.3, BYD v1.3
  (names here for design review; runtime identities from
  `configs/strategies/registry.json`).
- Supported navigation: Overview `/app`, strategy details, linked instrument
  explanation `/securities/:market/:symbol`, Operating Status `/system`.
- Historical Model Run Bundle v2 is formal evidence; Strategy Decision Ledger
  is current decision truth; Strategy Operations is its read projection;
  Supabase policy/RLS is the protected current-signal authority.
- RDI is a **separate, unvalidated research initiative**. Existing Operating
  Status may show its dated research readiness, but no RDI risk score, live
  current signal or strategy modification until qualified evidence and approval.

## Core experience / journey contract

```text
Completed US/CN trading session
  -> provider cutoff and data verification
  -> strategy-due decision (or documented not-due / unchanged)
  -> sealed decision + governed formal publication, independently dated
  -> entitled Overview: what happened, why, when next
  -> strategy detail: evidence, benchmark, drawdown, positions, trades, drivers
  -> instrument detail: source-bound history and historical model events
  -> Operating Status: data cutoffs, named blockers, existing recovery link
```

No web read refresh may trigger data downloads, training, backtests, automatic
publication or orders. Browser presentation never fabricates private signals,
missing evidence, fills, prices or next-session targets.

## Product quality pillars / measurable acceptance

**Reliability (P0)** — Collect a reviewed **20 eligible trading-session per
market**
operating acceptance for the existing four strategies, as already required by
`docs/architecture/repository_data_convergence.md`. Verify strategy-specific
cadence (CN_27 30-session cadence is not a daily rebalance), market cutoff,
provider freshness, formal publication, decision receipt, notification/delivery,
and whether manual remediation was needed. Count healthy no-change and not-due
honestly; never credit a stale or blocked refresh. A 20-session CN sample may
not include a CN_27 due rebalance (30-session cadence), so capture a separately
evidenced actual due event or deterministic due-path acceptance without
misrepresenting it as 20-session production evidence. Acceptance is based on
recorded session evidence, not green CI alone. Keep each blocked subsystem scoped.

**Trust (P0)** — Public formal histories and protected current operations must
remain distinct. Verify unauthenticated, member, Pro, owner, expired-session and
permission-change behavior against the deployed policy. No private targets or
current holdings in GitHub Pages assets, logs or frontend fallbacks.

**Reproducible local research (P1/v1)** — Reuse existing `alpha data`,
`alpha research` and evidence pipelines. Demonstrate a pinned and repeatable
accepted US and CN reference research/evaluation path with truthful blockers.
A research hypothesis returning poor alpha is a valid research outcome;
profitability, all candidate factor readiness and RDI promotion are not
software release gates.

**Data/Research (P0/P1)** — Preserve provider/timezone/PIT semantics,
adjustments, corporate-action lifecycle, identity, benchmark consistency,
dataset coverage and source hashes. Existing partial training profiles remain
explicit blockers. Research must record genuine walk-forward out-of-sample
evidence, negative outcomes and promotion decisions; no favorable retrospective
re-labeling.

**Decision UX (P1)** — For each active strategy and desktop/mobile viewport, a
reader can identify current state, event dates, benchmark-relative result,
drawdown, last model change and failure reason **without reading CI logs**.
Test 4 canonical scenarios: (a) valid changed decision, (b) valid unchanged /
not-due, (c) source delayed/blocked, (d) denied/expired entitlement. Demonstrate
instrument drill-down with exact model-identity events and no invented trade.

**Recovery/Delivery (P1)** — The owning failure stage and supported repair route
are explicit; the existing workflow is the only execution surface.
A repaired session yields new verified evidence without silently rewriting a
past decision or conflating a prior read with fresh delivery. Include failure
injection and restoration tests.

**Release (P1)** — One documented PR -> CI -> reviewed formal evidence ->
release -> post-release verification -> rollback route. Every release records
artifact identity, exact cutoffs, user-facing differences and gate receipts.

## Maturity gates (do not interpret as promised deadlines)

- **Research Prototype:** valid architecture, frozen hypotheses, synthetic tests;
  no predictive/operating claims.
- **Beta (current provisional assessment):** accepted formal bundles, coherent
  Console, protected current-reader contract and deployed delivery exist; full
  consecutive-session acceptance or task-based UAT is not yet evidenced here.
- **Release Candidate:** verified 20-session operating receipt; product trust/UAT
  acceptance; no unidentified source truth splits, incorrect privacy exposure,
  or non-reproducible release.
- **v1 Complete:** same acceptance holds at an actual release cut, with owner
  signoff, support/runbook, revert test, and a frozen scope contract. New RDI or
  strategies are *not* prerequisites for v1.

## Sequencing

1. **P0 — Close truth and operations:** continuous operating acceptance +
   access/privacy evidence, fix actual blockers; don't add workflows.
2. **P0 — Eliminate documentation ambiguity:** mark historic visions/matrices
   clearly as historical; consolidate current development contracts and resolve
   stale issues only after checking actual evidence.
3. **P1 — Finish user flows:** accept Overview -> Strategy Detail -> Instrument
   -> Status, including failure and authorization states; targeted improvements
   only where real task completion fails.
4. **P1 — Complete governed research reproduction:** accepted model evidence
   from frozen sources and OOS gates; stay on current four strategies.
5. **P2 — Polish after validation:** measured performance, accessibility,
   operational cost and optional integrations; no speculative feature additions.

Do not open a second registry, database, scheduler, dashboard, provider pipeline,
agent execution layer or automatic order integration. The 39-workflow ceiling
is already fully utilized in the reviewed tree; any new permanent workflow
requires retiring/replacing an existing path and demonstrating benefit.

## Ratified product decision vs deferred expansion

- **Ratified:** Direction A, personal single-operator quantitative research
  workstation. One owner can conduct local governed research, follow four
  accepted strategies, understand evidence and recover from failures.
- **Existing authority preserved:** ADR-0003; `AGENTS.md`;
  `docs/product/strategy_console.md`; active model registry; immutable formal
  evidence and decision ledger; current Supabase/RLS access enforcement.
- **Engineering success is not investment alpha:** test reproducibility,
  correct timestamps, current-state truth, source integrity, UAT and reliable
  releases. Strategy profitability is an independent research outcome.
- **Deferred:** external subscribers, billing, organization accounts,
  hosted multi-user collaboration, new primary navigation, autonomous orders,
  and RDI live score/strategy allocation overlays.
- **Under evidence review:** quantitative source-lag and runtime SLO targets.
  Establish these from observed eligible-session data, not by retrospectively
  choosing a pass threshold.
- **Acceptance authority:** [Direction A v1 scorecard](product_completion_scorecard_2026-10-25.md)
  and [local Agent execution roadmap](v1_direction_a_agent_roadmap_2026-10-25.md)
  define specific release gates; the owner has not approved deployment
  merely by approving this product direction.

## Current scoped implementation backlog (owner review pending)

- **#1277 / P0 Operating acceptance:** verify 20 eligible market sessions,
  sealed strategy decisions and genuine delivery/repair evidence; no phantom
  freshness or new monitoring workflow.
- **#1278 / P0 Documentation authority:** resolve obsolete product/connected
  runtime descriptions while preserving history and checking affected callers.
- **#1279 / P1 User task UAT:** 4 active strategies across desktop/mobile,
  changed/unchanged/delayed/denied and linked instrument flows; first collect
  observed evidence, then open narrowly scoped UX fixes.
- **#1281 / P1 RC/rollback:** single-owner runbook and real release/recovery
  acceptance without a new deployment stack.
- **Existing issues, do not duplicate:** #324/#325 data eligibility, #826
  reproducible training, #1272 PIT-safe RDI research (not v1 release gate),
  #1074 overall convergence priority.

### Ongoing owner–architect–local Agent review loop

Each milestone review records **(a)** release/main SHA and source cutoff,
**(b)** which user journey succeeded or failed with evidence, **(c)**
accepted/rejected architecture decision and why, **(d)** changes to milestone
scorecard, **(e)** ready-for-agent Issues with immutable acceptance. Product
direction is set by the owner; architecture proposes/scrutinizes; the local
Agent writes and tests code under a single scoped Issue and returns a PR.
A review may intentionally decide to delete or defer a feature. Avoid
replanning the whole product after each research experiment.

## Authority and change control

GitHub Issues own *active tasks*; accepted ADRs/AGENTS/strategy_console own
operational constraints; this document explains proposed direction. Local
agents act only on scoped issues and reviewed PRs, following
`docs/product/local_agent_delivery_contract_2026-10-25.md`. Do not rewrite
`TASKS.md` or historical project vision wholesale; reconcile stale documents
through a scoped, separately reviewed docs PR.
