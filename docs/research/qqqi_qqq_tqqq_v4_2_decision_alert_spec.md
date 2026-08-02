# v4.2 decision-grade alert specification

**Effective date:** 2026-08-02  
**Baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Execution convention:** close signal, next US session open  
**Status:** research-only; no order placement

## Purpose

The alert must answer four practical questions before the user decides whether to follow the model:

1. What exactly changed?
2. What position and estimated model cost does the change imply?
3. How far are current price and volatility conditions from the frozen thresholds?
4. What confirms, invalidates or reverses the state after execution?

The alert is not a second signal engine. It consumes the canonical prospective-monitor snapshot and therefore cannot diverge from the frozen v4.2 state trace.

## Delivery roles

| Channel | Role | Content depth |
|---|---|---|
| Telegram | Immediate decision card | Concise, plain-text summary below Telegram's message limit |
| GitHub Issue | Durable audit record | Full price, volatility, evidence, execution and fingerprint context |
| Workflow artifact | Machine evidence | JSON payload, detailed Markdown, Telegram text and source monitor summary |

## Required Telegram fields

Every fresh state-change message must contain:

- signal date and intended next-open execution;
- governed latest-data date and a freshness pass/fail indicator;
- current state, current state age and target state;
- explicit buy/sell weight changes for QQQI, QQQ and TQQQ;
- turnover units and estimated model transaction cost at 10 bps per unit;
- QQQ distance from MA20, MA50 and MA200;
- current 63-session drawdown and repair-stage booleans;
- VIX and VXN values with rolling normal/stress thresholds;
- transition-specific historical evidence;
- next confirmation and invalidation conditions;
- the principal risk of the target state;
- the deterministic signal fingerprint;
- a research-only and no-auto-order statement.

## Freshness gate

A message is actionable only when:

```text
latest close signal date == latest governed market-data date
```

A stale transition may still exist in generated evidence, but the workflow must not create a new Issue or send Telegram. This prevents delayed provider updates or partial bundles from producing an apparently current rebalance instruction.

## Cost interpretation

The alert reports:

```text
turnover units = sum(abs(target weight - current weight))
estimated model cost = turnover units × 10 bps
```

This is the frozen research convention, not a guarantee of actual commission, tax or slippage.

## Decision evidence

Historical evidence is transition-specific and is stored in:

`configs/research_paradigms/qqqi_qqq_tqqq_current_baseline.yaml`

It is descriptive evidence only. It must not be presented as a forecast or expected return. Important examples:

- `0→1`: lower-confidence recovery bridge; historically most useful when recovery later failed;
- `1→2`: strongest measured return-producing transition, but also the source of the largest tail losses;
- `2→1`: risk-control transition that may sacrifice upside;
- `1/2→0`: capital-protection transition that may miss a fast rebound.

## Execution deviations

The model assumes next-open execution. A real user may encounter:

- stale or incomplete data;
- market halt;
- extraordinary opening gap;
- broker or account restriction;
- materially different transaction costs.

Any skipped or modified execution should be recorded as an explicit deviation. It must not silently alter the model's prospective evidence.

## Non-goals

The alert does not:

- place or stage an order;
- calculate position size from account value;
- override v4.2;
- add discretionary stop-loss levels;
- promise that the target state will outperform;
- notify repeatedly while the state is unchanged.
