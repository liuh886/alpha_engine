# CN130 市场状态条件化与置信度现金机制实验报告

> 2022–2023仅用于校准；2024–2025用于冻结验证；2026仅报告。

## 最终裁决

- Decision: `confidence_gate_not_supported_regime_model_not_supported`
- Confidence gate supported: False
- Regime factor model supported: False
- 不创建CN x1.1；`research_only=true`。

## 校准阈值

- 第四行业固定得分阈值：0.8000
- Top4行业均值与行业中位数固定差值阈值：0.1000

## 置信度组合（20bps）

| 方案 | 相对超额 | 最大回撤 | 正窗口 | 平均暴露 | 现金期占比 | 留一名称 | 留一行业 | 40bps超额 | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| always_invested | 67.34% | -18.38% | 4/4 | 100.0% | 0.0% | 52.59% | 24.35% | 53.59% | FAIL |
| fourth_sector_score_fixed_0_80 | 55.95% | -19.14% | 4/4 | 96.5% | 14.0% | 40.45% | 14.20% | 43.12% | FAIL |
| risk_off_half_cash | 53.02% | -15.31% | 4/4 | 88.0% | 24.0% | 38.61% | 16.27% | 41.32% | FAIL |
| risk_off_full_cash | 38.64% | -13.25% | 3/4 | 76.0% | 24.0% | 24.68% | 7.62% | 28.82% | FAIL |
| sector_gap_fixed_0_10 | 36.76% | -16.54% | 3/4 | 62.0% | 38.0% | 35.93% | 13.73% | 26.37% | FAIL |
| combined_fixed_thresholds | 27.77% | -17.27% | 3/4 | 58.5% | 52.0% | 25.30% | -15.03% | 18.34% | FAIL |

## 市场状态条件化因子

- Mean Rank IC: -0.0027
- 正窗口：2/4
- 最差窗口：-0.0835
- 增量Rank IC：-0.0117
- Mean Spread：-0.40%
- Gate: FAIL

### 每个状态冻结因子
- risk_on: intraday_range_20__global(-1), distance_low_20__global(-1), momentum_20__global(-1), amihud_20__global(+1), volume_price_confirmation_20__sector_relative(+1)
- repair: trend_efficiency_20__sector_relative(+1), drawdown_63__global(+1), distance_low_20__global(+1), downside_volatility_20__global(-1), residual_momentum_20__global(+1)
- risk_off: residual_momentum_20__global(-1), amihud_20__global(+1), drawdown_63__global(-1), momentum_10__global(-1), distance_low_20__sector_relative(-1)
- neutral: amihud_20__global(+1), intraday_range_20__sector_relative(-1), distance_low_20__sector_relative(-1), volume_price_confirmation_20__global(+1), reversal_3__global(-1)

## 解释边界

- 置信度阈值采用预注册固定定义，不使用验证期收益。
- 因子方向、选择和权重仅来自2022–2023。
- 当前静态池仍存在生存者偏差；PIT基本面与市值未覆盖。
