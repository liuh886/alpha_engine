# QQQ/TQQQ absolute-breadth soft-scaling v4.2 result

Date: 2026-08-01

Experiment: `qqq_tqqq_absolute_breadth_scaling_v4_2`

Status: `research_only=true`, `trade_ready=false`

## Decision

Reject QQQE absolute trend as a soft 50%/75% TQQQ scaling factor.

The challenger reduced annual volatility modestly, but it also reduced CAGR, Sharpe, Sortino and Calmar while leaving maximum drawdown unchanged. It introduced substantially more weight changes and turnover without improving the core risk-adjusted objective.

Do not add this factor to v4.1. Do not search alternative QQQE moving-average windows, momentum windows or intermediate leverage weights on the same sample.

## Frozen comparison

The v4.1 state trace was identical between baseline and challenger.

Baseline:

- every leveraged session used 25% QQQ / 75% TQQQ.

Challenger:

- QQQE above its own MA20 with positive five-session momentum: 25% QQQ / 75% TQQQ;
- otherwise: 50% QQQ / 50% TQQQ.

The challenger did not use QQQE/QQQ relative strength and did not block entry into the recovery state.

Frozen in both variants:

- price-repair rules;
- VIX rules;
- VXN entry veto and immediate exit;
- close signal and next-open execution;
- 10 bps cost per turnover unit.

## Common-sample result

Economic sample: 2012-04-18 through 2026-07-30; 3,591 observations.

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.1 fixed 75% TQQQ | **25.92%** | 26.05% | **1.016** | **1.445** | -38.58% | **0.672** | **2,569.16%** |
| Absolute breadth 50%/75% scaling | 24.48% | **25.51%** | 0.987 | 1.398 | -38.58% | 0.634 | 2,165.17% |

Relative to fixed v4.1:

- CAGR: -1.44 percentage points;
- annual volatility: -0.54 percentage points;
- Sharpe: -0.029;
- Sortino: -0.047;
- maximum drawdown: unchanged;
- Calmar: -0.037;
- total return: -403.99 percentage points over the common sample;
- average TQQQ weight: -1.11 percentage points;
- turnover units: 127 to 175;
- weight changes: 84 to 210.

The factor therefore fails the predeclared requirement for a clear risk-adjusted improvement without material CAGR sacrifice.

## Chronological stability

| Period | Fixed CAGR | Breadth CAGR | Fixed Sharpe | Breadth Sharpe | Result |
|---|---:|---:|---:|---:|---|
| 2012-2017 | 16.96% | 16.58% | 0.911 | 0.912 | Mixed; slightly smoother but lower return |
| 2018-2021 | **43.71%** | 40.51% | **1.322** | 1.269 | Breadth weaker |
| 2022-2026 | **22.97%** | 21.48% | **0.870** | 0.837 | Breadth weaker |

The challenger was weaker in both later validation periods.

## Stress-window attribution

- 2018 Q4: identical;
- 2022 drawdown: identical;
- 2020 crash/recovery: breadth scaling reduced total return from 65.31% to 59.06% and Sharpe from 2.106 to 1.987.

The factor did not improve the major stress windows and reduced participation in the 2020 recovery.

## Weight and turnover attribution

The state trace remained identical, but the weight schedule changed 159 economic sessions and generated 126 additional weight changes.

- fixed baseline turnover units: 127;
- breadth challenger turnover units: 175;
- incremental turnover: 48 units;
- incremental cumulative transaction-cost deduction at 10 bps: 4.8 percentage points.

The sum of changed-session challenger-minus-baseline return differences was approximately -16.60 percentage points.

## Tier diagnostics

Within the breadth challenger:

- reduced 50% TQQQ tier: 159 sessions, cumulative net return +63.57%, positive-session rate 62.26%, worst day -5.96%;
- full 75% TQQQ tier: 537 sessions, cumulative net return +176.53%, positive-session rate 56.80%, worst day -10.13%.

The reduced tier had a higher hit rate and lower worst day, but scaling down those sessions still sacrificed too much cumulative return. These conditional statistics do not justify adding a factor that worsens the complete portfolio.

## Cost sensitivity

The fixed v4.1 baseline remained superior at 10, 25 and 50 bps transaction-cost assumptions. Higher costs further penalized the frequent breadth-driven weight changes.

## Interpretation

QQQE absolute trend contains intuitive market-participation information, but this frozen transformation did not allocate leverage efficiently. It mainly reduced exposure during profitable recovery sessions and added frequent internal rebalancing.

The result also confirms the governance principle that an intuitively sensible factor should not be added merely because it smooths volatility. It must improve the full risk-adjusted outcome after costs.

## Next step

Keep v4.1 unchanged and proceed to the next independent factor candidate: realized downside volatility used only as a leveraged-state veto. The factor must demonstrate information not already captured by VIX and VXN and must materially improve false-start or tail-loss outcomes after costs.

## Evidence

- workflow run: `30693039261`;
- artifact ID: `8816336601`;
- evidence digest: `sha256:1bd7d594741073b0ea1baaa77eca1882207b1d094f1f8047feaf8eacc4265a7d`.
