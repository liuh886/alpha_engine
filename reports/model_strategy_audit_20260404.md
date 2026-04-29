# AlphaEngine 模型与策略审计报告 (2026-04-04)

## 1. 实验 (Experiments) 与运行 (Runs)
- **mlruns/1 (US 市场)**: 
  - 运行总数: 16
  - 主要算法: LGBM (LightGBM), XGBoost
- **mlruns/2 (CN 市场)**: 
  - 运行总数: 4
  - 主要算法: LGBM (LightGBM)
- **其他**: `artifacts/models.json` 中额外记录了 Transformer (STAGING) 模型。

## 2. 策略 (Strategies) 核心逻辑
- **BiweeklyTrendStrategy** (双周趋势策略):
  - **核心逻辑**: 模型驱动排名 (Top-K=5)，60日均线 (MA60) 趋势过滤。
  - **调仓频率**: 每 10 个交易步长 (约双周) 重新平衡。
  - **规则**: `can_sell` (最小持有期=10天) 与 `is_rebalance_day`。
- **WeeklyQuantRatingStrategy** (每周量化评分策略):
  - **核心逻辑**: 基于连续 "StrongBuy" 评分 (分位数前 20%) 的累积天数 (Streak >= 3)。
  - **调仓频率**: 每周最后一个交易日。
  - **过滤**: 流动性 (20日成交额 > 10M), 价格上限 ($10,000)。

## 3. 模型权重文件 (Artifacts)
- **存储路径**: `/mnt/GitHub/alpha_engine/artifacts/models/`
- **文件总数**: 57 个 `.pkl` 文件。
- **分布**: 
  - `cn_model_*.pkl`: 10 个
  - `us_model_*.pkl`: 47 个
- **版本控制**: `model_list.yaml` 详细记录了所有模型的训练周期 (通常为 2021-2024)、参数及回测指标 (Annualized Return, Sharpe, Max Drawdown)。

## 4. 系统汇总 (Summary)
- **已训练模型总数**: 57
- **市场分布**: 47 (US), 10 (CN)
- **模型算法**: 
  - LightGBM (LGBModel): 27
  - XGBoost (XGBModel): 22
  - Transformer: 1 (STAGING)
  - 其他 (Auto-Registered): 7
- **策略类型**: 双周趋势跟踪 (Bi-weekly Trend Following), 每周量化评分 (Weekly Quant Rating)
