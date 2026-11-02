# Alpha Engine Strategy Console

Status: active focused-core product contract, effective 2026-10-21 by user direction.

2026-11-02 Owner decision: **A / Decision-first Investment Research Workspace** as the primary frontend architecture.
PR #1357 implements the four task-oriented destinations: Today (`/app`), Strategies (`/strategies`),
Research Lab (`/research`), and System (`/system`), alongside Instrument Detail (`/securities/:market/:symbol`).
The older two-destination notes below are historical records superseded by this architecture. Source,
permission, model registration, data cutoffs, and release gates are strictly unchanged.
This frontend workspace does not constitute Gate A7 GO, live execution capability, or uncertified signal release.
See frontend_reference_first_architecture_handoff_2026-11-02.md.

2026-10-24 user direction: retire CN x1.2 from the active registry, publication
catalogs and scheduled evaluation adapters. The maintained fleet now has four
strategies. Frozen contracts, historical bundles and failure evidence remain
available for audit and do not authorize reactivation.

Chart presentation follows [Strategy chart quality](chart_quality.md).

## Local Agent start here

The product serves one operator in two complementary modes: governed local CLI
research and this read-only four-strategy Console. The accepted
[single-user ADR](../adr/0003-single-user-local-quant-research-platform.md)
does not relax existing account entitlements or server-enforced current-data
access. Local research is supported; the retired browser research IDE is not.

Read these authorities before changing code:

1. [AGENTS.md](../../AGENTS.md): current scope, selected-pool gates and research-only boundary.
2. This contract and [actual routes](../../qlib-dashboard/src/routes.ts): maintained browser journeys.
3. [Strategy registry](../../configs/strategies/registry.json) and
   [formal catalog](../../data/research/formal_model_runs/catalog.json): exact active identities;
   selected-pool/reference registries and frozen contracts remain their own authorities.
4. [Lightweight operating contract](../architecture/repository_data_convergence.md#lightweight-operating-contract),
   [recovery runbook](../operations/decision_loop_recovery_2026-10-03.md) and
   [access boundary](../architecture/frontend_access_control.md): freshness, failures and protected reads.
5. [Local setup and verification](../../README.md#本地运行) and
   [CI governance](../ci-governance.md): existing CLI and release checks; no extra scheduler or state store.

Current delivery order and task disposition live in the
[maintained execution plan](next_stage_execution_plan.md#11-2026-11-01-远端任务收敛).
For an implementation handoff, use the [scoped work packages and acceptance
commands](next_stage_execution_plan.md#12-接手-agent-的执行细则2026-11-01).

Direction A acceptance is tracked by W0 [#1278](https://github.com/liuh886/alpha_engine/issues/1278),
W1 [#1277](https://github.com/liuh886/alpha_engine/issues/1277), W1b/W2
[#1279](https://github.com/liuh886/alpha_engine/issues/1279), W3
[#1282](https://github.com/liuh886/alpha_engine/issues/1282), then W4
[#1281](https://github.com/liuh886/alpha_engine/issues/1281). Work one scoped Issue
per branch/PR from current main. Attach positive and negative evidence, exact
SHA/cutoffs and PASS/FAIL/BLOCKED/NOT_TESTED results. Actual operating sessions,
live permission tests, independent research replay and owner release approval
cannot be replaced by fixtures or green CI. The detailed A0–A7 proposal is recorded in merged [PR #1276](https://github.com/liuh886/alpha_engine/pull/1276).

[TASKS.md](../../TASKS.md), [old product vision](../product_vision.md) and
[Research Studio capability matrix](RUNTIME_CAPABILITY_MATRIX.md) retain
historical decisions. Their retired routes, models, connected browser APIs,
local ZIP readers and offline support are not implementation requirements.

2026-10-24 user correction: instrument price detail and model buy/sell markers
are useful maintained strategy-explanation features. Formal holdings, trade and
attribution instruments link to the detail page.

2026-11-02 architecture update (PR #1357): the primary navigation destinations
are Today (`/app`), Strategies (`/strategies`), Research Lab (`/research`), and
System (`/system`).

## Purpose

Provide one daily research view of existing formal strategies: current
observation, target/change, reason, next evaluation, cutoff and blockers. Python
pipelines retain data, evaluation and publication authority. The console reads
evidence; it does not execute research or orders.

## Maintained surfaces

| Route | Purpose |
| --- | --- |
| `/app` (also the root destination) | Today: daily research brief, top 3 priorities, formal strategy fleet quick access |
| `/strategies` | Strategies: formal fleet comparison, operations read status, and links to details |
| `/strategies/:strategyId` | Strategy detail: task-oriented subsections (Summary, Decisions, Risk, Evidence), period sync |
| `/securities/:market/:symbol` | Instrument detail: TradingView Lightweight Charts POC + Recharts dual-engine OHLCV, volume and model events |
| `/research` | Research Lab: Racetrack local projections & RDI historical descriptive evidence |
| `/system` | Operating Status: source publication, health diagnosis, recovery and workflow actions |

Primary navigation links Today, Strategies, Research Lab, and System. Strategy details open
from the brief or fleet; instrument details open from formal holdings/trades/attribution.
Retired routes show an unavailable view with a return to Today; they do not select a fallback data source.

Racetrack research is accessible in Research Lab (`/research?section=racetrack`) and also preserved
via existing `/app?view=racetrack` bookmarks. It displays already published local NAV series,
cumulative Top 10 rankings and Runner detail. It does not alter current operations access.
Its loopback-only data boundary, evidence validation and partial-period limitations are
specified in [Racetrack frontend](racetrack_frontend.md).

The product no longer includes standalone research, run comparison, standalone
security exploration, factors/reports/library pages, local ZIP/preview loading, marketing,
referrals, PWA/offline installation, analytics or browser access-policy editing.
Historical contracts and sealed evidence remain. The worker URL is retained only
as an unregister/cache-retirement response for existing installs.

Instrument detail is a linked historical drill-down, not an alternate current
operations reader. The existing formal sync publishes compact disposable views
of the governed market catalog: OHLCV and exact active formal model/run events,
without copying factor panels. Original source hashes are retained, projected
files are hash-verified, and formal bundle identities are checked against the
loaded catalog. Price evidence can remain readable when a model's event binding
is unavailable. Event dates and target changes are not relabeled as live fills;
an event with no matching price bar stays in the ledger and is never moved to
another date. CN x1.2 remains retired and has no current model toggle or markers.

## One evidence path

The active strategy registry binds stable strategies to accepted model versions.
Formal Model Run Bundle v2 is the historical source. Current observations use
the existing authorized Strategy Operations reader and append-only Decision
Ledger. Public files and browser state are disposable projections. No browser
view reconstructs current holdings from formal historical portfolios.

Formal history stays readable when current observations are unavailable. Static
operations contain only a protected shell with public formal identity and
cadence. Current dates, holdings, targets, explanations, drivers and ledger
provenance use the existing runtime access plane. Server policies and account
entitlement govern access. Pre-upload and live-release checks enforce the same
public-shell contract.

## Reading and recovery

Overview, strategy detail and Operating Status share one in-memory observation
reader in the existing workspace. Route navigation reuses its verified results;
explicit refresh and returning to a visible tab recheck operations. Account,
permission and formal-identity changes invalidate the previous read immediately,
including late responses. Same-identity refreshes retain the last verified
observations at their original dates, explicitly labeled as a previous read;
failed runtime authorization or identity validation removes the affected private
values. Previous reads never establish a fresh observation or operating-session
credit. A read issue retains its affected model identity so a
failure elsewhere does not become the selected strategy's blocker. Static source
health is read on Operating Status only. No additional cache, database or
scheduler is introduced. Access required, pending reads, failures, unavailable sources,
unchanged decisions and cadence-retained targets remain distinct. Observation,
target and formal evidence dates are shown separately.

Operating Status separates current observations from the static source snapshot,
showing generation time and actual provider/formal cutoffs. A static health
summary does not claim successful current runtime delivery. Refresh status
retries reads only; recovery opens existing workflows.

Details preserve the reading order: current state, performance/risk,
holdings/trades/attribution, drivers and evidence. Mobile keeps the daily brief
before filters and historical depth. Missing/stale evidence stays explicit.

## Acceptance

- Accepted strategies come from the existing formal catalog, with verified manifests and sections.
- Status and detail preserve account restrictions while formal history remains public.
- Desktop, tablet and mobile retain readable navigation and core evidence access.
- Existing installs retire only this application's worker and cache namespace.
- No retired catalog, preview or local-bundle reader is requested by the core flow.
- Reliability is judged by eligible sessions, cutoff lag, failures and manual interventions; browser tests alone do not establish it.

The system remains `research_only=true` and `trade_ready=false`.
