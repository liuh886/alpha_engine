# QQQI / QQQ / TQQQ v4.2 next-stage experiment program

**Program date:** 2026-08-02  
**Baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Research status:** active; research-only

## Program objective

The next stage does not seek another retrospective headline winner. It asks three narrower questions in sequence:

1. Is the already-defined blended QQQI/SGOV profile a coherent lower-risk allocation, or is its drawdown improvement purchased through an unacceptably slow recovery?
2. Can prospective operations demonstrate that v4.2 alerts, data freshness and next-open execution are reliable enough for real-world use?
3. Is governed intraday data sufficiently complete and reproducible to justify a separate intraday-risk strategy family?

The stages must be completed in order. No stage changes the current v4.2 baseline automatically.

## Stage A — blended SGOV drawdown and recovery attribution

**Status:** started in the current research branch.

### Frozen structure

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ;
- exact v4.2 state trace;
- next-open execution;
- 10 bps per turnover unit;
- no SGOV-weight search.

### Research question

Why does the blended profile reduce maximum drawdown from roughly -24.2% to -17.9%, while extending the longest underwater period from roughly 113 to 195 sessions?

### Required outputs

- every v4.2 drawdown episode from peak to trough and recovery;
- the challenger path over the same episode start;
- drawdown improvement at the trough;
- recovery lead or lag in trading sessions;
- relative return at the baseline trough and recovery date;
- exact log-relative-wealth contribution by state 0, 1 and 2;
- separate stress, recovery and post-baseline-recovery phases;
- transaction-cost contribution;
- chronological and episode-concentration checks.

### Monitor-only gate

A separate prospective monitor may be authorized only if all predeclared checks pass:

- at least 60% of the five largest baseline drawdowns improve;
- median improvement is at least 1 percentage point;
- median recovery lag is no more than 30 sessions;
- both early and late major episodes show at least 50% improvement rates;
- no single episode contributes more than 60% of total positive improvement;
- full-sample CAGR sacrifice is no more than 4 percentage points.

Passing authorizes monitoring only. It does not replace v4.2.

## Stage B — prospective operating evidence

**Status:** active data collection; no model change.

For every new v4.2 state change after 2026-08-01, record:

- signal date and governed data date;
- Telegram and GitHub delivery status;
- alert fingerprint and duplicate suppression;
- target state and weights;
- theoretical next-open execution price;
- user-recorded or paper-execution price when available;
- opening gap and execution deviation;
- actual versus modeled transaction cost;
- whether the signal later confirmed, reversed or remained unresolved;
- realized 5-, 10-, 20- and 40-session outcomes.

### Minimum evidence before reconsidering confirmation

The `1→2` one-day confirmation observation may be revisited only after at least:

- 8 new prospective `1→2` events, or
- 24 months of monitoring,

whichever occurs later. Historical reparameterization is not a substitute.

## Stage C — intraday feasibility gate

**Status:** design only; strategy development prohibited until the gate passes.

PR #339 showed that the principal leveraged losses are usually formed during the trading session and are not visible at the preceding close. A separate intraday family would therefore require a new data and execution contract.

### Data feasibility requirements

- governed 5-minute or 15-minute bars for QQQ, TQQQ and a volatility proxy;
- consistent session calendars and daylight-saving handling;
- split and corporate-action policy appropriate for intraday bars;
- documented source identity and revision behavior;
- no survivorship or partial-session backfill;
- at least two independent data-source checks for major tail sessions;
- reproducible open, close and volume aggregation;
- explicit missing-bar and market-halt treatment.

### Execution feasibility requirements

- predeclared decision timestamp;
- next-bar or VWAP execution rule;
- spread and slippage model specific to TQQQ;
- no use of the same bar for both signal formation and execution;
- opening-auction and fast-market exceptions;
- transaction-cost stress and capacity assumptions.

### Gate decision

Only a data-quality report may be produced initially. No intraday strategy, stop-loss threshold or volatility target may be optimized until the data and execution gate passes.

## Explicitly prohibited work

- another bridge-weight grid;
- another SGOV-weight grid;
- another TQQQ-weight grid;
- moving-average or VIX/VXN threshold search;
- confirmation-length search;
- mixing intraday observations into the daily backtest without a new contract;
- promoting a challenger from headline CAGR alone.

## Expected decision tree

1. **SGOV attribution passes:** create a separate blended-profile prospective monitor; v4.2 remains baseline.
2. **SGOV attribution fails on recovery:** retain it only as a descriptive lower-volatility profile.
3. **Prospective v4.2 operations are reliable:** continue evidence accumulation without model changes.
4. **Intraday data gate passes:** open a new strategy-family issue and pre-register one simple hypothesis.
5. **Intraday data gate fails:** do not attempt intraday tail control inside Alpha Engine yet.
