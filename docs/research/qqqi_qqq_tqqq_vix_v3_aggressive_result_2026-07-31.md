# QQQI / QQQ / TQQQ VIX v3 Aggressive Result — 2026-07-31

## Decision

**Retain as an out-of-sample research challenger; do not promote to trade-ready.**

Increasing the partial-leverage state from 50% to 75% TQQQ improved return,
Sharpe and Calmar in the observed common sample. The improvement was not free:
volatility, maximum drawdown, turnover cost and the worst recovery-state day all
worsened. The incremental return was also concentrated in two long recovery
runs rather than distributed consistently across all entries.

## Isolation check

The VIX v2 baseline and VIX v3 challenger used:

- the same 627 adjusted open-to-open observations;
- identical QQQ price features and VIX states;
- identical close decision-state trace;
- identical next-open position-state trace;
- the same 36 state switches and 141 partial-leverage sessions;
- the same transaction-cost rate.

The sole executable change was:

```text
partial-leverage state
VIX v2: 50% QQQ + 50% TQQQ
VIX v3: 25% QQQ + 75% TQQQ
```

Therefore the differences below are attributable to the higher TQQQ weight and
its associated turnover cost, not to different timing rules.

## Common-window result

Economic return sample: 2024-01-30 through 2026-07-30.

| Strategy | CAGR | Volatility | Sharpe | Max drawdown | Calmar | Total return | Avg. TQQQ weight |
|---|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 64.06% | — |
| VIX v2, 50% TQQQ state | 26.67% | 24.29% | 1.095 | -23.23% | 1.148 | 80.09% | 11.24% |
| **VIX v3, 75% TQQQ state** | **29.62%** | **26.63%** | **1.108** | **-24.43%** | **1.212** | **90.68%** | **16.87%** |
| Price repair, 75% TQQQ, no VIX | 33.80% | 28.92% | 1.152 | -29.41% | 1.149 | 106.37% | 23.21% |

### VIX v3 versus VIX v2

- CAGR: **+2.94 percentage points**;
- total return: **+10.59 percentage points**;
- Sharpe: **+0.013**;
- Calmar: **+0.064**;
- annual volatility: **+2.34 percentage points**;
- maximum drawdown: **1.20 percentage points deeper**;
- turnover: **+8.0 units**;
- cumulative transaction-cost deduction: **+0.80 percentage points**.

Relative to QQQ buy and hold, VIX v3 produced 7.60 percentage points more CAGR
and a 0.068 higher Sharpe, while its maximum drawdown was only 0.26 percentage
points deeper in this sample.

## Recovery-state evidence

The partial-leverage state occurred on 141 sessions in both versions.

| Recovery-state statistic | VIX v2, 50% | VIX v3, 75% |
|---|---:|---:|
| Cumulative net return during state | 37.95% | 46.50% |
| Mean daily net return | 0.247% | 0.300% |
| Positive-session rate | 61.70% | 60.99% |
| Worst daily net return | -7.03% | -8.77% |

The higher weight increased cumulative recovery-state return by **8.55
percentage points**, but it did not improve the daily hit rate. The gain came
from larger participation in successful recoveries, accompanied by larger loss
magnitude during false starts.

## Episode concentration

There were ten contiguous partial-leverage episodes. Only five produced a
positive incremental return from raising TQQQ to 75%.

| Period | Sessions | VIX v2 return | VIX v3 return | Increment |
|---|---:|---:|---:|---:|
| 2024-08-22 | 1 | -2.50% | -3.18% | -0.67 pp |
| 2024-08-26 to 2024-08-28 | 3 | -2.75% | -3.48% | -0.73 pp |
| 2024-09-03 | 1 | -6.26% | -7.85% | -1.59 pp |
| 2024-09-16 to 2024-09-17 | 2 | 0.51% | 0.61% | +0.10 pp |
| 2024-09-20 to 2024-10-01 | 8 | -0.87% | -1.18% | -0.31 pp |
| 2024-11-08 to 2024-12-18 | 28 | 2.05% | 2.20% | +0.15 pp |
| 2025-05-13 to 2025-05-23 | 9 | 2.38% | 2.85% | +0.46 pp |
| 2025-06-02 to 2025-08-01 | 43 | 15.64% | 19.42% | +3.79 pp |
| 2026-04-10 to 2026-06-05 | 40 | 35.27% | 45.05% | +9.78 pp |
| 2026-06-16 to 2026-06-24 | 6 | -4.69% | -6.02% | -1.33 pp |

Most of the benefit came from the two long recovery episodes beginning in June
2025 and April 2026. Short, failed repairs generally became more expensive.
This concentration is the main reason not to declare 75% structurally superior
from the current sample.

## VIX still functions as the risk-budget layer

Against the matched 75% TQQQ price-repair strategy without VIX, VIX v3 gave up
4.18 percentage points of CAGR but improved maximum drawdown by 4.98 percentage
points and Calmar by 0.063. This preserves the prior finding:

> Price repair supplies the return opportunity; VIX controls how much recovery
> risk the strategy is permitted to carry.

## Persistent experiment record

The successful run wrote both the evidence package and a queryable strategy
record:

```text
artifacts/strategy_runs/
  qqqi_qqq_tqqq_vix_v3_aggressive/
    <run_id>/
      run_record.json
```

The record contains contract hashes, sample coverage, metrics, comparisons,
state diagnostics, evidence hashes, Git SHA and workflow run ID. It can be
queried through `StrategyExperimentJournal` without mixing deterministic
strategy experiments into the MLflow model registry.

## Next valid step

Freeze 75% as a named challenger and monitor it out of sample. Do not search the
current data for an apparently optimal weight such as 60%, 70%, 80% or 100%.
A later weight comparison should be separately versioned and evaluated on new
observations or a pre-registered historical proxy study.

Status remains:

```text
research_only = true
trade_ready = false
```
