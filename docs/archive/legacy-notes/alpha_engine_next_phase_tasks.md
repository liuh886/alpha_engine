# AlphaEngine 下一阶段任务清单

> 基于 2026-06-08 审计结果生成
> 当前状态：四个核心问题基础设施 80-90% 完成，剩余差距集中在集成和产品化

---

## 前置说明

上一阶段（6月7日）解决了三个 P0 问题：
- ✅ Agent 调用真实归因引擎（不再是 stub）
- ✅ Walk-forward 硬门控（阻止不达标模型晋级）
- ✅ 统一实验记忆系统（ExperimentJournal）

当前系统的 5,518 行核心代码覆盖了因子发现、归因、记忆、防过拟合的基础设施。
下一阶段的目标是：**让系统从"模块可工作"变成"端到端可跑通"。**

---

## Sprint 1：端到端验证（1-2 天）

### T-01：完整的 Agent 循环冒烟测试

**目标**：验证 agent 能通过 MCP 完成完整的研究闭环

**验收标准**：
1. 通过 MCP 调用 `define_factor` 注册一个新因子（如 5 日动量）
2. 通过 `evaluate_factor` 获取 IC/ICIR/t-stat
3. 通过 `validate_factor` 触发晋级流程
4. 通过 `compile_strategy_with_factors` 将 Active 因子编译为策略 YAML
5. 通过 `run_backtest` 执行回测
6. 通过 `attribute_factor_returns` 查看归因
7. 通过 `query_experiments` 确认实验被记录
8. 全程无人工干预，记录每步的输入/输出/耗时

**风险**：依赖 Qlib 数据管线可用性。如果数据未就绪，需要先跑 `update_market_data`。

**估时**：1 天

---

### T-02：数据库初始化验证

**目标**：确认 `factor_registry.db` 和相关 SQLite 库在首次使用时正确创建

**验收标准**：
1. 删除 `artifacts/factor_registry.db`（如果存在）
2. 调用 `define_factor` → 确认 db 自动创建，表结构正确
3. 调用 `evaluate_factor` → 确认 validation 记录写入
4. 调用 `query_experiments` "summary" → 确认统计正确
5. 重启服务后数据不丢失

**估时**：0.5 天

---

## Sprint 2：补齐关键差距（3-5 天）

### T-03：因子去重机制

**目标**：防止 agent 重复注册相同的因子表达式

**当前问题**：`FactorRegistry` 没有检查表达式唯一性，同一因子可以被注册多次

**验收标准**：
1. `define_factor` 检查表达式是否已存在
2. 已存在 → 返回已有因子的信息（不重复创建）
3. 新增 API：`GET /api/factors/exists?expression=...`
4. MCP 工具返回明确提示："该因子已存在，ID=X，当前阶段=Y"

**估时**：0.5 天

---

### T-04：模型级多重检验校正

**目标**：当 agent 跑多个模型配置时，对模型表现进行多重检验校正

**当前问题**：FDR 校正只在因子扫描层（FactorScanner），不在模型层

**验收标准**：
1. 新增 `ModelBatchValidator` 类
2. 输入：多个模型的回测结果
3. 输出：BH FDR 校正后的显著性判定
4. 集成到 promotion gate：批量实验中只有 FDR 校正通过的模型可晋级
5. MCP 工具：`validate_model_batch`

**估时**：1.5 天

---

### T-05：时变归因（Rolling Attribution）

**目标**：归因结果不只是全周期平均，而是按时间窗口滚动

**当前问题**：`FactorAttribution` 用全周期 OLS，看不到因子贡献随时间的变化

**验收标准**：
1. `FactorAttribution` 新增 `rolling_attribution(window_months=6)` 方法
2. 输出每个时间窗口的因子贡献变化
3. 识别因子贡献衰减趋势（如"动量因子贡献从 40% 降到 10%"）
4. MCP 工具参数新增 `rolling_window` 可选参数
5. 返回结构包含时间序列数据，供 Dashboard 绘图

**估时**：1.5 天

---

### T-06：扩展因子扫描池

**目标**：将硬编码的 16 个因子扩展为可配置的因子池

**当前问题**：`factor_scanner.py` 的 16 个因子写死在 Python 列表里

**验收标准**：
1. 因子池配置外部化为 `configs/factor_pool.yaml`
2. 支持按类别（momentum/volume/volatility/mean_reversion/value/quality）组织
3. `FactorScanner` 从 YAML 加载因子池
4. Agent 可通过 MCP `define_factor` 自定义新因子并加入池
5. 保留现有 16 个因子作为默认池

**估时**：1 天

---

## Sprint 3：Agent 自主循环能力（1 周）

### T-07：Agent 自动迭代逻辑

**目标**：agent 能根据实验结果自动决定下一步

**当前问题**：agent 能执行单次实验，但不会根据结果自动迭代

**验收标准**：
1. `ResearchAssistant` 新增 `run_research_loop(goal, max_iterations=20)` 方法
2. 循环逻辑：
   - 查询 `ExperimentJournal` 了解历史
   - 根据 `what_failed()` 避免重复失败路径
   - 提出新假设 → 构造因子 → 检验 → 入库
   - 达到 max_iterations 或找到 VALIDATED 因子时停止
3. 每次迭代记录到实验日志
4. 返回结构化报告：尝试了什么、发现了什么、失败了什么
5. MCP 工具：`run_research_loop`

**估时**：3 天

---

### T-08：自然语言研究目标解析

**目标**：用户用自然语言描述研究目标，agent 解析为结构化任务

**当前问题**：`StrategyCompilerService` 只处理策略参数的 NL，不处理研究目标

**验收标准**：
1. 新增 `ResearchGoalParser` 类
2. 输入："帮我找一个在 A 股高波动环境下还能赚钱的策略，回撤别超过 15%"
3. 输出结构化 goal：
   ```json
   {
     "market": "cn",
     "regime_filter": "high_volatility",
     "target": {"max_drawdown": 0.15, "min_sharpe": 1.0},
     "suggested_factor_families": ["low_volatility", "quality", "defensive"]
   }
   ```
4. 支持中英文输入
5. 与 `run_research_loop` 集成

**估时**：2 天

---

## Sprint 4：Dashboard 产品化（1 周）

### T-09：因子库页面

**目标**：Dashboard 新增因子库浏览页面

**验收标准**：
1. 列表页：所有因子的名称、类别、阶段、IC、创建日期
2. 筛选：按阶段（Proposed/Candidate/Validated/Active/Deprecated）
3. 排序：按 IC、ICIR、创建日期
4. 详情页：因子完整历史（验证记录、使用记录、归因贡献）
5. 表达式可读展示（不是原始 Qlib 语法）

**估时**：2 天

---

### T-10：归因可视化页面

**目标**：Dashboard 新增归因分析页面

**验收标准**：
1. 因子贡献饼图（哪个因子贡献了多少收益）
2. 因子风险贡献柱状图
3. 时变归因折线图（如果 T-05 完成）
4. 归因 R² 展示（模型解释了多少收益）
5. 与基准（QQQ/沪深300）的对比

**估时**：2 天

---

### T-11：实验日志页面

**目标**：Dashboard 新增实验日志页面，让人类能看到 agent 在做什么

**验收标准**：
1. 实验列表：时间、类型、状态、结果
2. 筛选：按类型（factor/model/walk_forward）、按状态（success/fail）
3. 搜索：通过 `search_experiments` API
4. 失败实验的失败原因展示
5. 与 `ExperimentJournal` REST API 对接

**估时**：1.5 天

---

## 优先级总览

| 优先级 | 任务 | 估时 | 依赖 | 价值 |
|--------|------|------|------|------|
| **P0** | T-01 端到端冒烟测试 | 1d | 无 | 验证系统是否真的能跑通 |
| **P0** | T-02 数据库初始化验证 | 0.5d | 无 | 基础可靠性 |
| **P1** | T-03 因子去重 | 0.5d | T-01 | 防止实验污染 |
| **P1** | T-06 因子池外部化 | 1d | T-01 | 解锁 agent 自定义因子 |
| **P1** | T-04 模型级 FDR | 1.5d | T-01 | 防过拟合最后一环 |
| **P2** | T-05 时变归因 | 1.5d | 无 | 归因深度提升 |
| **P2** | T-07 Agent 自动迭代 | 3d | T-01,T-03 | 核心 agent-native 能力 |
| **P2** | T-08 NL 研究目标解析 | 2d | T-07 | 人机交互入口 |
| **P3** | T-09 因子库页面 | 2d | T-06 | 人类审查层 |
| **P3** | T-10 归因可视化 | 2d | T-05 | 人类理解层 |
| **P3** | T-11 实验日志页面 | 1.5d | 无 | Agent 透明度 |

**总估时：约 17 人天（3.5 周）**

---

## 建议执行顺序

```
Week 1:  T-01 → T-02 → T-03 → T-06（端到端验证 + 基础补齐）
Week 2:  T-04 → T-05 → T-07（防过拟合 + Agent 循环）
Week 3:  T-08 → T-09 → T-10 → T-11（NL 入口 + Dashboard）
```

**T-01（端到端冒烟测试）是所有后续任务的前提。** 如果冒烟测试发现管线不通，后面的任务都没有意义。

---

## 一句话 Goal（给编程 Agent）

如果只能给编程 agent 下达一个 goal 来推动下一阶段：

**「跑通一次完整的端到端流程：通过 MCP 注册一个新因子 → 检验 → 入库 → 编译策略 → 回测 → 归因 → 确认实验被记录，修复过程中发现的所有阻塞问题。」**
