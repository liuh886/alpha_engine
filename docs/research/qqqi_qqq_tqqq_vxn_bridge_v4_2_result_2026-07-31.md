# v4.2 confidence-weighted bridge allocation result

**Evidence date:** 2026-07-31  
**Economic return sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Evidence status:** post-result hypothesis; research-only; not trade-ready

## Executive conclusion

The one predeclared 50% QQQI / 50% QQQ bridge improved every primary risk-adjusted metric while preserving the exact v4.1 decision trace and the exact 129 partial-leverage sessions.

The improvement did not come from a new signal or higher TQQQ exposure. It came primarily from reducing the cost and binary risk of moving fully between QQQI and QQQ during the lower-confidence state 1.

Retain `qqqi_qqq_tqqq_vxn_bridge_v4_2` as a post-result prospective monitoring challenger. Do not replace the frozen v4.1 monitoring baseline yet and do not test alternative bridge weights on the observed sample.

## Frozen comparison

| State | v4.1 | v4.2 bridge |
|---|---|---|
| 0: defensive | 100% QQQI | 100% QQQI |
| 1: early recovery | 100% QQQ | 50% QQQI + 50% QQQ |
| 2: confirmed recovery | 25% QQQ + 75% TQQQ | 25% QQQ + 75% TQQQ |

All QQQ, VIX, VXN, transition, execution and cost rules remained unchanged.

## Complete portfolio result

| Strategy | Total return | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Turnover | Cost deduction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v4.1 | 101.17% | 32.44% | 25.82% | 1.218 | 1.764 | -24.43% | 1.328 | 71 units | 7.10% |
| **v4.2 bridge** | **103.53%** | **33.06%** | **25.62%** | **1.244** | **1.801** | **-24.21%** | **1.365** | **55 units** | **5.50%** |

Relative to v4.1:

- total return: +2.36 percentage points;
- CAGR: +0.62 percentage points;
- annual volatility: -0.20 percentage points;
- Sharpe: +0.026;
- Sortino: +0.037;
- maximum drawdown: improved by 0.22 percentage points;
- Calmar: +0.037;
- turnover: -16 units;
- cumulative transaction-cost deduction: -1.60 percentage points;
- average TQQQ weight: unchanged;
- switch count: unchanged at 40.

## Attribution

### Exact state equality

- decision state was identical on every session;
- partial-leverage sessions were identical on every session;
- state 2 return trace was exactly identical;
- only state-1 weights differed.

### State-1 contribution

| Metric | v4.1, 100% QQQ | v4.2, 50% QQQI / 50% QQQ |
|---|---:|---:|
| Sessions | 130 | 130 |
| Cumulative state-1 net return | 5.50% | 6.10% |
| Mean daily net return | 0.0468% | 0.0502% |
| Positive-session rate | 53.08% | 56.15% |
| Worst daily net return | -3.54% | -3.33% |

### Cost and gross-return decomposition

The bridge did not create higher gross return over the complete portfolio:

- v4.1 gross total return: approximately 115.95%;
- bridge gross total return: approximately 115.03%;
- gross-return difference: approximately -0.92 percentage points.

The net improvement came from lower transition friction and slightly better state-1 downside behavior:

- v4.1 cumulative cost deduction: 7.10%;
- bridge cumulative cost deduction: 5.50%;
- cost saving: 1.60 percentage points before compounding effects;
- net total-return improvement: 2.36 percentage points.

The bridge halves turnover only where the model moves directly between defensive and early-recovery states:

| Transition | Events | v4.1 turnover per event | Bridge turnover per event | Total turnover saved |
|---|---:|---:|---:|---:|
| 0 to 1 | 10 | 2.0 | 1.0 | 10 units |
| 1 to 0 | 6 | 2.0 | 1.0 | 6 units |
| 1 to 2 | 12 | 1.5 | 1.5 | 0 |
| 2 to 1 | 8 | 1.5 | 1.5 | 0 |
| 2 to 0 | 4 | 2.0 | 2.0 | 0 |

## Chronological stability

| Segment | Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar |
|---|---|---:|---:|---:|---:|---:|---:|
| Early | v4.1 | 24.25% | 27.73% | 0.922 | 1.326 | -24.43% | 0.993 |
| Early | **bridge** | **24.68%** | **27.61%** | **0.937** | **1.347** | **-24.21%** | **1.019** |
| Late | v4.1 | 45.71% | 22.64% | 1.778 | 2.616 | -16.20% | 2.821 |
| Late | **bridge** | **46.68%** | **22.30%** | **1.831** | **2.700** | **-15.47%** | **3.017** |

Both chronological segments improved. The result is therefore not confined to the late 2026 event, although the complete evidence window remains short.

## Entry-event nuance

A static 5/10/20/40-session event study after each 0-to-1 entry generally favors 100% QQQ over the bridge, especially at twenty and forty sessions. This is not inconsistent with the complete portfolio result:

- the strategy does not necessarily remain in state 1 for the full event horizon;
- state 1 often ends through leverage confirmation or renewed defense;
- the bridge's primary benefit is lower round-trip turnover and better realized behavior during the actual state-1 holding intervals;
- it is an allocation-efficiency improvement, not evidence that QQQI should outperform QQQ throughout recoveries.

## Decision

Retain the bridge as a separate prospective monitoring challenger because it passed all predeclared gates:

- CAGR improved;
- Sharpe, Sortino and Calmar improved;
- maximum drawdown was not worse;
- turnover declined materially;
- the exact v4.1 state trace was preserved;
- early and late chronological segments both improved.

Do not:

- replace v4.1 as the frozen baseline before prospective evidence exists;
- test 25/75, 40/60, 60/40, 75/25 or dynamic bridge weights on this sample;
- describe the result as an independently validated strategy;
- mark the bridge trade-ready.

## Validation

- Ruff: passed;
- focused Mypy: passed;
- bridge, VXN overlay, breadth/VXN, inherited VIX and journal tests: passed;
- notebook code-cell compilation: passed;
- evidence workflow: `30706201043`;
- artifact ID: `8820398584`;
- artifact digest: `sha256:3b4962b11796ee72ec4f74cca12ddf0d40800cf5417af4e42dabfb3a3d81abbf`.
