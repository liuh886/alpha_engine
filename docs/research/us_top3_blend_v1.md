# US Top-3 Blend Baseline v1

## Purpose

This document freezes the strongest current Alpha Engine research candidate as a canonical baseline for subsequent drawdown-control experiments. It preserves evidence from PR #172 without changing models, weights, universe, benchmark, cost assumptions, or promotion gates.

## Baseline identity

| Field | Value |
|---|---|
| Baseline ID | `us_top3_blend_v1` |
| Source PR | #172 — benchmark-aware Top-K evidence |
| Source merge commit | `882337c933fc899941283951e79425d2e24ce31d` |
| Market | US |
| Benchmark | QQQ |
| Candidate | 50/50 daily ranker + inverted historical 10D momentum |
| Horizon | Raw forward 10D returns only |
| Portfolio | Top-3 long-only |
| Cost | 20 bps |
| OOS windows | 2024H1, 2024H2, 2025H1, 2025H2 |

## Preserved evidence

| Metric | Value |
|---|---:|
| Positive excess windows | 4 / 4 |
| Per-window excess return | 29.43%, 12.79%, 8.23%, 5.47% |
| Compounded portfolio return | 137.16% |
| Compounded QQQ return | 50.23% |
| Compounded relative excess return | 57.87% |
| Mean window Sharpe | 2.24 |
| Worst window drawdown | -17.00% |

## Gate interpretation

The baseline is a meaningful **stronger research candidate**, but it is **not trade-ready**.

| Gate | Threshold | Observed | Pass? |
|---|---:|---:|---|
| Positive excess windows | >= 3 / 4 | 4 / 4 | yes |
| Compounded relative excess | > 30% | 57.87% | yes |
| Worst drawdown | >= -15.00% | -17.00% | no |

The drawdown gate fails because the worst observed drawdown breaches the -15.00% limit. The source PR also did not evaluate the full lifecycle promotion gate and did not model borrow constraints for the long-short diagnostic.

## Scope boundary

This baseline preservation does not:

- add a new model;
- tune blend weights;
- change the universe;
- change QQQ benchmark treatment;
- change raw 10D label semantics;
- weaken the -15% drawdown gate;
- introduce broker, order-management, or live-trading behavior;
- set `trade_ready=true`.

## Required next experiment

Run exactly three drawdown-control variants against this frozen baseline:

1. `top5_equal_weight` — Top-5 long-only, equal weight.
2. `top3_inverse_vol20_weight` — Top-3 long-only, weights proportional to `1 / vol20`, normalized to 100% gross exposure.
3. `top3_benchmark_trend_filter` — Top-3 long-only; if QQQ 20D return is negative, gross exposure is 0.5, otherwise 1.0.

Each variant must use the same data snapshot, benchmark, cost, OOS windows, frozen score source, and raw forward 10D return convention as this baseline.

## Decision

```json
{
  "baseline_id": "us_top3_blend_v1",
  "promotion_status": "stronger_research_candidate",
  "research_candidate": true,
  "trade_ready": false,
  "trade_ready_reason": "Worst window drawdown -17.00% breaches the -15.00% risk gate."
}
```
