# Alpha Engine Strategy Console

Status: active focused-core product contract, effective 2026-10-21 by user direction.

2026-10-24 user direction: retire CN x1.2 from the active registry, publication
catalogs and scheduled evaluation adapters. The maintained fleet now has four
strategies. Frozen contracts, historical bundles and failure evidence remain
available for audit and do not authorize reactivation.

Chart presentation follows [Strategy chart quality](chart_quality.md).

2026-10-24 user correction: instrument price detail and model buy/sell markers
are useful maintained strategy-explanation features. Formal holdings, trade and
attribution instruments link to the detail page. Overview and Status remain the
two primary navigation destinations.

## Purpose

Provide one daily research view of existing formal strategies: current
observation, target/change, reason, next evaluation, cutoff and blockers. Python
pipelines retain data, evaluation and publication authority. The console reads
evidence; it does not execute research or orders.

## Maintained surfaces

| Route | Purpose |
| --- | --- |
| `/app` (also the root destination) | Daily brief and formal strategy fleet |
| `/strategies/:strategyId` | Current observation and formal historical evidence |
| `/securities/:market/:symbol` | Instrument OHLCV, volume and historical model events |
| `/system` | Operating Status, dated source publication and recovery links |

Only Overview and Status appear in primary navigation. Strategy details open
from the brief/fleet. Retired routes show an unavailable view with a return to
Overview; they do not select a fallback data source.

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
