# Alpha Engine v1.0 — Direction A Local Agent Development Roadmap

**Owner decision (2026-10-25):** v1 = a personal, single-operator professional
quant research workstation. **Status:** draft plan in PR #1276; implementation
must use existing authority (accepted ADR-0003, `AGENTS.md`,
`docs/product/strategy_console.md`, `configs/strategies/registry.json`).
The local operator researches with CLI/verified evidence and reads accepted
strategy observations through the existing read-only Console.

## Work package discipline

One Issue -> one branch based on **current main** -> narrow implementation ->
targeted & existing CI -> negative/real-world evidence -> PR -> owner review
-> merge -> deployed verification. The architect owns product questions,
architecture review and acceptance; the local Agent owns code/test/receipts;
the owner makes product and release decisions. Every task must show
READY / BLOCKED / DONE and evidence links, not only tests green. No
independent service, model registry, browser trading surface, second state
database, new schedule, external billing or multi-tenant accounts.

## W0: freeze product scope and document authority — #1278 (P0)

**First task / docs-only.** Reconcile actual main `AGENTS.md`, strategy
registry, Strategy Console and ADR-0003 with legacy `TASKS.md`,
`docs/product_vision.md`, `docs/product/RUNTIME_CAPABILITY_MATRIX.md`.
Mark historical/superseded passages with an authoritative pointer; do not
delete historical research. **DoD:** one unambiguous "start here" for a local
Agent, tested links and verified routes. Exclude new pages/feature work.

## W1: prove the operating loop — #1277 (P0)

Capture a source-hashed **20 eligible completed exchange-session window per
market** from existing operating review/decision/publication/delivery
receipts. Each session/strategy record includes provider, formal, factor,
decision, delivery cutoffs, due/not-due/unchanged/delayed/blocked, exact
cause, timing and manual intervention. QQQ and BYD have daily cadences,
US x1.3 each 10 provider sessions, CN_27 each 30 completed CN sessions;
never require daily rebalances for all strategies. A 20-session observation
may miss CN_27 due events: attach a separately evidenced actual due
cycle and deterministic due-path failure test; label separately.
**DoD:** 100% eligible sessions accounted for; zero unexplained P0 or
unmarked stale read; real incident/recovery and retained failure history.
Missing upstream evidence remains BLOCKED. No new operational scheduler.

## W1b: certify existing privacy boundaries — #1279 (P0 subset)

Test published static assets and Supabase current-operation permissions
against unauthenticated/member/Pro/owner, revocation and session expiry
where applicable, preserving existing architecture. **DoD:** zero
confirmed unauthorized current allocations/targets in publicly available
assets or unauthorized reads; formal histories remain public. Record
real request traces, negative failures and the precise affected current
resource. Do not invent multi-tenant/commerce work or drop RLS.

## W2: test the four-strategy operator journey — #1279 (P1)

For every accepted formal strategy, on desktop and mobile, verify
Overview -> Strategy Detail -> linked Instrument -> Operating Status.
Include changed and legitimate unchanged/not-due decision, stale/blocked
data, denied/expired access; mark not-applicable/untested explicitly.
Inspect benchmark, period, relative-return semantics, drawdown, holdings,
trade history vs model events, provenance and next evaluation date.
**DoD:** expected/observed screenshot and trace matrix; no critical
identity, privacy, missing-state, fill or performance misrepresentation.
Open *separate* small defect Issue after observing a real failure, not
a speculative redesign. No new main nav or research browser.

## W3: finish a reproducible local research vertical slice — #324/#325/#826 (P1)

Reuse existing canonical company event/PIT, VWAP/Alpha158 and training
issues. Demonstrate **one accepted US and one CN** reproducible local
data -> research/evaluator -> immutable evidence run with pinned sources,
reference benchmarks, exchange calendars, adjustments, corporate events,
costs, source hashes and comparisons; preserve failed experiments.
**DoD:** independently repeatable exact or documented tolerance outputs
with frozen contracts; if data lacks verified PIT coverage, report BLOCKED,
not retrospective fill. No new model/factor selection or unverified alpha
claims. Do not mark unrelated exploratory profiles ready to satisfy v1.

## W4: release as a one-operator product — #1281 (P1)

Using existing release and Pages workflows, produce an owner-local runbook:
setup from lockfiles, provider configuration and secrets handling, daily
read/doctor, controlled manual research, formal publication review,
error diagnosis, restore and rollback. Freeze one release SHA and
cutoffs, attach current deployment acceptance, privacy/static check,
post-release evidence and safe rollback rehearsal. **DoD:** A0–A6
release scorecard **PASS** (or explicit NO-GO), owner A7 signoff and
no mutation of sealed research/decision evidence during rollback.

## Priorities and explicit exclusions

| Order | Issue | Dependencies / acceptance evidence |
| --- | --- | --- |
| 0 | #1278 | Read current main; docs authority fixes |
| 1 | #1277 | Existing operating acceptance receipts; real eligible sessions |
| 1 (parallel) | #1279 privacy checks | Live protection evidence or BLOCKED |
| 2 | #1279 UAT | Representative changed/not-due/blocked/denied cases |
| 3 | #324/#325/#826 as required | Accepted local US/CN research reproducibility |
| 4 | #1281 | Gated release and owner rollback drill |

**Separate research:** RDI #1272 remains research-only/unvalidated and
does not block Direction A v1. A valid failed risk hypothesis or a strategy
that lags QQQ/CSI300 is a scientific/market result, not a software
completion failure. Commercial customers, multi-tenant hosting, external
support SLA, payment, automatic orders and new strategy lineups require
a new future owner scope decision and (where applicable) ADR review.

## Review record on every milestone

Record: latest main SHA and real data cutoff; operator question; what the
Agent shipped; observed success/failure and negative tests; risk and
added/removed permanent complexity; exact GitHub PR/evidence links;
architect PASS/BLOCK/REJECT recommendation; owner final decision.
Update the [Direction A scorecard](product_completion_scorecard_2026-10-25.md)
only on new evidence. Never rewrite historic experiments or treat
synthetic fixture passes as eligible trading-session results.
