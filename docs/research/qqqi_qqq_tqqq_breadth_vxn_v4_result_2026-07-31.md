# QQQI / QQQ / TQQQ breadth and VXN v4 result

**Evidence date:** 2026-07-31  
**Economic return sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Status:** research-only; not trade-ready

## Executive conclusion

The first breadth gate is rejected. Requiring `QQQE / QQQ` to be above its 20-session average with positive five-session momentum removed most successful 75% TQQQ participation and did not improve maximum drawdown.

VXN contains incremental Nasdaq-specific information, but wholesale replacement of VIX or dual confirmation across every state is not yet superior. VXN improved Sharpe and late-sample performance, while producing a deeper full-sample drawdown. The next admissible hypothesis is therefore a **VXN leverage-layer veto** that leaves VIX responsible for QQQI/QQQ defense and initial repair.

## Strategy results

| Strategy | CAGR | Volatility | Sharpe | Max drawdown | Calmar | Total return | Partial leverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 64.06% | — |
| VIX v3, 75% TQQQ | 29.62% | 26.63% | 1.108 | -24.43% | 1.212 | 90.68% | 141 sessions |
| VIX v3 + relative breadth gate | 17.19% | 23.23% | 0.800 | -24.43% | 0.703 | 48.38% | 35 sessions |
| VXN replaces VIX | 30.12% | 25.58% | 1.158 | -26.30% | 1.145 | 92.53% | 124 sessions |
| VIX + VXN dual confirmation | 29.62% | 24.97% | 1.164 | -26.30% | 1.126 | 90.69% | 110 sessions |

## Market breadth finding

The relative breadth gate reduced average TQQQ weight from 16.87% to 4.19% and removed 106 of 141 leveraged sessions. CAGR fell by 12.43 percentage points and Calmar by 0.509, while maximum drawdown was unchanged.

The leveraged sessions retained by the breadth strategy produced a cumulative net loss of 8.40%, compared with a 46.50% cumulative gain for the baseline leveraged state.

The gate blocked eight baseline leverage entries. It correctly blocked the weak August 2024 starts, but also blocked strong subsequent recoveries, including:

- 2025-05-12: subsequent TQQQ return was approximately 14.9% over 20 sessions and 25.3% over 40 sessions;
- 2025-05-30: approximately 19.0% over 20 sessions and 30.0% over 40 sessions;
- 2026-04-09: approximately 47.5% over 20 sessions and 55.7% over 40 sessions.

### Interpretation

`QQQE / QQQ` measures whether equal-weight Nasdaq-100 is outperforming cap-weight QQQ. That is a valid concentration diagnostic, but it is not the same as asking whether a QQQ-linked leveraged position will recover.

A profitable QQQ/TQQQ recovery can remain mega-cap led. Requiring equal-weight relative outperformance therefore rejects precisely the concentration-led recoveries that TQQQ is designed to capture.

The finding rejects this proxy as a hard leverage switch. It does **not** establish that all market-breadth information is useless. A direct point-in-time constituent breadth series may still be informative, but it requires trustworthy historical membership and should be a separate data-contract project.

## VXN finding

VIX and VXN were related but not identical:

- level correlation: 0.874;
- daily percentage-change correlation: 0.930;
- VIX stress sessions: 156;
- VXN stress sessions: 193;
- common stress sessions: 141;
- VXN-only stress sessions: 52;
- VIX-only stress sessions: 15.

VXN therefore identifies materially more Nasdaq-specific stress than VIX.

### VXN-only replacement

Relative to VIX v3, replacing VIX with VXN:

- increased CAGR by 0.50 percentage points;
- increased total return by 1.85 percentage points;
- improved Sharpe by 0.050;
- reduced annual volatility by 1.05 percentage points;
- reduced turnover by 4.0 units;
- but deepened maximum drawdown by 1.87 percentage points;
- and reduced Calmar by 0.067.

The chronological split was unstable:

| Segment | VIX v3 CAGR | VXN-only CAGR | VIX v3 Sharpe | VXN-only Sharpe |
|---|---:|---:|---:|---:|
| Early common sample | 24.73% | 21.20% | 0.936 | 0.837 |
| Late common sample | 37.30% | 44.72% | 1.401 | 1.767 |

VXN helped substantially in the late sample, especially by reducing exposure during several Nasdaq-specific stress days in May and June 2026. However, replacing VIX across every state changed the earlier QQQI/QQQ path and entered the April 2025 shock from a weaker equity base, producing the deeper full-sample drawdown.

### Dual confirmation

Requiring both VIX and VXN reduced volatility and improved Sharpe, but it was too defensive:

- defensive-state occupancy increased from 58.69% to 71.13%;
- partial-leverage occupancy fell from 22.49% to 17.54%;
- full-sample CAGR was essentially unchanged;
- maximum drawdown deepened to 26.30%;
- Calmar declined.

The dual rule blocked three baseline leverage starts. Two were followed by positive TQQQ returns and one—the June 2026 false start—was followed by a material loss. This is useful information, but not enough to justify requiring VXN confirmation for every entry and every state transition.

## Architecture decision

The evidence supports a narrower role:

1. **QQQ price repair** remains the return-opportunity detector.
2. **VIX** remains the broad-market defense and initial QQQ repair overlay.
3. **VXN** should be tested only as a Nasdaq-specific veto on the 75% TQQQ layer.
4. **QQQE/QQQ relative breadth** should remain diagnostic, not a hard TQQQ gate.

A follow-up contract must preserve VIX behavior in the defensive and QQQ states, prohibit 75% TQQQ only when VXN is independently stressed, and return to QQQ when VXN stress reappears. Because this hypothesis was generated after observing v4, it cannot be treated as independent evidence and must require future out-of-sample monitoring.

## Validation

- Ruff: passed;
- focused Mypy: passed;
- breadth, VXN, inherited VIX and strategy-journal tests: passed;
- notebook compilation: passed;
- live-data workflow run: `30690518926`;
- evidence artifact: `8815500542`;
- artifact digest: `sha256:74cef0df0e77f5391721946c567997843a35b0920e66573bb03e267e71ac42ac`.
