# v4.2 prospective evidence ledger

**Status:** research-only; not trade-ready  
**Parent baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Operating tracker:** Issue #348

## Purpose

The ledger converts future v4.2 observations into durable, auditable evidence without changing the strategy. GitHub Issues are the long-lived record; GitHub Actions artifacts are supporting files that may expire.

The ledger records two event classes:

1. a fresh v4.2 state-change alert;
2. the start of a frozen recovery-precursor episode while executed and close-decision state both remain state 1.

A recovery-precursor record is explicitly non-actionable. It records the hypothetical 25% and 50% TQQQ research allocations but never creates Telegram target weights.

## Immutable event record

The initial Issue body contains a versioned base64-url machine record inside an HTML comment. The initial record is never overwritten. It contains:

- event ID and deterministic signal fingerprint;
- signal close date and latest governed data date;
- current and target states and weights;
- turnover and modeled cost;
- data identity and provider selection;
- signal-time VIX/VXN and QQQ repair features;
- research-only and trade-ready flags;
- recovery-precursor status and hypothetical allocations when applicable.

State-change records reuse the existing signal fingerprint, so the ledger attaches to the decision-grade signal Issue instead of creating a duplicate.

## Outcome updates

The scheduled workflow appends idempotent comments only when new evidence exists. Declared horizons are 1, 2, 3, 5, 10, 20 and 40 trading sessions after the signal close.

Updates may include:

- theoretical next-open date and ETF opening prices;
- QQQ opening gap;
- QQQ and TQQQ cumulative return;
- raw 50%-versus-25% component;
- directional leverage and TQQQ tracking/compounding attribution;
- five-session favourable and adverse excursion;
- five-session realized volatility and sign reversals;
- intraday and overnight contribution;
- time to formal state 2 or state-0 reversion.

A horizon is posted only after the required number of governed return observations exists. Missing bars and unresolved outcomes remain visible.

## Precursor episode lifecycle

Only one recovery-precursor episode may be active at a time.

- The first close satisfying the frozen precursor creates the event.
- Repeated satisfying closes do not create duplicate Issues.
- When the current close no longer satisfies the precursor, the active event is marked `precursor_closed`.
- A later, independent precursor may create a new event.
- Historical closed events cannot be reopened by a later precursor.

## Monthly summary

One Issue per calendar month reports:

- event counts by type;
- completed horizon counts;
- unresolved 40-session observations;
- delivery and evidence status where available;
- an explicit statement that model modification is not authorized.

The monthly summary is an operating report, not a model-selection document.

## Governance boundaries

The ledger does not authorize:

- changing v4.2 states, thresholds or weights;
- promoting the 25% or 50% precursor;
- selecting a confirmation delay from accumulated outcomes;
- fitting a classifier or score;
- modifying Telegram targets;
- interpreting an Actions artifact as the durable source of truth.

A separately pre-registered timing hypothesis still requires at least one independent late or prospective failed recovery event and a new decision contract.

## Operating workflow

Workflow: `QQQI v4.2 Prospective Evidence Ledger`

The workflow:

1. rebuilds the governed ETF reference bundle;
2. runs the frozen v4.2 prospective monitor;
3. builds the existing decision-alert context;
4. exports prior ledger Issues and update markers;
5. creates new event records and deterministic outcome updates;
6. persists or attaches GitHub Issues without duplication;
7. updates the monthly summary;
8. uploads supporting evidence for 90 days.

All generated records retain `research_only=true` and `trade_ready=false`.
