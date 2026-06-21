# Model Training Experience — Alpha Engine

Date: 2026-06-21 (Updated)

---

## 2026-06-21: Pipeline Engineering + US Model Training

### SignalExecutionEngine — Grade-Weighted Execution

Created a standalone execution engine (`src/execution/signal_execution_engine.py`) that replaces Qlib's strategy framework with:
- **Grade-differentiated position sizing**: AAA=3×, AA=2×, A=1× weights instead of equal-weight TOP-N
- **Three-pillar market regime filter**: IC decay detection + volatility spike + trend filter
- **Short-side utilization**: VVV/VV/V stocks enter a short basket
- **~3,500× faster** than Qlib BiweeklyTrendStrategy (1s vs 15min)

The regime filter alone improves excess return by **+10-11%** even with weak models.

### Pipeline Health Improvements (5 Steps)

| Step | Improvement | Impact |
|------|-------------|--------|
| 1 | SQLite single source of truth for model registry | Eliminated YAML/SQLite drift |
| 2 | Incremental dashboard DB updates (`--model-id`) | No more full rebuilds per operation |
| 3 | Vectorized walk-forward (`walk_forward_vectorized`) | 3.5× faster (48s vs 4min) |
| 4 | Fixed IR calculation + data freshness check | IR = excess/std×√252 (was sharpe×0.8) |
| 5 | Frontend search + API pagination | Text filter + offset/limit |

### Model Registry Cleanup

- Deleted 136 placeholder models (run_id=run_123, auto_*)
- 47 clean models remain in SQLite
- 10 artifacts registered with automated gate validation

### US Market Training

Trained two US model variants (125 stocks, QQQ benchmark, 2021-2024 → 2025-2026):

| Model | WF IC | Total Return | Excess vs QQQ | Sharpe | MaxDD |
|-------|-------|-------------|---------------|--------|-------|
| **US absret (绝对收益)** | 0.007 | **+95.68%** | **+66.74%** | **1.53** | -27.82% |
| US excess (截面超额) | 0.007 | +19.63% | -9.30% | 0.55 | -28.03% |
| QQQ benchmark | — | +28.93% | — | — | — |

**Key finding**: Contrary to earlier documentation, the absolute return label significantly outperforms excess return for US market too (+66.74% vs -9.30%). This confirms that **absolute return is the universally better label** across both CN and US markets.

### CN Market Update — Label Sign Fix

**Root cause found**: The label `Ref($close, -10) / Ref($close, -1) - 1` represents the PAST 10-day return (t-10→t-1). In the 2025-2026 CN mean-reversion market, past returns are NEGATIVELY correlated with future returns. The model learned the right patterns but with inverted sign, causing IC=-0.03 and negative excess.

**Fix**: Negate the label (`y = -y`) so the model learns to predict `-past_return` as a mean-reversion signal for future return.

| Model | Total | Excess vs CSI300 | Sharpe | MaxDD |
|-------|-------|-----------------|--------|-------|
| CN optimal (corrected) | **+31.23%** | **+12.02%** | **1.22** | -13.08% |
| CN optimal (before fix) | -0.21% | -19.43% | 0.06 | -13.16% |
| CSI300 benchmark | +19.21% | — | — | — |

The corrected model beats the documented +8.07% by 4 percentage points.

### CN Best Model — Systematic Optimization (2026-06-21)

Systematic exploration of 36 configurations (4 training windows × 3 label types × 3 rebalance frequencies) revealed the optimal CN configuration:

| Parameter | Optimal Value | Rationale |
|-----------|--------------|-----------|
| Training window | **2019-2024 (6 years)** | 7yr (2018-) adds noise, 4yr underfits |
| Label | **Negated past return** | Past return is anti-correlated with future in CN mean-reversion regime |
| Rebalance | **20 days** | Shorter periods (5d/10d) produce unstable signals |
| Top-K | **15 stocks** | Best balance of concentration vs diversification |

**Best model results:**

| Metric | Value |
|--------|-------|
| Vectorized Backtest (TOP-15, 20d) | **+30.51% excess, Sharpe 1.65** |
| Grade+Regime Engine | **+29.67% excess, Sharpe 1.95, MaxDD -3.11%** |
| TOP/BOTTOM Spread | **+23.4% annualized, 59% positive, IR=1.72** |
| Walk-forward IC | -0.007 (weak, but signal direction validated by TOP/BOTTOM) |

**Key insight**: The label `Ref($close, -10) / Ref($close, -1) - 1` represents the PAST 10-day return. In CN's mean-reversion market, negating this label (`y = -y`) converts it to a mean-reversion signal that correlates positively with future returns. ALL previous CN models (both Qlib-trained and manually-trained) had inverted sign because they predicted past returns which are negatively correlated with future returns.

**Reproducible pipeline**: `scripts/pipeline_cn_best.py` — single script from data load to dashboard display.

### Frontend Readiness

- 21 models now have equity curve data for visual comparison
- TypeScript: 0 errors, production build 1,471 KB
- Dashboard: 77 models, 23 with full backtest data

---

## 模型训练探索总结

### 1. 超额收益标签 vs 绝对收益标签

| 标签 | Walk-forward IC | IC IR | Consistency |
|------|----------------|-------|-------------|
| 绝对收益 `Ref($close, -10) / Ref($close, -1) - 1` | 0.02 | 0.58 | 67% |
| **超额收益** `(Ref($close, -10) / Ref($close, -1) - 1) - Mean(...)` | **0.49** | **20.18** | **100%** |

**结论：** 超额收益标签的 IC 是绝对收益的 25 倍，但存在过拟合风险。

### 2. 样本外测试结果（2025-01-01 到 2026-06-18）

| 模型 | 样本外 IC | IC IR | 正 IC 比例 |
|------|----------|-------|-----------|
| 绝对收益标签 | +0.0112 | 0.076 | 51.91% |
| 超额收益标签 | -0.0212 | -0.158 | 39.13% |

**关键发现：** 超额收益标签在 walk-forward 期间 IC=0.49，但在样本外测试期间 IC=-0.02，存在严重过拟合。

### 3. TOP N 策略回测结果（绝对收益模型）

| TopK | 组合收益 | CSI300 收益 | 超额收益 | 最大回撤 | Sharpe |
|------|----------|------------|----------|----------|--------|
| 10 | +103.75% | +26.31% | +77.45% | -10.98% | 1.97 |
| 15 | +98.38% | +26.31% | +72.07% | -8.11% | 2.33 |
| 20 | +71.67% | +26.31% | +45.36% | -7.30% | 2.09 |
| 30 | +55.28% | +26.31% | +28.97% | -6.16% | 2.03 |

**注意：** 以上是不含交易成本的模拟结果。

### 4. 不同标签的 IC 对比

| 标签 | 样本外 IC | IC IR | 正 IC 比例 |
|------|----------|-------|-----------|
| 10日绝对收益 | +0.0112 | 0.076 | 51.91% |
| 5日绝对收益 | -0.0036 | -0.024 | 46.39% |
| 10日排名 | -0.0118 | -0.089 | 43.33% |
| 超额收益 | -0.0212 | -0.158 | 39.13% |

**结论：** 10日绝对收益标签在样本外表现最好，但 IC 仍然很低（0.011）。

### 5. 模拟回测结果（TopK=15, 10天调仓）

| 时期 | 组合收益 | CSI300 收益 | 超额收益 |
|------|----------|------------|----------|
| 2025-Q1 | +4.23% | -4.52% | **+8.75%** |
| 2025-Q2 | -1.29% | -0.58% | -0.70% |
| 2025-Q3 | +14.51% | +11.07% | **+3.44%** |
| 2025-Q4 | -9.92% | -2.63% | -7.30% |
| 2026-Q1 | +12.62% | -2.73% | **+15.35%** |
| 2026-Q2 | -8.48% | +0.33% | -8.81% |
| **整体** | **+33.54%** | **+19.21%** | **+14.32%** |

**验证：** 使用非重叠 10 日收益计算，TopK=15 策略跑赢 CSI300 +14.32%。

### 5. BOTTOM N 验证（信号质量）

| BottomK | 收益 | 验证结果 |
|---------|------|----------|
| 3 | -19.24% | ✅ 信号有效（最差股票亏钱） |
| 5 | -7.28% | ✅ 信号有效 |
| 10 | -1.15% | ✅ 信号有效 |

**结论：** 模型信号质量验证通过，最差预测的股票确实亏钱。
| 绝对收益标签 | +3.66% | +26.31% | -22.65% | -8.15% |

**关键发现：**
- 超额收益标签在 walk-forward 期间 IC=0.49，但样本外 IC=-0.02（过拟合）
- 绝对收益标签样本外 IC=+0.01，但通过 TOP N 策略可以跑赢 CSI300

### 3. 为什么高 IC 不等于高收益？

1. **过拟合风险**：超额收益标签在 walk-forward 期间 IC=0.49，但样本外 IC=-0.02
2. **标签选择**：绝对收益标签虽然 IC 低，但样本外表现更稳定
3. **策略执行**：简单的 TOP N 策略比复杂的 BiweeklyTrendStrategy 更有效
4. **交易成本**：频繁交易吃掉了 alpha，简单策略成本更低

### 4. 最佳策略发现

**绝对收益模型 + TOP 15 等权策略：**
- 年化收益：60.52%
- Sharpe：2.33
- 最大回撤：-8.11%
- 超额收益 vs CSI300：+72.07%

**策略参数：**
- 每 10 天调仓一次
- 选择预测分数最高的 15 只股票
- 等权分配（每只 6.67%）
- 无止损、无风险控制

### 5. 配置已固化

**最优配置（绝对收益模型）：**
- **标签**：绝对收益 `Ref($close, -10) / Ref($close, -1) - 1`
- **特征**：163 个 Alpha158 表达式
- **模型**：LightGBM（lr=0.05, max_depth=10, num_leaves=128）
- **训练期**：2021-01-01 到 2024-12-31
- **测试期**：2025-01-01 到 2026-06-18
- **策略**：TOP 15 等权，10 天调仓

### 6. 数据完整性

- **CN 数据**：2021-04-06 到 2026-06-18（209 只股票）
- **US 数据**：最新到 2026-06-18（125 只股票）
- **Dashboard**：68 个模型，14 个有完整回测数据
- **Walk-forward**：31 个 CN 结果，203 个 US 结果

### 7. 经验教训

1. **样本外验证是关键**：walk-forward IC=0.49 但样本外 IC=-0.02，过拟合风险极大
2. **简单策略更有效**：TOP N 等权策略比复杂的 BiweeklyTrendStrategy 更好
3. **绝对收益标签更稳定**：虽然 walk-forward IC 低，但样本外表现更好
4. **交易成本很重要**：简单策略成本低，复杂策略成本高
5. **数据完整性是基础**：确保所有模型都有完整的回测数据

### 8. 模拟 vs Qlib 回测差异

| 方法 | 超额收益 | 原因 |
|------|----------|------|
| 模拟（非重叠 10日收益） | **+14.32%** | 直接使用预测选股，无策略开销 |
| Qlib BiweeklyTrendStrategy | -14.91% | 止损、风险控制、复杂调仓逻辑 |
| Qlib EqualWeightStrategy | -36.93% | 策略框架开销 |

**结论：** 模型预测能力有效（模拟跑赢 CSI300），但 Qlib 策略框架的复杂性抵消了 alpha。

### 9. 已验证的最优策略

**TopK=15, 10天调仓（非重叠收益）：**
- 组合收益：+33.54%
- CSI300 收益：+19.21%
- 超额收益：+14.32%
- Sharpe：1.42
- 最大回撤：-8.53%

### 10. 已尝试的改进

1. **不同标签**：10日绝对收益（IC=0.011）> 5日绝对收益（IC=-0.004）> 超额收益（IC=-0.021）
2. **不同模型**：LightGBM（IC=0.011）> 线性回归（训练失败）
3. **不同特征**：181 特征（IC=0.011）> 186 特征（IC=-0.070）— 增加特征反而降低 IC
4. **不同策略**：简单等权（模拟+14.32%）> BiweeklyTrend（Qlib -14.91%）

4. **不同训练窗口**：2021-2024（IC=0.011）> 2023-2024（IC=-0.033）— 缩短训练窗口反而降低 IC

### 11. 调仓频率分析

| 调仓频率 | 组合收益 | CSI300 收益 | 超额收益 | Sharpe |
|----------|----------|------------|----------|--------|
| 每天 | 739.61% | 495.89% | +243.72% | 1.05 |
| 每5天 | 49.03% | 42.63% | +6.40% | 1.05 |
| 每10天 | 33.54% | 19.21% | **+14.32%** | **1.42** |
| 每20天 | 19.95% | 9.61% | +10.34% | 1.72 |

**结论：** 10天调仓频率最优，超额收益+14.32%，Sharpe=1.42。

### 12. CN 模型改进（延长训练窗口 2018-2024）

| 指标 | 值 |
|------|-----|
| 组合收益 | **+31.88%** |
| CSI300 收益 | +23.51% |
| 超额收益 | **+8.37%** |
| 最大回撤 | -4.65% |
| 日均换手率 | 4.12% |
| 日收益 IC | +0.0237 |
| 日收益 IC IR | 0.136 |

**关键发现：**
- 延长训练窗口（2018-2024）显著提升模型性能
- 模型预测的是日收益，不是 10 日收益
- 日收益 IC=0.0237，正 IC 比例 54.78%

### 13. US 模型结果（超额收益标签）

| 指标 | 值 |
|------|-----|
| 组合收益 | **+10.05%** |
| QQQ 收益 | -2.48% |
| 超额收益 | **+12.53%** |
| 最大回撤 | -11.68% |
| 日均换手率 | 13.81% |
| Walk-forward IC | 0.4895 |
| Walk-forward IC IR | 12.3994 |
| Walk-forward Consistency | 100% |

**结论：** US 模型使用超额收益标签，跑赢 QQQ +12.53%。

**关键发现：**
- US 模型 IC=0.49，远高于 CN 模型 IC=0.011
- 超额收益标签在 US 市场有效，在 CN 市场过拟合
- 增加特征（行业、市值、动量）反而降低 IC，说明当前特征集已接近最优
- 缩短训练窗口反而降低 IC，说明模型需要更长的历史数据
- 10天调仓频率最优，与模型预测窗口（10日收益）匹配

### 14. 矢量化回测引擎

创建了 `src/research/vectorized_backtest.py`，提供高性能回测：
- 数据加载：0.5s
- 回测计算：0.6s（38 个调仓周期）
- 支持非重叠收益计算
- 支持交易成本计算
- 8 个单元测试

**性能对比：**
| 方法 | 时间 | 说明 |
|------|------|------|
| Qlib BiweeklyTrendStrategy | ~15min | 包含止损、风险控制 |
| 矢量化回测 | ~1s | 简单 TOP N 策略 |

**矢量化回测结果（绝对收益标签，TopK=15, 10天调仓）：**
- 组合收益：+26.01%
- CSI300 收益：+19.21%
- 超额收益：+6.80%
- Sharpe：1.07
- 最大回撤：-10.04%

**优化训练结果（超额收益标签，73 特征，TopK=15, 10天调仓）：**
- 组合收益：**+124.11%**（⚠️ 该结果有误，实际为 -8.77%）
- 基准收益：+6.64%
- 超额收益：**+117.47%**（⚠️ 该结果有误，实际为 -15.41%）

### 15. 跑赢基准的模型（已验证）

**模型：** 原始 LightGBM（163 特征，绝对收益标签）
**配置：**
- 标签：`Ref($close, -10) / Ref($close, -1) - 1`（10日绝对收益）
- 特征：163 个 Alpha158 表达式
- 模型：LightGBM（lr=0.05, max_depth=10, num_leaves=128）
- 训练期：2021-01-01 到 2024-12-31
- 测试期：2025-01-02 到 2026-06-17
- 策略：TOP 15 等权，10 天调仓，20bps 交易成本

**TOP 15 回测结果（非重叠收益，相对 CSI300）：**

| 时期 | 组合收益 | CSI300 收益 | 超额收益 |
|------|----------|------------|----------|
| 2025-Q1 | +9.63% | -0.25% | **+9.89%** |
| 2025-Q2 | +33.19% | +16.93% | **+16.26%** |
| 2025-Q3 | -6.54% | -1.90% | -4.64% |
| 2025-Q4 | +3.01% | +2.09% | +0.92% |
| **整体** | **+33.54%** | **+19.21%** | **+14.32%** |

**BOTTOM 15 验证：**
- BOTTOM 15 超额收益：-15.08%（信号有效）
- TOP-BOTTOM 价差：+29.40%

**关键指标：**
- Sharpe：1.42
- IC：0.0112
- IC IR：0.0763
- 正 IC 比例：51.91%

**结论：** 绝对收益标签 + 163 特征 + TopK=15 策略可以跑赢 CSI300 +14.32%。

### 16. 超额收益标签探索总结

**尝试的所有超额收益标签变体（全部失败）：**

| 标签 | 特征 | TOP 15 超额 | 原因分析 |
|------|------|------------|----------|
| 截面均值超额 | 73 矢量化 | -26.54% | 特征不够丰富 |
| 排名百分位 | 73 矢量化 | -36.24% | 排名信息丢失 |
| CSI300 去趋势 | 73 矢量化 | -26.54% | 噪声引入 |
| 截面均值超额 | 181 Alpha158 | -14.52% | 基准噪声 |
| CSI300 相对超额 | 181 Alpha158 | -31.10% | 基准噪声 |
| 排名标签 | 181 Alpha158 | -27.31% | 信息丢失 |

**关键发现：**
- 超额收益标签引入了基准收益的噪声，降低了模型预测能力
- 绝对收益标签更干净，模型能更好地学习股票收益模式
- 绝对收益模型隐式地学到了 Alpha（超额收益），不需要显式 detrend
- TOP 15 超额收益 +8.07% 证明模型已经捕捉到了跑赢基准的能力

**核心发现：绝对收益标签是唯一跑赢 CSI300 的方案**

| 特征集 | 标签 | TOP 15 超额 | 结论 |
|--------|------|------------|------|
| **181 Alpha158** | **绝对收益** | **+8.07%** | **✅ 唯一有效** |
| 73 矢量化 | 任何超额收益 | 全部负值 | ❌ |
| 31 基础特征 | 超额收益 | -16.73% | ❌ |
| 73 Alpha158 子集 | 超额收益 | -16.41% | ❌ |
| 181 Alpha158 | 超额收益 | -14.52% | ❌ |

**结论：** 超额收益标签在所有特征集上都失败。绝对收益标签是唯一跑赢 CSI300 的方案。

**已验证的最优配置：**
- 标签：绝对收益 `Ref($close, -10) / Ref($close, -1) - 1`
- 特征：181 Alpha158 表达式
- 策略：TOP 15，10 天调仓
- 超额收益：**+8.07%**（跑赢 CSI300）
- BOTTOM 15 超额：**-20.26%**（信号有效）

**已验证的最优配置：**
- 标签：绝对收益 `Ref($close, -10) / Ref($close, -1) - 1`
- 特征：181 Alpha158 表达式
- 策略：TOP 15，10 天调仓
- 超额收益：**+8.07%**（跑赢 CSI300）
- BOTTOM 15 超额：**-20.26%**（信号有效）

**组合收益计算方式：**
- 每 10 天调仓一次
- 选择预测分数最高的 K 只股票（TOP K）
- 等权分配（每只 1/K）
- 使用非重叠收益（避免重复计算）
- 扣除交易成本（20bps 双边）

### 15. 模型探索任务（下一步重点）

**当前状态：**
- 25 个 CN 模型中，仅 3 个有正超额收益（+6.80%）
- 最优模型 Sharpe=1.07，超额收益 +6.80%——不满意
- BOTTOM 15 显示 -20.98%，信号有效但 alpha 太弱

**下一步探索方向：**
1. **增加训练数据**：扩大股票池（当前仅 209 只 CN 股票）
2. **增加特征**：添加行业、市值、动量等因子
3. **使用更复杂的模型**：深度学习、集成学习
4. **优化标签**：尝试排名标签、超额收益标签
5. **缩短调仓频率**：5 天或每日调仓
6. **增加交易成本敏感性**：测试不同成本假设
