# AlphaEngine 严格审计报告

> 审计时间：2026-06-09
> 审计方法：直接读取数据库、产物文件、代码，不依赖 Agent 自述

---

## 一、核心问题修复验证

### 1. Alembic 迁移错误 ✅ 已修复

**证据**：
```
engine_state.db → workflow.rebacktest.us
  2026-06-08 07:00  FAILURE  "Can't locate revision identified by '7d34483879f0'"
  2026-06-09 11:33  SUCCESS  run_id=472692644cd84b71b997fc294f929e1b
```

Rebacktest 管线已能正常运行，不再因 Alembic 迁移版本不匹配而崩溃。

### 2. 因子注册库 ✅ 可用

**数据**：
- 74 个因子入库（9 Active + 65 Proposed）
- 10 次验证记录，9 次使用记录
- 因子编译器成功生成 `us_lgbm_workflow_with_factors_us_20260609.yaml`（含 8 个 Active 因子）

**晋级门控在工作**：`mean_reversion_price_ma_ratio_5` IC=0.036, ICIR=0.30, t=2.2 → 被正确判为 `passed=0`（未晋级）。

### 3. 因子编译 → 回测管线 ✅ 可运行

编译器成功将 Active 因子注入 Qlib workflow YAML，回测管线成功执行（SUCCESS 状态）。

---

## 二、五个关键问题

### 🔴 问题 1：Walk-Forward 产出零指标（最严重）

**现象**：最新的 walk-forward 结果（2026-06-08）所有 split 的 IC=0.0，Sharpe=null。

```json
// 4 个 split 全部如此：
{ "split_id": 0, "ic": 0.0, "rank_ic": 0.0, "sharpe": null, "max_drawdown": null, "annual_return": null }
{ "split_id": 1, "ic": 0.0, "rank_ic": 0.0, "sharpe": null, ... }
{ "split_id": 2, "ic": 0.0, "rank_ic": 0.0, "sharpe": null, ... }
{ "split_id": 3, "ic": 0.0, "rank_ic": 0.0, "sharpe": null, ... }
```

**影响**：VALIDATED 晋级要求 walk-forward 通过，但 walk-forward 管线无法产出任何有效指标。**整个三级晋级体系的第二级是瘫痪的。**

**根因推测**：walk-forward 管线可能在每个 split 内没有正确训练模型或计算预测值。需要检查 `walk_forward.py` 中 split 训练/预测逻辑是否真的在执行。

---

### 🔴 问题 2：IC 值异常偏高

**现象**：9 个 Active 因子的 IC 值：

| 因子 | IC | ICIR | t-stat |
|------|------|------|--------|
| mom_5d | 0.71 | 6.72 | 50.7 |
| mom_10d | 0.68 | 6.21 | 46.9 |
| mean_reversion_price_ma_ratio_10 | 0.69 | 5.82 | 43.9 |
| composite_vol_adj_mom_5 | 0.63 | 6.40 | 48.4 |
| mean_reversion_ma_dev_10 | 0.59 | 5.48 | 41.4 |
| momentum_ret_5 | 0.55 | 4.44 | 33.5 |
| sharpe_20 | 0.60 | 5.13 | 38.7 |
| corr_cv_20 | 0.37 | 2.75 | 20.7 |
| mean_reversion_ma_dev_5 | 0.19 | 1.42 | 10.7 |

**正常范围**（学术/行业标准）：IC = 0.02-0.05, ICIR = 0.3-0.7, t-stat = 2-5

**我们的值**：IC 是正常值的 10-30 倍，t-stat 是正常值的 10 倍。

**可能原因**：
1. **样本内评估**：IC 在训练数据上计算，没有做样本外切割
2. **数据泄露**：未来数据泄漏到特征计算中
3. **股票池太小**：当前 watchlist 可能只有 118 只 US 股票，横截面太窄导致虚假高相关
4. **生存偏差**：watchlist 只包含"好股票"（如 QQQ 成分股）

**如果 IC 是真实的**，我们早就有亿万富翁级别的 Alpha 了。所以**这几乎肯定是评估方法的问题**，不是真正的 Alpha。

---

### 🟡 问题 3：回测成功但无输出

**现象**：rebacktest 报告 SUCCESS，但：
- mlflow.db：表为空（0 表）
- metadata.db：表为空（0 表）
- artifacts/backtest/ 目录不存在
- 无新的权益曲线 CSV 或回测报告

**影响**：回测管线虽然不报错了，但产出物可能没有被正确保存。我们需要验证回测是否真的产生了有意义的结果，还是只是"没有崩溃就报 SUCCESS"。

---

### 🟡 问题 4：因子 IC 衰减追踪为空

**现象**：`artifacts/factor_ic/` 目录为空。系统声明有衰减检测能力（`mean_decay_1d`, `mean_decay_5d`），但没有持久化衰减时间序列。

**影响**：无法回答"这个因子的 Alpha 是否在衰减？" — 这是因子生命周期管理的核心问题。

---

### 🟡 问题 5：Agent 循环未真正闭环

**现象**：`agent_thought_stream.json` 显示：
```
"Target hyperparameters proposed for 0 active factors: lr=0.08, max_depth=7"
```

系统有 9 个 Active 因子，但 agent 在计算超参时认为有 0 个。说明 agent 循环的某些步骤加载了陈旧的状态，没有读取最新的因子注册库。

---

## 三、系统状态总结

| 层级 | 状态 | 说明 |
|------|------|------|
| **基础设施** | ✅ 可用 | DB 创建、迁移、MCP 接口正常 |
| **因子注册** | ✅ 可用 | 74 因子，去重、晋级门控工作 |
| **因子编译** | ✅ 可用 | YAML 生成、回测注入正常 |
| **回测执行** | ⚠️ 形式通过 | 不崩溃，但产出物缺失 |
| **Walk-Forward** | ❌ 瘫痪 | 零指标，无法支撑晋级判定 |
| **IC 评估** | ❌ 不可信 | IC 异常高，评估方法需审计 |
| **归因分析** | ✅ 代码存在 | 未审计实际执行结果 |
| **Agent 闭环** | ⚠️ 部分 | 状态不同步，未完成完整迭代 |
| **Dashboard** | ✅ 代码存在 | 4 个新页面已实现 |

**一句话结论：基础设施 80% 可用，但核心验证管线（walk-forward + IC 评估）存在严重问题，系统目前无法产出可信的 Alpha 判定。**

---

## 四、下一阶段开发目标

### 战略定位：从"能跑"到"能信"

上一阶段解决了"系统不崩溃"。下一阶段的核心问题是：**系统产出的结果能不能信任？**

---

### P0：修复验证管线（1 周）

#### T-01：Walk-Forward 指标修复
- **目标**：walk-forward 每个 split 产出真实的 IC、Sharpe、最大回撤
- **方法**：审计 `walk_forward.py` 中的 split 训练→预测→评估逻辑，确保每个 split 真正训练了模型
- **验收**：4 个 split 的 IC 不全为 0，Sharpe 不全为 null
- **估时**：2 天

#### T-02：IC 评估方法审计与修复
- **目标**：IC 值回到合理范围（0.02-0.10）
- **方法**：
  1. 确认 `factor_evaluator.py` 使用的是**样本外** IC 计算（train/test 分割）
  2. 检查因子表达式是否存在未来数据泄漏（如 `$close` 在 t 日是否包含了 t+1 的信息）
  3. 确认 Qlib 数据管线的时间对齐正确
- **验收**：Active 因子的 IC 在 0.03-0.15 范围内
- **估时**：3 天
- **这是整个系统可信度的基石。IC 不可信 = 整个系统不可信。**

#### T-03：回测产出物验证
- **目标**：回测 SUCCESS 意味着"真的跑出了权益曲线和指标"
- **方法**：在 rebacktest 管线中增加产出物检查，确认 CSV/JSON 权益曲线文件存在且非空
- **验收**：回测 SUCCESS 后能在 artifacts/ 中找到权益曲线和指标文件
- **估时**：1 天

---

### P1：构建可信的端到端闭环（1-2 周）

#### T-04：端到端冒烟测试（带真实验证）
- **目标**：MCP 调用完整链路：`define_factor → evaluate_factor → validate_factor → compile_strategy → run_backtest → attribute_factor_returns → query_experiments`
- **验收**：每一步有真实输出，最终 backtest 结果有权益曲线和绩效指标
- **估时**：1 天

#### T-05：因子 IC 衰减追踪
- **目标**：持久化每个 Active 因子的 IC 时间序列，支持衰减检测
- **方法**：在 `FactorEvaluator` 中增加 `track_ic_over_time()` 方法，按月/季度滚动计算 IC，写入 `factor_ic/` 目录
- **验收**：每个 Active 因子有完整的 IC 时间序列，Dashboard 可展示
- **估时**：1.5 天

#### T-06：Agent 状态同步修复
- **目标**：Agent 循环的每一步都能读取最新的因子注册库和系统状态
- **方法**：在 `research_loop.py` 的 `run_research_cycle()` 开始时强制刷新因子状态
- **验收**：agent_thought_stream 不再出现 "0 active factors" 的误判
- **估时**：0.5 天

---

### P2：因子发现质量提升（2 周）

#### T-07：扩大股票池并验证
- **目标**：将 watchlist 从 ~118 只扩大到至少 S&P 500，验证 IC 值是否仍然显著
- **影响**：如果扩大后 IC 大幅下降，说明之前的高 IC 是小样本/生存偏差造成的
- **估时**：2 天

#### T-08：样本外 IC 硬门控
- **目标**：因子评估必须使用 OOS（Out-of-Sample）IC，不是全样本 IC
- **方法**：`FactorEvaluator` 增加 train/test 分割参数，默认 80/20
- **验收**：晋级门控基于 OOS IC，不是 IS IC
- **估时**：1 天

#### T-09：回归测试基准
- **目标**：建立一组已知结果的测试用例，确保代码变更不会静默改变评估结果
- **方法**：用固定的因子、固定的数据、固定的时间窗口，产出一组预期的 IC/ICIR/t-stat 值
- **估时**：1 天

---

## 五、建议执行顺序

```
Week 1:  T-01 (Walk-Forward 修复) → T-02 (IC 审计) → T-03 (回测产出物)
Week 2:  T-04 (端到端冒烟) → T-05 (IC 衰减追踪) → T-06 (Agent 同步)
Week 3:  T-07 (扩大股票池) → T-08 (OOS IC 门控) → T-09 (回归测试)
```

**核心逻辑：先让验证管线可信（Week 1），再让端到端闭环可靠（Week 2），最后提升因子发现质量（Week 3）。**

---

## 六、一句话 Goal（给编程 Agent）

**「修复 walk-forward 使其产出真实指标，审计 IC 评估方法使其回归合理范围，让系统能产出可信的 Alpha 判定。」**
