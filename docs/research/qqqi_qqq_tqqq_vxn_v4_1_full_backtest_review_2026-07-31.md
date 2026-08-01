# QQQI / QQQ / TQQQ v4.1 complete backtest review

**Strategy:** `qqqi_qqq_tqqq_vxn_leverage_v4_1`  
**Evidence date:** 2026-07-31  
**Economic return sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Status:** `research_only=true`, `trade_ready=false`, `post_result_hypothesis=true`

Companion notebook: `notebooks/16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb`.

## 1. Strategy architecture

The strategy is a risk-budget state machine rather than a next-day direction model:

1. QQQ price repair identifies a recovery opportunity.
2. VIX controls broad-market defense and the initial transition from QQQI to QQQ.
3. VXN only vetoes the Nasdaq-specific 75% TQQQ layer.
4. The leveraged state is fixed at 25% QQQ and 75% TQQQ.
5. Signals are generated at the close and executed at the next adjusted open.
6. Transaction cost is 10 basis points per turnover unit.

States:

- state 0: 100% QQQI;
- state 1: 100% QQQ;
- state 2: 25% QQQ plus 75% TQQQ.

## 2. Complete portfolio result

| Strategy | Total return | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Switches | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 64.06% | 22.01% | 21.30% | 1.041 | — | -24.17% | 0.911 | 0 | — |
| VIX v3, 75% TQQQ | 90.68% | 29.62% | 26.63% | 1.108 | — | -24.43% | 1.212 | — | 65 units |
| **v4.1 VXN leverage veto** | **101.17%** | **32.44%** | **25.82%** | **1.218** | **1.764** | **-24.43%** | **1.328** | **40** | **71 units** |

Relative to VIX v3, v4.1 produced:

- total return: +10.49 percentage points;
- CAGR: +2.82 percentage points;
- annual volatility: -0.81 percentage points;
- Sharpe: +0.110;
- maximum drawdown: unchanged;
- Calmar: +0.115;
- turnover: +6 units.

## 3. State-path attribution

VXN did not change the broad defensive trace. It only changed the allocation between QQQ and the leveraged state.

| State | VIX v3 | v4.1 |
|---|---:|---:|
| QQQI defensive sessions | 368 | 368 |
| QQQ attack sessions | 118 | 130 |
| Partial-leverage sessions | 141 | 129 |

Leveraged-state quality improved despite less time in TQQQ:

| Metric | VIX v3 | v4.1 |
|---|---:|---:|
| Leveraged sessions | 141 | 129 |
| Cumulative leveraged-state net return | 46.50% | 60.22% |
| Mean daily net return | 0.300% | 0.393% |
| Positive-session rate | 60.99% | 62.02% |
| Worst leveraged day | -8.77% | -7.85% |

The primary short-sample success event was the 2026-06-15 veto. VIX had normalized near 16.20 while VXN remained stressed near 25.92. TQQQ subsequently returned approximately -10.96% over five sessions and -13.56% over twenty sessions.

## 4. Chronological stability

| Segment | Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---|---:|---:|---:|---:|
| Early | VIX v3 | 24.73% | 0.936 | -24.43% | 1.012 |
| Early | v4.1 | 24.25% | 0.922 | -24.43% | 0.993 |
| Late | VIX v3 | 37.30% | 1.401 | -19.69% | 1.895 |
| Late | v4.1 | 45.71% | 1.778 | -16.20% | 2.821 |

The early segment was slightly weaker and the late segment materially stronger. This instability, together with the post-result origin of the rule, prevents promotion.

## 5. Buy/sell signal effectiveness

The notebook distinguishes the close-derived signal date from the next-open execution date and plots the actual executed buys and sells for QQQI, QQQ and TQQQ.

A separate event study compares each new allocation with the counterfactual of keeping the old allocation for 5, 10, 20 and 40 sessions.

### Twenty-session event study

| Executed action | Events | Mean return benefit versus old allocation | Median benefit | Positive-benefit rate | Mean max-drawdown improvement | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Add TQQQ leverage | 12 | **+5.76 pp** | **+4.24 pp** | **91.7%** | not the primary objective | Strongest return-producing signal |
| QQQI to QQQ | 10 | **+0.74 pp** | approximately flat | **50.0%** | limited | Weakest risk-on transition |
| TQQQ to QQQ | 8 | **-3.40 pp** | negative | low | **+6.34 pp** | Gives up upside to control drawdown |
| QQQ to QQQI defense | 10 | **-0.61 pp** | negative | low | **+3.97 pp** | Defensive rather than return-maximizing |

The signal roles are therefore asymmetric:

- initial risk-on and leverage signals should create return;
- deleveraging and defensive signals should reduce drawdown;
- a sell signal should not be judged solely by whether the risk asset subsequently rose.

## 6. Long-history attack-layer validation

QQQI is excluded rather than backfilled. Source states 0 and 1 both map to QQQ, while state 2 maps to 25% QQQ and 75% TQQQ.

Economic sample: 2010-10-18 through 2026-07-30; 3,969 observations.

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 18.95% | 20.46% | 0.951 | 1.332 | -36.69% | 0.516 |
| Static 25% QQQ / 75% TQQQ | 37.06% | 50.79% | 0.877 | 1.232 | -74.04% | 0.501 |
| Frozen VIX v3 attack layer | 25.81% | 26.12% | 1.011 | 1.428 | -38.58% | 0.669 |
| Frozen v4.1 VXN attack layer | **26.31%** | **25.78%** | **1.036** | **1.472** | **-38.58%** | **0.682** |

The long-history improvement is directionally positive but small:

- CAGR: +0.50 percentage points;
- volatility: -0.33 percentage points;
- Sharpe: +0.025;
- Sortino: +0.044;
- maximum drawdown: unchanged;
- turnover: higher.

Only 21 of 3,969 economic holdings differed. VXN prevented some tail losses but also missed the October 2015 recovery and underperformed during the 2020 crash/recovery window. It therefore remains a prospective candidate rather than a fully validated permanent factor.

## 7. Metric-led optimization diagnosis

The strongest part of v4.1 is the state-1-to-state-2 leverage transition. The weakest part is the state-0-to-state-1 transition:

- adding TQQQ has a strong twenty-session return edge;
- moving from QQQI to QQQ has only a small average edge and approximately 50% positive relative outcomes;
- maximum drawdown remains unchanged at about -24.43%;
- turnover increased relative to VIX v3.

This suggests that the next optimization should not add another timing factor to the leveraged layer. It should examine whether state 1 is too binary for an early, lower-confidence recovery phase.

## 8. Next frozen challenger

One simple allocation-only hypothesis is admissible:

- state 0 remains 100% QQQI;
- state 1 becomes 50% QQQI and 50% QQQ;
- state 2 remains 25% QQQ and 75% TQQQ;
- every signal, threshold, state transition, execution convention and cost assumption remains unchanged.

This is a confidence-weighted bridge allocation, not a new predictive factor. Exactly one 50/50 bridge is tested; no allocation grid is allowed.

Promotion requires simultaneous improvement in risk-adjusted return, no worse maximum drawdown, lower or equal turnover, and chronological stability. Any attractive result remains post-result and research-only until prospective evidence exists.
