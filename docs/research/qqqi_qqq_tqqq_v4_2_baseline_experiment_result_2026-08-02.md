# QQQI / QQQ / TQQQ v4.2 baseline experiment result

**Evidence date:** 2026-08-02  
**Economic sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Transaction cost:** 10 basis points per turnover unit  
**Current research baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Status:** research-only; not trade-ready

## Executive decision

1. Keep v4.2 as the current research baseline.
2. Keep v4.1 as the immutable historical signal comparator.
3. Reject the pure-SGOV structure as the primary replacement for v4.2.
4. Retain the blended QQQI / SGOV structure as a drawdown-focused research challenger, not as the new baseline.
5. Do not search additional SGOV weights or change any price, VIX, VXN or TQQQ rule on this sample.
6. Continue evaluating the blended challenger through drawdown-episode attribution and later prospective evidence before any promotion decision.

The corrected SGOV experiment uses signal history from 2010 for indicator warmup but begins economic comparison only when QQQI, QQQ, TQQQ and SGOV all have valid adjusted next-open returns. This restores the same 627-session economic sample used by the v4.2 baseline.

## 1. Current baseline confirmation

| Strategy | Total return | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Historical v4.1 | 101.11% | 32.42% | 25.82% | 1.218 | 1.763 | -24.45% | 1.326 | 71 units |
| **Current v4.2 baseline** | **103.52%** | **33.06%** | **25.62%** | **1.244** | **1.801** | **-24.22%** | **1.365** | **55 units** |

The recomputed values are consistent with the published v4.1/v4.2 result within normal data-refresh rounding. v4.2 keeps the exact v4.1 state trace and reduces turnover by 16 units.

## 2. Actual state-1 lifecycle attribution

The strategy contains 18 contiguous state-1 intervals in the formal sample.

| Lifecycle | Episodes | Mean sessions | Mean v4.1 net return | Mean v4.2 net return | Mean v4.2 advantage | Positive advantage rate | Mean drawdown improvement | Entry turnover saved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `0->1->0` | 5 | 17.2 | -1.75% | **-1.47%** | **+0.275 pp** | **80.0%** | **+0.417 pp** | 5 units |
| `0->1->2` | 5 | 2.6 | **+2.60%** | +2.34% | -0.257 pp | 20.0% | +0.019 pp | 5 units |
| `2->1->2` | 7 | 2.1 | -0.05% | **+0.01%** | **+0.057 pp** | 57.1% | **+0.154 pp** | 0 |
| `2->1->0` | 1 | 16.0 | +2.29% | +2.25% | -0.045 pp | 0.0% | **+0.256 pp** | 0 |

### Interpretation

The bridge behaves as intended:

- it is most valuable when an attempted recovery fails and the strategy returns from state 1 to defense;
- it generally sacrifices a small amount of upside when a recovery is quickly confirmed and the strategy moves from state 1 to state 2;
- it modestly improves drawdown behavior during temporary deleveraging intervals;
- its economic value is asymmetric risk budgeting, not better market timing.

The lifecycle table captures turnover on the state-1 entry day. The remaining full-sample turnover advantage occurs when the portfolio later exits state 1 back to state 0.

## 3. Tail-risk comparison: v4.2 versus v4.1

| Metric | v4.1 | v4.2 | Result |
|---|---:|---:|---|
| Worst daily return | -7.85% | -7.85% | unchanged; dominated by leveraged state |
| 5% daily quantile | -2.264% | **-2.258%** | slightly better |
| 95% expected shortfall | -3.940% | **-3.928%** | slightly better |
| Worst 5-session return | -12.31% | -12.31% | unchanged |
| Worst 10-session return | -15.82% | **-15.57%** | better |
| Worst 20-session return | -14.83% | **-14.58%** | better |
| Maximum drawdown | -24.45% | **-24.22%** | better by 0.22 pp |
| Recovery duration | 115 sessions | **114 sessions** | one session shorter |
| Longest underwater run | 114 sessions | **113 sessions** | one session shorter |
| Ulcer index | 0.07062 | **0.06976** | slightly better |

The v4.2 allocation improves ordinary state-1 downside behavior, but it does not solve the principal tail event because the worst daily and five-session losses occur in the unchanged leveraged state. Future drawdown improvement therefore requires either a different defensive asset or a separately justified tail-control architecture; it should not come from further bridge-weight fitting.

## 4. Frozen SGOV defensive structures

### Portfolio definitions

| State | Current v4.2 | Pure SGOV defense | Blended QQQI / SGOV defense |
|---|---|---|---|
| State 0 | 100% QQQI | 100% SGOV | 50% QQQI / 50% SGOV |
| State 1 | 50% QQQI / 50% QQQ | 50% SGOV / 50% QQQ | 25% QQQI / 25% SGOV / 50% QQQ |
| State 2 | 25% QQQ / 75% TQQQ | unchanged | unchanged |

All candidates use the exact same state dates, 40 switches, 55 turnover units and 5.50% cumulative cost deduction.

### Complete results

| Strategy | Total return | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Current v4.2** | **103.52%** | **33.06%** | 25.62% | 1.244 | 1.801 | -24.22% | 1.365 |
| Pure SGOV defense | 74.39% | 25.05% | **17.15%** | 1.390 | 2.012 | -21.03% | 1.191 |
| **Blended QQQI / SGOV** | 90.39% | 29.54% | 19.75% | **1.410** | **2.042** | **-17.91%** | **1.649** |

### Tail-risk results

| Metric | Current v4.2 | Pure SGOV | Blended QQQI / SGOV |
|---|---:|---:|---:|
| 95% expected shortfall | -3.93% | **-2.70%** | -3.05% |
| Worst 5-session return | -12.31% | **-10.44%** | -11.37% |
| Worst 10-session return | -15.57% | -15.35% | **-15.04%** |
| Worst 20-session return | -14.58% | -14.18% | **-12.61%** |
| Maximum drawdown | -24.22% | -21.03% | **-17.91%** |
| Longest underwater run | **113 sessions** | 207 sessions | 195 sessions |
| Ulcer index | 0.06976 | 0.07901 | **0.06756** |
| Main drawdown recovery | **114 sessions** | 208 sessions | 196 sessions |

### Chronological stability

#### Early segment: 2024-01-30 through 2025-07-30

| Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---:|---:|---:|---:|
| Current v4.2 | **24.67%** | 0.937 | -24.22% | 1.018 |
| Pure SGOV | 15.10% | 0.892 | -21.03% | 0.718 |
| Blended QQQI / SGOV | 20.45% | **1.009** | **-17.91%** | **1.142** |

#### Late segment: 2025-07-31 through 2026-07-30

| Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---:|---:|---:|---:|
| Current v4.2 | **46.69%** | 1.832 | -15.46% | **3.019** |
| Pure SGOV | 41.58% | **2.183** | -14.18% | 2.933 |
| Blended QQQI / SGOV | 44.44% | 2.087 | **-14.76%** | 3.011 |

## 5. SGOV decisions

### Pure SGOV defense — reject as primary architecture

Pure SGOV materially lowers volatility and expected shortfall, but:

- CAGR falls by approximately 8.01 percentage points;
- total return falls by approximately 29.13 percentage points;
- maximum drawdown improves by only approximately 3.20 percentage points;
- Calmar falls below v4.2;
- the longest underwater run increases from 113 to 207 sessions;
- ulcer index worsens.

It removes too much of QQQI's recovery participation while leaving the unchanged state-2 tail risk intact.

### Blended QQQI / SGOV defense — retain as a named challenger

The blended structure provides a more balanced tradeoff:

- maximum drawdown improves by approximately 6.31 percentage points;
- expected shortfall improves by approximately 0.87 percentage points;
- volatility falls by approximately 5.87 percentage points;
- Sharpe, Sortino and Calmar all improve;
- CAGR falls by approximately 3.52 percentage points;
- the longest underwater run increases by 82 sessions.

It passes the initial drawdown-depth objective but fails to improve drawdown duration. This distinction matters: the portfolio loses less at the trough but takes longer to reclaim its prior peak because it carries less equity exposure during recovery.

Decision: retain `qqqi_sgov_blended_defense` as a drawdown-focused challenger for further episode attribution and prospective monitoring design. Do not replace v4.2 and do not test other SGOV weights on the same sample.

## 6. Signal-alert validation

The new alert layer consumes the existing v4.2 prospective-monitor output and does not reproduce the state machine independently.

The validation run produced a genuine pending state transition from the 2026-07-31 close:

- current executed state: state 0, 100% QQQI;
- close-derived target: state 1, 50% QQQI / 50% QQQ;
- target rebalance: sell 50% QQQI and buy 50% QQQ;
- trigger: early QQQ price repair with VIX easing;
- VIX: approximately 15.99;
- VXN: approximately 26.00 and not classified as stressed;
- intended execution: next US trading-session open;
- fingerprint: `7bd5f606e67436360da1`.

PR validation deliberately does not create a live Issue or Telegram message. Production scheduled/manual runs create one owner-assigned GitHub Issue per new fingerprint and optionally send the same Chinese payload to Telegram.

## 7. Evidence

- experiment-suite workflow run: `30730596122`;
- experiment-suite artifact ID: `8827843430`;
- experiment-suite artifact digest: `sha256:7a5feaa66b4d830969b5d1ffa3aef21ca1b98f6157be3af7062b40304c6c79e4`;
- signal-alert validation workflow run: `30730596133`;
- signal-alert artifact ID: `8827841085`;
- signal-alert artifact digest: `sha256:2fec875e52d655dad94640f3a4fa8b622c1c3e8eb0f71ef4bcdc904fb4506d1a`;
- executed experiment notebook: `notebooks/18_qqqi_qqq_tqqq_v4_2_baseline_experiment_suite.ipynb`.

The first SGOV run with an economic start of 2024-10-16 was discarded because its contract did not provide sufficient pre-sample signal warmup. No decision in this report uses that truncated run.
