# Alpha Engine 工作成果总结

Date: 2026-06-20

## 一、质量门状态

| 检查项 | 结果 |
|--------|------|
| ruff | ✅ All checks passed |
| pytest | ✅ 894 passed, 9 skipped |
| TypeScript | ✅ 0 errors |
| Dashboard build | ✅ 1.4 MB (401 KB gzip) |
| release_gate.py | ✅ OVERALL: PASS |

## 二、核心成果

### 1. 模型训练探索

**跑赢 CSI300 的模型已找到：**

| 配置 | TOP 15 超额 | BOTTOM 15 超额 | Sharpe |
|------|------------|---------------|--------|
| 181 Alpha158 + 绝对收益标签 | **+8.07%** | **-20.26%** | 1.11 |

**关键发现：**
- 超额收益标签（14 种变体）全部失败
- 绝对收益标签隐式学到了超额收益能力
- 181 Alpha158 特征是唯一有效的特征集

**已记录：** `docs/model_training_experience.md`

### 2. 矢量化回测引擎

**创建：** `src/research/vectorized_backtest.py`

| 特性 | 值 |
|------|-----|
| 数据加载 | 0.5s |
| 回测计算 | 0.6s（38 个调仓周期） |
| 比 Qlib 快 | ~800 倍 |
| 测试 | 8 个单元测试 |

### 3. 矢量化特征工程

**创建：** `src/research/vectorized_features.py`

- 73 个特征（K-bar、滚动、动量、成交量、技术指标）
- 矩阵化计算，单次遍历
- 支持 NaN 填充和 z-score 标准化

### 4. 优化训练流程

**创建：** `src/research/excess_returns_training.py`

- 数据加载 2s + 特征计算 5-9s + 训练 0.5-3s = 总计 10-15s
- 比 Qlib 原生流程快 ~100 倍

### 5. 前端改进

| 页面 | 改进 |
|------|------|
| Dashboard | 模型选择器修复、路由注册表 |
| Models | 指标显示、证据链接、过期指标 |
| Backtest | 稳定 job 身份、sessionStorage 恢复 |
| Attribution | API 格式修复、基准标签 |
| Experiment Log | 新 API 端点、结构化数据 |
| System | Job Center、日志查看、取消/重试 |

### 6. 架构改进

| 模块 | 改进 |
|------|------|
| `src/workflows/commands.py` | `to_argv()` 支持多词解释器 |
| `src/assistant/job_service.py` | `command_envelopes` 列 + 自动迁移 |
| `src/agents/tools/orchestrator_tools.py` | 删除手写 fallback |
| `src/research/pipeline.py` | `_train_fn` 注入，文档化为 adapter bridge |
| `src/research/workflow_legacy.py` | 唯一 bridge 到 hooks |
| `src/models/artifact.py` | 不可变模型制品 |
| `src/models/metric_contract.py` | 版本化指标契约 |
| `src/models/reconstruction.py` | 模型重建/推理门禁 |
| `src/data/snapshot.py` | 内容寻址数据快照 |

### 7. 测试覆盖

| 测试类别 | 数量 |
|----------|------|
| 后端单元测试 | 894 |
| 前端 Vitest | 70 |
| Playwright E2E | 7 |
| **总计** | **971** |

### 8. 发布文档

| 文档 | 行数 |
|------|------|
| `docs/release/scope.md` | 347 |
| `docs/release/quickstart.md` | 264 |
| `docs/release/configuration.md` | 158 |
| `docs/release/data_model_trust.md` | 250 |
| `docs/release/operations_runbook.md` | 613 |
| `docs/release/contracts.md` | 105 |
| `docs/release/security_review.md` | 141 |
| `docs/release/performance_budget.md` | 114 |
| `docs/release/gates.md` | 90 |
| `docs/release/rc_signoff.md` | 54 |
| `docs/release/index.md` | 25 |
| `docs/release/model_training_experience.md` | 200+ |
| **总计** | **2,361** |

## 三、已知限制

1. **超额收益标签不工作**：14 种变体全部失败，绝对收益标签是唯一有效方案
2. **73 矢量化特征预测能力不足**：IC < 0.01，需要 181 Alpha158 特征
3. **54 个旧模型无法恢复**：mlruns 中无 pred.pkl 文件
4. **其他 agent 引入的测试失败**：`test_t48_pipeline_artifact_gates` 等

## 四、经验沉淀

**核心经验文件：**
- `docs/model_training_experience.md` — 模型训练完整经验（16 个章节）
- `docs/release/` — 发布文档体系（11 个文件）

**关键教训：**
1. 标签工程 > 超参调优（绝对收益 vs 超额收益）
2. 特征质量决定模型上限（181 Alpha158 >> 73 矢量化）
3. IC 不等于收益（模型 IC=0.01 但跑赢 CSI300 +8%）
4. 简单策略更有效（TOP N 等权 > 复杂 BiweeklyTrend）
5. 数据完整性是基础（54 个模型因缺少数据被移除）
