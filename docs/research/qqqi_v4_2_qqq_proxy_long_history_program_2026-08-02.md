# v4.2 recovery precursor: QQQ proxy long-history program

**Pre-registration date:** 2026-08-02  
**Status:** research-only; not trade-ready

## Research question

Does the historical preference for a 50% TQQQ recovery precursor over the 25%
precursor survive when the short QQQI return history is mechanically replaced
with the much longer QQQ return history?

QQQI was launched in January 2024. The existing product-specific experiment
therefore contains only three precursor episodes. QQQ has a much longer history,
but this experiment remains limited by the actual SGOV history because no cash
or Treasury proxy is introduced.

## Fixed proxy

The experiment keeps the existing six-symbol governed data bundle. It preserves
the original QQQI bars for overlap validation, then creates a second in-memory
bar mapping in which:

```text
QQQI adjusted bars = exact copy of QQQ adjusted bars
```

No option-income estimate, distribution reconstruction, fee adjustment, tax
adjustment or covered-call simulation is applied.

## What remains frozen

- v4.2 state machine and signal trace;
- shock-memory, medium-repair, VIX and VXN precursor conditions;
- close-time decision and next-open execution;
- 10 basis points per turnover unit;
- actual SGOV and TQQQ returns;
- 25% precursor allocation;
- 50% precursor allocation;
- formal state 2 at 25% QQQ / 75% TQQQ;
- no additional weight or threshold search.

## Two evidence layers

### 1. Long-history structural proxy

The common sample begins only after all live assets required by the proxy are
tradable. With QQQI removed as the limiting asset, SGOV is expected to determine
the start date in May 2020.

The long sample compares:

- QQQ-proxy v4.2;
- QQQ-proxy static SGOV defense;
- QQQ-proxy 25% TQQQ precursor;
- QQQ-proxy 50% TQQQ precursor.

### 2. Actual-versus-proxy overlap validation

The actual QQQI experiment is rerun on its native sample. Every actual marginal
50%-versus-25% event is matched to the corresponding QQQ-proxy event by start
and end date. The experiment records whether the marginal return direction is
consistent.

## Pre-registered support gate

The QQQ proxy supports the structural 50% hypothesis only if:

- the long sample contains at least six precursor events;
- it adds at least three events beyond the actual QQQI sample;
- every actual event is matched in the overlap;
- overlap sign concordance is at least 67%;
- the proxy sample starts before the actual sample;
- 50% minus 25% CAGR is non-negative in the full, early and late sample;
- at least 60% of long-sample marginal events are positive;
- the largest event contributes no more than 50% of positive marginal benefit.

The existing 50% tail-risk and drawdown gate is also recomputed on the proxy
sample.

## Interpretation boundary

A passing proxy result may strengthen confidence that the recovery timing and
incremental leverage logic are structural. It cannot establish that QQQI itself
would have produced the same pre-2024 economics, because QQQI's option premiums,
distribution policy, fees, tax character and covered-call path dependence did
not exist in the proxy.

No proxy result can directly alter Telegram targets or authorize trading.
