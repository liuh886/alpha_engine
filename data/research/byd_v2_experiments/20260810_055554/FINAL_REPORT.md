# BYD v2.0 Regime Model — 最终实验报告

## Issue
[#716](https://github.com/liuh886/alpha_engine/issues/716)

## 执行时间
- Round 1: 2026-08-10 05:55 UTC
- Round 2: 2026-08-10 06:04 UTC

---

## 一、历史实验全景回顾

### BYD 模型演进路线

| 版本 | Issue | 方法 | 结论 | 关键指标 (Full Overlap) |
|---|---|---|---|---|
| V1.0 binary | #496 | 5种二元long/cash策略 | **REJECTED** — 全部跑输B&H | 最高CAGR 14% vs B&H 22% |
| V1.0 core/tactical | #500 | 75%核心+25%战术, SMA120滞后切换 | **ACCEPTED** — 核心-卫星架构最优 | CAGR 21.6%, MaxDD -53.7%, Calmar 0.40 |
| V1.1 dividend | #525 | 加入515180.SH替代cash | **ACCEPTED** — 全面改善 | CAGR 35.1%, MaxDD -48.7%, Calmar 0.72 |
| V1.2 recovery state | #513 | 5因子状态机(drawdown_252等) | **REJECTED** — 被V1.0全面压制 | 2025+反而跑输V1.0 |
| V1.3 recovery overlay | #516 | 事件触发overlay | **REJECTED** — 89.5%收益来自开发期 | 2025+不及V1.0 |
| V1.2 extreme defense | #560 | 极端下跌时降仓位 | **REJECTED** — 降仓正好错过反弹 | MaxDD无任何改善 |
| V1.2 trend expansion | #560 | 趋势扩张至110-125% | **HELD BACK** — 过于集中 | +0.59pp CAGR但79.7%来自验证期 |
| V1.2 convex momentum | #592/#596 | 凸性动量预算替代固定杠杆 | **PROMOTED** (当前formal) | **CAGR 35.3%, Sharpe 0.919, MaxDD -49.2%** |

### 核心经验教训

1. **Best model = simplest model**: V1.0的SMA120非对称滞后+75/25核心卫星架构是所有后续优化的基础
2. **Hysteresis is critical**: 进入全仓比退出全仓更难 → 防止whipsaw
3. **Never cut at the bottom**: extreme defense在drawdown底部降仓正好错过反弹
4. **515180.SH的作用是替代零收益现金,不是对冲**: 相关性仅0.31, 同向下跌仅26.2%
5. **Performance decay is real**: 所有模型开发期→验证期→2025+都在衰减

### V1.2 正式模型按期间表现
| 期间 | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| Development (2019-2022) | 78.9% | 1.36 | -42.2% |
| Fixed Validation (2023-2024) | 8.2% | 0.40 | -41.3% |
| Retrospective 2025+ | 4.8% | 0.30 | -37.3% |
| **Full Overlap** | **35.3%** | **0.92** | **-49.2%** |

---

## 二、V2 XGBoost Regime Model 实验结果

### Round 1 — 基准探索

#### E1: Walk-Forward 稳定性
5年expanding window (2012→2021 train, 逐年test):

| 年份 | Accuracy | Sharpe | 问题 |
|---|---|---|---|
| 2022 | 37.6% | 0.062 | 弱 |
| 2023 | 50.0% | -0.338 | 预测Bear=3.7%, 实际=34.3% |
| 2024 | 33.9% | 0.369 | 预测Bull=13.2%, 实际=68.2% |
| 2025 | 44.4% | 0.493 | 中等 |
| 2026 | 75.0% | -0.011 | 几乎全预测Neutral |

**稳定性**: MODERATE (std=0.145) — 模型系统性偏向Neutral预测

#### E2: 基准对比 (2022-2026)

| Strategy | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| **XGBoost 75/25** | **5.43%** | **0.327** | **-41.9%** |
| BYD 75%+ETF fixed | 3.29% | 0.254 | -42.3% |
| BYD Buy & Hold | 2.69% | 0.254 | -53.0% |
| BYD v1.x trend_20_60 | -3.63% | -0.074 | -35.6% |

XGBoost Regime Model是唯一正Sharpe策略。

#### E3: 持仓惯性 (⭐ 核心发现)

| Min Hold | CAGR | Sharpe | Trades | Turnover |
|---|---|---|---|---|
| None | 5.43% | 0.327 | 132 | 81.75 |
| 10d | 4.51% | 0.297 | 45 | 45.0 |
| 20d | 6.38% | 0.350 | 35 | 35.0 |
| **30d** | **9.91%** | **0.444** | **27** | **27.0** |
| 60d | 7.35% | 0.375 | 17 | 17.0 |

**30天最短持仓: 交易-80%, CAGR+82%.** 核心问题不是信号质量,是过度交易。

#### E4: 因子重要性 (Top 5)
`long_reversal`(0.088) > `drawdown_252`(0.077) > `price_percentile_3y`(0.065) > `trend_slope_120`(0.060) > `mom_12m`(0.057)

符合BYD均值回归特性 — 最强的预测因子都是逆转/回撤类。

### Round 2 — 校准优化

#### R2.1: Label Horizon
- 90d horizon最好(accuracy 61.2%, Sharpe 0.331)
- 但所有horizon的绝对Sharpe都低于R1的无约束30d min hold (0.444)

#### R2.2: 直接 vs V1.2
**v2 XGBoost全面不及V1.2**:
- Development: v2 CAGR 4.4% vs V1.2 78.9%
- Validation: v2 CAGR -2.4% vs V1.2 8.2%
- Retrospective: v2 CAGR 1.4% vs V1.2 4.8%

#### R2.3: Multi-Horizon Ensemble
- 最佳ensemble: Sharpe 0.198, CAGR 1.90% — 不及任何单模型

#### R2.4: Class-Weighted + Confidence Calibrated
- **完全失败**: 均值CAGR≈0%, Sharpe≈0.02
- 2026年零交易 — confidence threshold让模型过于保守
- **关键教训: confidence calibration摧毁了R1的收益**

---

## 三、V1.2 vs V2 XGBoost 深度对比

| 维度 | V1.2 (Convex Momentum) | V2 XGBoost Regime (best) |
|---|---|---|
| **方法论** | 确定性状态机 + 凸性预算 | XGBoost 3-class + min hold |
| **可解释性** | 完全透明(4条规则) | 特征重要性可查(黑箱) |
| **Full Overlap CAGR** | **35.3%** | ~5-10% (仅2022-2026) |
| **Full Overlap Sharpe** | **0.92** | ~0.33-0.44 (仅2022-2026) |
| **MaxDD** | -49.2% | -41.9% (2022-2026) |
| **Calmar** | **0.72** | 0.20 (2022-2026) |
| **2023-2024 CAGR** | **8.2%** | ~0-5% |
| **2025+ CAGR** | **4.8%** | ~1-2% |
| **开发→验证衰减** | 大幅(78.9%→8.2%) | 中等(但基线更低) |
| **过度交易风险** | 低(滞后机制) | 高(需要min hold约束) |
| **Neutral偏向** | N/A(总是或1或0) | **严重** - 核心缺陷 |
| **维护复杂度** | 极低(4条规则) | 中等(23因子重训练) |

### V1.2在每一个维度上都碾压V2

V2 XGBoost唯一比V1.2好的维度是MaxDD略低(-41.9% vs -49.2%), 但这不足以弥补CAGR和Sharpe的巨大差距。

---

## 四、最终实验结论

### 1. XGBoost Regime Model 不适合替代V1.2

**核心原因**:
- V1.2在6.4年全量数据上CAGR 35.3%, Sharpe 0.92 — 这是极其强健的基线
- V2在2022-2026子集上最好的CAGR仅9.91%(需要大量优化),全量远低于V1.2
- 3-class regime classification任务本质噪声太大(accuracy 0.4-0.6)
- V1.2的4条规则极其简单但效果极佳 — 复杂化没有收益

### 2. 30天最小持仓是唯一有意义的发现

- 将任何regime model的交易频率约束到每月1-2次,显著提升收益
- 但这本身证明了"减少交易>改进信号" — 回归到V1.0/V1.2的滞后设计哲学
- V1.2已经有隐含的滞后(非对称entry/exit条件) — 效果类似但更优雅

### 3. BYD建模的正确方向不是ML-based regime classification

历史证据一致表明:
- **简单滞后状态机 > 复杂多因子模型** (V1.0战胜了所有binary策略和recovery state)
- **凸性预算 > 固定杠杆** (V1.2 convex momentum战胜了trend expansion固定规则)
- **核心-卫星 > 全有全无** (V1.0的75/25架构是所有后续优化的基础)

V2探索确认了这个方向:ML不能改进已经非常优秀的规则。

### 4. V1.2的真正问题: 开发期→生产期衰减

这应该在V1.x演进框架内解决,而非重写:
- 开发期CAGR 78.9% → 验证期 8.2% → 2025+ 4.8%
- 三个期间连续衰减 → overfitting to 2019-2022 bull market
- 需要的改进: 更稳健的参数估计(rolling window calibration),而非新范式

---

## 五、建议: 停止V2 XGBoost方向

### 不做
- ❌ XGBoost/LGBM regime classifier
- ❌ 增加更多特征(已有23个,rsi_extreme贡献为0)
- ❌ Multi-horizon ensemble
- ❌ Confidence calibration

### 建议做
1. **V1.3方向**: 在V1.2规则框架内,用rolling window重新校准SMA参数和drawdown阈值
2. **Regime-aware V1.2**: 在V1.2基础上增加显式regime识别(Bull/Bear),在不同regime下使用不同的核心仓位(如Bear时核心60%替代75%)
3. **515180.SH轮动优化**: 评估515180的基本面/动量轮动信号
4. **Prospective evidence积累**: V1.2趋势扩张已在prospective shadow运行,等待更多out-of-sample证据

### V2的保留价值
- 30天最小持仓约束: **作为通用风控规则,可应用于任何BYD交易的wrapper**
- 因子重要性排名: 确认了BYD的均值回归特征(long_reversal, drawdown_252主导)
- 实验脚本: 保留作为后续探索的框架

---

## 六、产出文件

| 文件 | 说明 |
|---|---|
| `scripts/byd_v2_regime_research.py` | Round 1 实验脚本 |
| `scripts/byd_v2_regime_round2.py` | Round 2 优化脚本 |
| `data/research/byd_v2_experiments/20260810_055554/` | R1 数据+结果+记录 |
| `data/research/byd_v2_experiments/20260810_060404_r2/` | R2 数据+结果 |
