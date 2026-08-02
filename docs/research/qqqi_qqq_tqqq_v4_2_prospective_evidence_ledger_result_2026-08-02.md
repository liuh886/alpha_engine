# v4.2 prospective evidence ledger result

**Evidence date:** 2026-08-02  
**Baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Status:** research-only; not trade-ready

## Executive decision

The prospective evidence program from Issue #348 now has an operating ledger implementation.

- GitHub Issues are the durable event records.
- Initial signal-time facts are stored in immutable versioned markers.
- Outcomes are appended as idempotent comments at 1/2/3/5/10/20/40 trading sessions.
- Recovery-precursor episodes remain non-actionable and cannot create Telegram target weights.
- One monthly Issue summarizes evidence accumulation without authorizing a model change.
- v4.2 signal logic, target weights and Telegram targets remain unchanged.

**Decision:** `operate_prospective_ledger_without_model_change`.

## 1. Durable event model

Two event classes are supported:

1. a fresh v4.2 state change;
2. the start of a frozen recovery-precursor episode while executed and close-decision states both remain state 1.

The initial record contains the signal date, latest governed data date, deterministic fingerprint, states and weights, modeled turnover and cost, governed-data identity and the frozen signal-close feature set.

The event record is encoded in the Issue body and is never replaced by later outcomes. Outcome observations are separate machine-readable comments.

## 2. Episode lifecycle and deduplication

The ledger enforces one active recovery-precursor episode at a time.

- repeated qualifying closes do not create duplicate Issues;
- the first non-qualifying close ends the active episode;
- a later independent episode may create a new record;
- a later precursor cannot reopen an older closed event.

State-change records reuse the existing signal fingerprint. If the decision-alert workflow already created an Issue, the ledger attaches to that Issue.

## 3. Outcome evidence

For each event the updater waits for actual governed trading-session observations and may append:

- theoretical next-open date and ETF opening prices;
- QQQ opening gap;
- QQQ and TQQQ cumulative returns;
- raw 50%-versus-25% return component;
- underlying directional leverage component;
- TQQQ tracking and compounding component;
- five-session MFE, MAE, realized volatility and sign reversals;
- intraday and overnight contribution;
- time to formal state 2 or state-0 reversion.

No horizon is filled before the required number of observations exists.

## 4. Governed dry run

Workflow run `30750143744` rebuilt the governed ETF bundle and reran the frozen v4.2 monitor.

Latest governed close:

- signal date: **2026-07-31**;
- current state: **0**;
- close-decision state: **1**;
- transition: **open risk bridge**;
- deterministic fingerprint: `7bd5f606e67436360da1`;
- recovery precursor: **false**;
- theoretical execution: **2026-08-03 next US market open**;
- completed outcome horizons: **none**, because the next open had not yet occurred.

The dry run generated one state-change ledger record and no outcome update. The fingerprint matches existing Issue #333, so the production persistence path will attach the record rather than create a duplicate signal Issue.

## 5. Monthly operating summary

The dry run produced the July 2026 summary:

- state-change events: 1;
- recovery-precursor events: 0;
- completed horizons: 0;
- unresolved 40-session observations: 1;
- model change authorized: false.

The monthly summary is operational evidence only.

## 6. Persistence architecture

The scheduled workflow runs after the existing decision-alert workflow:

1. rebuild governed ETF data;
2. run the frozen monitor and alert renderer;
3. export existing ledger markers and completed horizons from Issues;
4. build new events and deterministic updates;
5. attach to an existing signal Issue or create a new research Issue;
6. append only previously unposted horizons or status changes;
7. create or update the calendar-month summary;
8. upload supporting evidence for 90 days.

Actions artifacts are not the durable source of truth because they expire. The GitHub Issue record remains available after artifact expiry.

## 7. Governance boundaries

This implementation does not authorize:

- changing v4.2;
- changing QQQI, QQQ or TQQQ weights;
- promoting the 25% or 50% precursor;
- selecting a confirmation delay;
- fitting a classifier or threshold;
- changing Telegram targets;
- treating post-execution outcomes as signal-time inputs.

A future timing hypothesis still requires an independent late or prospective failed recovery event and a separately pre-registered decision contract.

## 8. Evidence

- workflow: `QQQI v4.2 Prospective Evidence Ledger`;
- canonical run: `30750143744`;
- artifact ID: `8834169106`;
- artifact digest: `sha256:09602cec6843e5706554c7c6dccac9c3806216ffaebdbd02eba9773c97bea71f`;
- supporting specification: `docs/research/qqqi_qqq_tqqq_v4_2_prospective_evidence_ledger_spec.md`;
- operating tracker: Issue #348.
