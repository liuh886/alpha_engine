# QQQ/TQQQ v4.1 long-history validation result

Date: 2026-08-01

Experiment: `qqq_tqqq_vxn_attack_v4_1_long_history`

Status: `research_only=true`, `trade_ready=false`, `post_result_hypothesis=true`

## Decision

Retain the VXN leverage veto as a prospective monitoring candidate, but do not treat it as a clearly validated strategy factor and do not promote it into a production contract.

The long-history evidence is directionally positive but not stable enough. VXN improved full-sample return and risk-adjusted metrics with unchanged maximum drawdown, yet the advantage was sparse, driven by a small number of divergent holdings, and negative in the early historical segment. Most rolling windows affected by VXN did not outperform the frozen VIX v3 attack layer.

## Validation boundary

QQQI is excluded. No synthetic or pre-inception history is used.

Economic mapping:

- source state 0: QQQ;
- source state 1: QQQ;
- source state 2: 25% QQQ / 75% TQQQ.

The experiment therefore validates only the attack layer and does not claim historical performance for the complete QQQI / QQQ / TQQQ portfolio.

Sample:

- prepared sample: 2010-10-18 through 2026-07-31;
- economic returns: 2010-10-18 through 2026-07-30;
- observations: 3,969;
- execution: close signal, next adjusted open;
- transaction cost: 10 bps per turnover unit.

## Full-sample result

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 18.95% | 20.46% | 0.951 | 1.332 | -36.69% | 0.516 | 1,437.27% |
| Static 25% QQQ / 75% TQQQ | 37.06% | 50.79% | 0.877 | 1.232 | -74.04% | 0.501 | 14,234.19% |
| Frozen VIX v3 attack layer | 25.81% | 26.12% | 1.011 | 1.428 | -38.58% | 0.669 | 3,618.97% |
| Frozen v4.1 VXN-veto attack layer | **26.31%** | **25.78%** | **1.036** | **1.472** | **-38.58%** | **0.682** | **3,858.15%** |

Relative to the frozen VIX v3 attack layer, VXN produced:

- CAGR: +0.50 percentage points;
- annual volatility: -0.33 percentage points;
- Sharpe: +0.025;
- Sortino: +0.044;
- maximum drawdown: unchanged;
- Calmar: +0.013;
- total return: +239.18 percentage points over the full long sample;
- average TQQQ weight: 14.91% to 14.51%;
- turnover units: 127 to 139.

## Chronological stability

| Period | VIX v3 CAGR | VXN v4.1 CAGR | VIX v3 Sharpe | VXN v4.1 Sharpe | Interpretation |
|---|---:|---:|---:|---:|---|
| 2010-2017 | 20.45% | 19.57% | 1.024 | 0.990 | VXN weaker |
| 2018-2021 | 41.52% | 43.71% | 1.255 | 1.322 | VXN stronger |
| 2022-2026 | 21.53% | 22.97% | 0.821 | 0.870 | VXN stronger |

The factor therefore did not depend only on the 2026 event, but the early-period underperformance prevents a strong structural claim.

## Named stress windows

- 2018 Q4: both variants were identical and remained in QQQ.
- 2022 drawdown: both variants were identical and remained in QQQ.
- 2020 crash and recovery: the VXN variant underperformed the VIX-only attack layer, with total return 65.31% versus 69.75%.

VXN did not improve every important regime and sometimes exited useful leverage during recovery.

## Sparse attribution

Across 3,969 economic observations, the economic holdings differed on only 21 sessions.

Only three baseline leverage entries were blocked at entry:

| Signal date | 5-day TQQQ | 10-day TQQQ | 20-day TQQQ | 40-day TQQQ | Read-through |
|---|---:|---:|---:|---:|---|
| 2011-10-21 | +4.11% | +0.39% | -15.73% | -14.02% | Helpful at longer horizons |
| 2015-10-08 | +5.07% | +19.15% | +24.95% | +26.29% | Harmful; missed a major recovery |
| 2026-06-15 | -10.96% | -6.28% | -13.56% | unavailable | Helpful |

Additional VXN-triggered exits reduced several sharp losses, including September and October 2020 and June 2026, but also gave up positive leveraged days in 2020, 2024 and May 2026.

## Rolling-window stability

The median rolling performance difference was approximately zero because the strategies were identical for most sessions. Among windows whose results were actually affected by VXN:

- one-year windows: only about 31% had higher CAGR under VXN;
- three-year windows: only about 36% had higher CAGR under VXN;
- the median affected one-year and three-year CAGR deltas were negative.

The positive full-sample mean was therefore produced by a small number of large avoided losses rather than broad, consistent dominance.

## Cost sensitivity

The VXN advantage remained positive but narrowed as costs increased:

| Cost per turnover unit | VIX v3 CAGR | VXN v4.1 CAGR | VIX v3 Sharpe | VXN v4.1 Sharpe |
|---|---:|---:|---:|---:|
| 10 bps | 25.81% | 26.31% | 1.011 | 1.036 |
| 25 bps | 24.29% | 24.64% | 0.964 | 0.984 |
| 50 bps | 21.79% | 21.90% | 0.885 | 0.896 |

This confirms that extra turnover is economically relevant and should be diagnosed before any further state-machine change.

## Interpretation

VXN has a coherent role: it occasionally identifies Nasdaq-specific stress after VIX has already normalized. Its value comes from avoiding a few expensive leveraged exposures, not from improving ordinary recovery timing.

That is not yet enough to classify it as an obviously effective permanent factor because:

1. only 21 sessions changed over almost sixteen years;
2. one important 2015 recovery was incorrectly blocked;
3. the early historical segment was weaker;
4. most affected rolling windows underperformed;
5. the benefit depends on sparse tail events and additional turnover.

## Next step

Proceed to churn and dwell-time diagnostics without changing the strategy. Determine whether the extra VXN exits create avoidable short re-entry cycles and whether one simple hysteresis hypothesis is justified.

Do not add a cooldown, another factor or a new allocation tier until those diagnostics are complete.

## Evidence

- workflow run: `30691947502`;
- artifact ID: `8815971914`;
- evidence digest: `sha256:64cb61754392e2c195ebceb5eba46d69cf776ef16abf0b8800f91c5926da973f`.
