# AlphaEngine 代码复查报告 — 对照检验清单

**日期**: 2026-06-17
**基线**: 检验分析报告 (2026-06-17)
**结论**: **14 项任务中 7 项已实现，2 项部分实现，5 项未实现**

---

## 总览

| 原任务 | 当前状态 | 变化 |
|:-------|:---------|:-----|
| T1.1 策略推荐接口 | ✅ 已实现 | 新增 `_recommend_strategy()` + API 层推荐 |
| T1.2 组合级决策接口 | ⚠️ 批量但非组合 | 新增 `POST /portfolio/analysis`，但缺少集中度/一致性分析 |
| T1.3 信号历史与趋势 | ✅ 已实现 | SQLite 持久化 + GET/POST history 接口 |
| T1.4 买卖价位标注 | ✅ 已实现 | `PriceTargets` dataclass + ATR 动态计算 |
| T2.1 导航重构 | ✅ 已实现 | 4 组英文分组 (Core/Research/Strategy/System) |
| T2.2 StockTerminal v2 | ⚠️ 部分实现 | 策略推荐面板 ✅、价位展示 ✅、但图表无信号标注 |
| T2.3 Watchlist 增强 | ❌ 未实现 | 仍为基础 6 列表格 |
| T2.4 策略页面升级 | ❌ 未实现 | 仍为 YAML 编辑器 |
| T2.5 数据新鲜度指示器 | ✅ 已实现 | GlobalStatusBar 显示数据年龄 + 黄色警告 |
| T3.1 端到端集成测试 | ❌ 未实现 | 无 HTTP 级 /decision 端点测试 |
| T3.2 模型健康检查 | ⚠️ 部分实现 | 独立端点存在，但 decision 端点内未集成 |
| T3.3 策略间一致性测试 | ❌ 未实现 | 仅有单策略一致性（引擎 vs BiweeklyTrend） |
| T3.4 Walk-Forward 修复 | ✅ 已实现 | 非 None IC 过滤、零值保护、状态字段 |
| T4.3 IC 评估修复 | ❌ 未实现 | 无 clamp/winsorize/异常检测 |

---

## 逐项详细评估

### ✅ T1.1 — 策略推荐接口（已实现）

**证据**:
- `StockDecisionEngine._recommend_strategy()` — 基于动量 z-score、因子数量、波动率状态、信号类型从 3 个策略中选择
- `StockDecision` 包含 `recommended_strategy` 字段 (name, display_name, reason, confidence)
- `GET /{symbol}/decision` 响应中自动包含推荐

**质量评估**: 推荐逻辑是基于规则的启发式（非 ML），覆盖了全部 3 个注册策略。合理但不可配置。

**遗留问题**: 推荐仅在 BUY 信号时展示（前端），HOLD/SELL 时隐藏了推荐面板。

---

### ⚠️ T1.2 — 组合级决策接口（批量但非组合）

**证据**:
- `POST /portfolio/analysis` 已存在，接受 `symbols: list[str]`
- 逐标的调用 `engine.evaluate()`，返回统计 (BUY/HOLD/SELL 计数)

**缺失**:
- ❌ 板块集中度分析（同行业 > 40% 警告）
- ❌ 信号一致性评分
- ❌ 跨标的相关性提示

**评价**: 当前是"并行单股评估"，不是真正的"组合分析"。组合层面的洞察完全缺失。

---

### ✅ T1.3 — 信号历史与趋势（已实现）

**证据**:
- `_SignalHistoryStore` 类 + SQLite 表 `signal_history`
- 字段：symbol, market, signal, confidence, score, rank, price_targets, recommended_strategy, recorded_at
- `GET /{symbol}/history?days=30` 检索历史
- `POST /{symbol}/record` 执行评估并记录

**质量评估**: 存储和检索链路完整。但缺少：
- ❌ 信号变动检测（今天信号是否与昨天不同？）
- ❌ 趋势判定（信号强度是在增强还是衰减？）
- ❌ 自动记录（需手动调 POST record，无 cron 自动触发）

---

### ✅ T1.4 — 买卖价位标注（已实现）

**证据**:
- `PriceTargets` dataclass：current_price, buy_range_low/high, stop_loss_price, target_price, atr_20, support, resistance
- `_compute_price_targets()` 使用 ATR 动态计算：
  - BUY: 入场区间 = MA20 ± 0.5×ATR, 止损 = close - 2×ATR, 目标 = close + 3×ATR
  - SELL: 止损 = 当前价
  - HOLD: 参考价 = MA20 - 2×ATR

**遗留问题**:
- support/resistance 字段已定义但前端未渲染
- 价位仅在 BUY 信号时显示，SELL 时不展示（前端逻辑限制）
- 无止盈机制

---

### ✅ T2.1 — 导航信息架构重构（已实现，英文标签）

**证据**:
- `Sidebar.tsx` 已分 4 组：Core (3), Research (6), Strategy (3), System (4)
- 分组逻辑合理

**遗留问题**:
- 标签为英文，非中文（取决于国际化策略，可能是刻意选择）
- Research 组有 6 项，略显拥挤

---

### ⚠️ T2.2 — StockTerminal 重构（部分实现）

**已实现**:
- ✅ 策略推荐面板（BUY 信号时显示 recommended_strategy）
- ✅ 价位展示（buy_range, stop_loss, target, ATR）
- ✅ Market 切换：Watchlist 视图有 US/CN 按钮，个股分析自动检测后缀
- ✅ 因子展示有 z-score 颜色编码（|z| > 2 红/绿）

**未实现**:
- ❌ K 线图上无买卖信号标注（无 addMarker / createPriceLine）
- ❌ 无最近搜索快捷标签
- ❌ 因子面板无自然语言解读（仅 raw 数值）
- ❌ 护栏面板未做折叠优化（失败项未突出）

---

### ❌ T2.3 — Watchlist 增强（未实现）

**现状**: `WatchlistItem` 接口仅有 6 字段：
```typescript
symbol, signal, confidence, score, rank, risk_flags
```

**缺失**:
- ❌ 当前价格
- ❌ 日涨跌幅
- ❌ 信号持续天数
- ❌ 推荐策略
- ❌ 信号变动视图
- ❌ 批量选择/导出

---

### ❌ T2.4 — 策略页面升级（未实现）

**现状**: `StrategyPage.tsx` 仍然是纯 YAML 编辑器：
- 选择文件 → 显示 YAML → 编辑 → 保存
- 无策略绩效卡片、无回测曲线、无持仓展示、无交易记录

---

### ✅ T2.5 — 数据新鲜度指示器（已实现）

**证据**:
- `GlobalStatusBar.tsx` 含 `formatAge()` 函数
- 显示 "Data: Xm ago" / "Xh ago" / "Xd ago"
- 数据 > 2 天 → 黄色警告
- 显示 `latestCalendarDay`

**遗留问题**:
- 无模型训练日期显示
- 无红色警告阈值（> 7 天）
- 个股页无独立数据截止日期

---

### ❌ T3.1 — 端到端集成测试（未实现）

**现状**:
- `test_decision_integration.py` 测试引擎类级别（459 行，12 测试用例），**不是 HTTP 级**
- 无任何测试调用 `GET /api/stock-analysis/{symbol}/decision` 通过 FastAPI TestClient
- 前端仅 3 个测试文件（format、ErrorBoundary、Skeleton），21 个用例，无页面级测试

---

### ⚠️ T3.2 — 模型健康检查（部分实现）

**已实现**:
- `GET /data/freshness` 独立端点 — 检查 Qlib 数据年龄 (> 3天 warn) 和 pred.pkl 年龄 (> 7天 warn)
- `GET /models/health` 独立端点 — 检查推荐模型年龄 (> 14天 warn)

**缺失**:
- ❌ `GET /{symbol}/decision` 内部**不检查**模型陈旧性 — 盲目加载任意年龄的预测
- ❌ 决策响应中无 `stale_model: true` 警告字段
- ❌ pred.pkl 缺失时不降级到纯技术分析，而是 500 错误

---

### ❌ T3.3 — 策略间信号一致性测试（未实现）

**现状**: `TestDecisionConsistency` 仅对比决策引擎 vs BiweeklyTrendStrategy 的卖出规则一致性（5 个测试用例）。

**缺失**:
- ❌ 多策略对同一标的的信号比较
- ❌ 一致率统计
- ❌ 信号分歧自动标记

---

### ✅ T3.4 — Walk-Forward 修复（已实现）

**证据**:
- `SplitResult` 增加 `status` 字段（"success"/"failed"/"skipped"）
- `aggregate()` 过滤仅用成功且非 None 的 IC
- `_compute_ic()` 有 5 样本最低要求 + 零标准差保护
- IC_IR 有 `std > 1e-12` 除零保护

**遗留**: 单元测试用合成数据验证数学正确性，但无实盘数据的端到端验证证据。

---

### ❌ T4.3 — IC 评估修复（未实现）

**现状**: `factor_evaluator.py` 中的 IC 计算路径：
- 使用 `CSZScoreNorm` 跨截面标准化 → Pearson/Spearman 相关
- 无 `np.clip`、无 winsorize、无 max-IC 阈值
- 代码注释承认"small stock universe (118 stocks)"但未修正
- Gate 阈值 (`min_icir: 0.3`) 校准于预期 IC 水平，可能掩盖膨胀值

---

## 重新修订的任务清单

基于复查结果，以下任务仍需完成或改进：

### 🔴 高优先级（阻塞性）

| ID | 任务 | 类型 | 说明 |
|:---|:-----|:-----|:-----|
| **R1** | Decision 端点内集成模型陈旧性检查 | 后端 | 当前 /decision 盲目加载预测，应在响应中注入 staleness 警告 |
| **R2** | K 线图信号标注 | 前端 | 用 lightweight-charts 的 addMarker + createPriceLine 在图上标注买卖点和价位 |
| **R3** | Watchlist 增强 | 前端 | 增加价格、涨跌幅、信号天数、推荐策略列 |
| **R4** | IC 膨胀修正 | 后端 | 添加 winsorize 或 clip 机制，小宇宙偏差修正 |

### 🟡 中优先级（体验改善）

| ID | 任务 | 类型 | 说明 |
|:---|:-----|:-----|:-----|
| **R5** | 组合分析增强 | 后端 | 在 batch 评估基础上增加板块集中度和信号一致性评分 |
| **R6** | 策略页面升级 | 前端 | 从 YAML 编辑器升级为含绩效卡片的策略全景视图 |
| **R7** | HTTP 级集成测试 | 测试 | 用 TestClient 测试 /decision、/watchlist/summary、/portfolio/analysis |
| **R8** | 信号历史自动化 | 后端 | cron 定时触发 record，增加信号变动检测和趋势判定 |
| **R9** | 价位展示扩展 | 前端 | SELL 信号也显示价位；渲染 support/resistance；K 线上叠加价位线 |

### 🟢 低优先级（长期质量）

| ID | 任务 | 类型 | 说明 |
|:---|:-----|:-----|:-----|
| **R10** | 多策略一致性测试 | 测试 | 对同一标的跑全部策略，统计一致率 |
| **R11** | 模型降级兜底 | 后端 | pred.pkl 缺失时降级到纯技术分析信号而非 500 |
| **R12** | 前端页面级测试 | 测试 | StockTerminal 核心流程的 Vitest + RTL 测试 |
| **R13** | Walk-Forward 实盘验证 | 后端 | 用真实数据跑一次 walk-forward，确认指标非零且合理 |
| **R14** | 因子自然语言解读 | 前端 | StockTerminal 因子面板增加 z-score 含义的文本解释 |

---

## 进度量化

| 类别 | 已完成 | 部分 | 未完成 | 完成率 |
|:-----|:------|:-----|:-------|:-------|
| 后端能力 (T1.x + T3.x) | 4 | 2 | 2 | 50% |
| 前端体验 (T2.x) | 3 | 1 | 2 | 50% |
| 工程质量 (T3.1-T3.4) | 1 | 1 | 2 | 25% |
| **总体** | **8** | **4** | **6** | **44%** |

> 原始 14 项中 8 项有实质性进展，后端能力推进最快，工程质量缺口最大。
