# VXN leverage-veto v4.1 result

**Evidence date:** 2026-07-31  
**Economic return sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Evidence status:** post-result hypothesis; research-only; not trade-ready

## Executive conclusion

Using VXN only as a veto on the 75% TQQQ layer produced the strongest risk-adjusted result in the current recovery-strategy sequence without changing the VIX-controlled defensive or initial QQQ states.

Relative to VIX v3, the overlay increased CAGR and Sharpe, reduced annualized volatility, preserved the same maximum drawdown and improved Calmar. It also removed the June 2026 false leverage start identified by VXN-specific stress.

However, this rule was generated after observing the v4 result. The evidence is therefore hypothesis-generating rather than independent, and the strategy must remain an out-of-sample monitoring candidate.

## Full-sample results

| Strategy | CAGR | Volatility | Sharpe | Max drawdown | Calmar | Total return | Partial leverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 64.06% | — |
| VIX v3, 75% TQQQ | 29.62% | 26.63% | 1.108 | -24.43% | 1.212 | 90.68% | 141 sessions |
| **VIX v3 + VXN leverage veto** | **32.44%** | **25.82%** | **1.218** | **-24.43%** | **1.328** | **101.17%** | **129 sessions** |

Relative to VIX v3:

- CAGR: **+2.82 percentage points**;
- total return: **+10.49 percentage points**;
- annual volatility: **-0.81 percentage points**;
- Sharpe: **+0.110**;
- maximum drawdown: unchanged;
- Calmar: **+0.115**;
- average TQQQ weight: 16.87% to 15.43%;
- turnover: 65 to 71 units;
- cumulative transaction-cost deduction: 6.50% to 7.10%.

The improvement survived the higher turnover assumption already charged by the backtest.

## State-path attribution

The overlay preserved the broad defensive path exactly:

| State | VIX v3 | VXN veto |
|---|---:|---:|
| QQQI defensive sessions | 368 | 368 |
| QQQ attack sessions | 118 | 130 |
| Partial-leverage sessions | 141 | 129 |

This confirms the intended architecture:

- VIX and price rules still decide when the system is defensive;
- VIX and price repair still decide when to move from QQQI to QQQ;
- VXN only decides whether Nasdaq-specific risk permits the additional TQQQ budget.

## Leveraged-state result

| Metric | VIX v3 | VXN veto |
|---|---:|---:|
| Leveraged sessions | 141 | 129 |
| Cumulative leveraged-state net return | 46.50% | 60.22% |
| Mean daily net return | 0.300% | 0.393% |
| Positive-session rate | 60.99% | 62.02% |
| Worst daily net return | -8.77% | -7.85% |

The overlay used less TQQQ time but obtained more return from the retained exposure. This is materially different from the rejected breadth gate, which removed successful recovery participation.

## Blocked leverage entry

The VXN veto blocked one baseline leverage transition:

- signal date: 2026-06-15;
- VIX was normalized at approximately 16.20;
- VXN remained stressed at approximately 25.92;
- subsequent TQQQ returns were approximately:
  - 5 sessions: **-10.96%**;
  - 10 sessions: **-6.28%**;
  - 20 sessions: **-13.56%**.

This event is economically consistent with the proposed role: broad-market fear had normalized, while Nasdaq-specific option-implied risk had not.

The overlay also reduced leveraged exposure when VXN stress reappeared during an existing TQQQ state, which contributed to the improved worst-day and late-sample risk profile.

## Chronological split

| Segment | Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---|---:|---:|---:|---:|
| Early | VIX v3 | 24.73% | 0.936 | -24.43% | 1.012 |
| Early | VXN veto | 24.25% | 0.922 | -24.43% | 0.993 |
| Late | VIX v3 | 37.30% | 1.401 | -19.69% | 1.895 |
| Late | VXN veto | 45.71% | 1.778 | -16.20% | 2.821 |

The early segment was slightly weaker, while the late segment improved materially. This asymmetry is the main reason the current result cannot be treated as stable or independently validated.

## Decision

Retain `qqqi_qqq_tqqq_vxn_leverage_v4_1` as the leading **out-of-sample monitoring candidate** for the current strategy family.

Do not:

- promote it to trade-ready;
- tune the VXN stress percentile or spike thresholds;
- add VXN easing or normalization requirements based on this sample;
- increase TQQQ weight further from this result;
- describe the result as independent evidence.

The next valid evidence should consist of future observations after 2026-07-31 or a genuinely independent historical dataset with the same frozen contract.

## Validation

- Ruff: passed;
- focused Mypy: passed;
- VXN overlay, breadth/VXN, inherited VIX and strategy-journal tests: passed;
- live-data workflow run: `30690786777`;
- evidence artifact: `8815588121`;
- artifact digest: `sha256:6184c8e2f4186d4fc90848cb4ceb974c7334d9fce56b9e17eda1ef1a07ce4cd4`.
