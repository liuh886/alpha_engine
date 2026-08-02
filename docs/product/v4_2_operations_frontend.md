# v4.2 Operations Frontend

## Purpose

The `v4.2 Operations` view answers a narrow operational question:

> What did the frozen v4.2 scheduled workflow most recently record, and how much prospective evidence has accumulated since that signal?

It is not a browser trading terminal and does not execute the strategy.

## Execution plane

GitHub Actions remains the only operating plane for v4.2:

1. build the governed QQQI / QQQ / TQQQ reference bundle;
2. run the frozen v4.2 monitor after the US close;
3. build the next-open signal context;
4. persist immutable event records and append-only observations to GitHub Issues;
5. deliver the existing Telegram alert when the governed signal workflow authorizes one.

The frontend changes none of these steps.

## Read model

The static GitHub Pages application reads the public Issue ledger through the GitHub REST API.

It decodes only these machine markers:

- `prospective-evidence-record` — immutable signal-time event;
- `prospective-evidence-update` — append-only next-open and outcome observation;
- `prospective-evidence-month` — monthly evidence accumulation summary.

Human prose is not parsed to infer a position or result.

The latest actionable event is selected deterministically from `state_change` records by:

1. signal date;
2. Issue number as the tie-breaker.

A newer `recovery_precursor` remains a separate research-only shadow event and cannot replace the actionable state-change record.

## Display semantics

### Last executed allocation at signal close

This is the immutable `current_weights` value retained when the event was created. It is not labelled as a present brokerage position.

### Close-time target allocation

This is the `target_weights` decision intended for the next session open. It remains visibly distinct from the signal-time allocation.

The frontend does not display this target as executed merely because the next session has passed.

### Execution evidence

When the append-only observation contains an `execution` object, the page shows:

- theoretical next-open date;
- theoretical next-open prices;
- QQQ opening gap when available.

This is model evidence, not a broker fill or order receipt.

### Prospective outcomes

The 1/2/3/5/10/20/40-session table is populated only from completed machine-record horizons. Missing horizons stay `Pending`; the page never extrapolates them.

## Failure behavior

The page fails visibly when:

- the public GitHub API is unavailable or rate-limited;
- no valid `state_change` machine record exists;
- a marker is malformed;
- the record weakens the required `research_only=true` or `trade_ready=false` boundary.

It does not fall back to prose scraping or the historical backtest bundle.

## Product boundary

The browser may:

- read public immutable evidence;
- compare signal-time and target allocations;
- show decision context and outcome progress;
- link to the exact durable Issue.

The browser may not:

- refresh market data;
- run v4.2;
- change thresholds, states or weights;
- write GitHub Issues;
- send Telegram alerts;
- place or simulate brokerage orders;
- promote the 25% or 50% TQQQ research comparators;
- claim `trade_ready=true`.

## Validation

The implementation includes:

- pure parser tests for base64-url markers, latest-event selection, monthly summaries and research-boundary rejection;
- static Playwright coverage with mocked public GitHub Issue records;
- desktop and mobile overflow checks;
- the existing TypeScript, lint, build and static-artifact suites.

Related Issue: #407.
