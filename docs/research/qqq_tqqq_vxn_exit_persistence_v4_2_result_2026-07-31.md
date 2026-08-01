# QQQ/TQQQ VXN exit-persistence v4.2 result

Date: 2026-08-01

Experiment: `qqq_tqqq_vxn_exit_persistence_v4_2`

Status: `research_only=true`, `trade_ready=false`, `post_result_hypothesis=true`

## Decision

Reject the two-close VXN exit-persistence rule.

The challenger reduced switches and transaction costs, but it also reduced CAGR, Sharpe, Sortino and Calmar while leaving maximum drawdown unchanged. Lower churn did not compensate for delayed exits during useful VXN stress events.

Do not add this rule to v4.1 and do not test three-day, five-day or other cooldown/persistence variants on the same sample.

## Frozen comparison

The sole change was the VXN-only exit rule for an existing leveraged position:

- baseline v4.1: exit after one VXN-stress close;
- challenger v4.2: exit after two consecutive VXN-stress closes.

Frozen in both variants:

- immediate VXN veto on new leveraged entries;
- immediate VIX stress exit;
- immediate MA20 price-failure exit;
- price-repair and VIX rules;
- 25% QQQ / 75% TQQQ leveraged allocation;
- close signal, next-open execution;
- 10 bps cost per turnover unit.

## Full-sample result

Economic sample: 2010-10-18 through 2026-07-30; 3,969 observations.

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.1 immediate VXN exit | **26.31%** | **25.78%** | **1.036** | **1.472** | -38.58% | **0.682** | **3,858.15%** |
| v4.2 two-close persistence | 25.97% | 25.99% | 1.019 | 1.444 | -38.58% | 0.673 | 3,694.37% |

Relative to v4.1, the challenger produced:

- CAGR: -0.34 percentage points;
- annual volatility: +0.20 percentage points;
- Sharpe: -0.016;
- Sortino: -0.028;
- maximum drawdown: unchanged;
- Calmar: -0.009;
- total return: -163.78 percentage points over the long sample;
- switches: 92 to 84;
- turnover units: 139 to 127;
- explicit cumulative transaction-cost deduction: 1.2 percentage points lower;
- leveraged exposure: 10 additional sessions.

The experiment therefore fails the predeclared requirement that lower turnover must not come with risk-adjusted deterioration.

## Chronological stability

| Period | v4.1 CAGR | v4.2 CAGR | v4.1 Sharpe | v4.2 Sharpe | Result |
|---|---:|---:|---:|---:|---|
| 2010-2017 | 19.57% | 19.98% | 0.990 | 1.006 | Challenger slightly better |
| 2018-2021 | **43.71%** | 41.71% | **1.322** | 1.262 | Challenger worse |
| 2022-2026 | **22.97%** | 22.67% | **0.870** | 0.860 | Challenger worse |

The rule improved the early segment but weakened both later validation segments.

## Stress windows

- 2018 Q4: identical;
- 2022 drawdown: identical;
- 2020 crash/recovery: the challenger improved total return from 65.31% to 70.69%.

The favorable 2020 window was insufficient to overcome delayed exits elsewhere.

## Session attribution

Only ten economic sessions changed. Keeping leverage for an additional day helped during transient stress in October 2015, July 2020 and August 2024, but hurt materially during:

- 2020-09-03: -6.30 percentage points relative contribution;
- 2020-10-27: -1.63 percentage points;
- 2026-05-18: -2.28 percentage points.

The sum of changed-session return deltas was approximately -3.37 percentage points.

## Cost sensitivity

The challenger remained weaker at ordinary cost assumptions:

| Cost per turnover unit | v4.1 CAGR | v4.2 CAGR | v4.1 Sharpe | v4.2 Sharpe |
|---|---:|---:|---:|---:|
| 10 bps | **26.31%** | 25.97% | **1.036** | 1.019 |
| 25 bps | **24.64%** | 24.45% | **0.984** | 0.972 |
| 50 bps | 21.90% | **21.95%** | **0.896** | 0.893 |

At 50 bps the CAGR difference narrowly reversed because of lower turnover, but Sharpe remained lower. This does not justify modifying the base strategy around an unusually high cost assumption.

## Interpretation

Phase B correctly identified that rapid VXN exits can be harmful, but the proposed persistence rule also delayed exits during the few tail events that create most of VXN's value. The diagnostic problem did not translate into a superior executable rule.

The correct action is to keep v4.1 unchanged and stop persistence/cooldown optimization.

## Next step

Proceed to independent factor challengers in the predeclared order. Test one factor at a time against unchanged v4.1 and add none unless it demonstrates clear incremental value.

The first admissible candidate is absolute market breadth used as soft leverage scaling, not the previously rejected QQQE/QQQ relative-strength hard gate.

## Evidence

- workflow run: `30692732090`;
- artifact ID: `8816230345`;
- evidence digest: `sha256:e0b5a7bc744d77ba96f465abcf4c34dd9dca5b8640d3ff42be7c7eb35f30b542`.
