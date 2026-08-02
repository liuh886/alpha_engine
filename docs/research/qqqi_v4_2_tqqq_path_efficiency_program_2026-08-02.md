# v4.2 TQQQ precursor path-efficiency program

**Date:** 2026-08-02  
**Issue:** #398  
**Status:** research-only; not trade-ready

## Question

Why do six recovery-precursor events eventually reach formal state 2 but still lose when the shadow allocation increases TQQQ from 25% to 50%?

## Frozen evidence

This program reuses:

- the v4.2 state trace;
- the exact QQQ proxy from PR #364;
- the 15-event failure taxonomy from PR #379;
- fixed 25% and 50% TQQQ comparators;
- next-open execution and 10 bps cost.

No threshold, weight, moving average, volatility rule or persistence value changes.

## Attribution model

For each precursor event, the raw economic difference from replacing 25% QQQ with 25% TQQQ is decomposed as:

```text
25% × (TQQQ return − QQQ return)
=
25% × (daily-3x QQQ counterfactual − QQQ return)
+
25% × (TQQQ return − daily-3x QQQ counterfactual)
```

The first term is the **directional leverage component**. The second is the **tracking and compounding component**.

The 3x QQQ counterfactual compounds three times each governed QQQ open-to-open return. It is an attribution device, not a claim that a synthetic security was tradable.

## Path evidence

For each event the analysis records:

- QQQ and TQQQ 1/2/3/5/10/20-session returns;
- first-5-session favourable and adverse excursions;
- session of maximum adverse excursion;
- QQQ realized volatility and sign reversals;
- intraday and overnight log-return contributions;
- TQQQ residual relative to the daily-3x QQQ counterfactual;
- event-period directional and tracking components;
- formal state-2 and state-0 timing from the frozen taxonomy.

## Governance

Post-execution path variables explain outcomes but cannot be converted into signal thresholds in this experiment. Stable mechanisms may be added to the prospective evidence ledger only.

A new pre-registered hypothesis requires an independent late or prospective failed event. The current late segment contains three successes and no failures, so this program cannot authorize a model change by construction.
