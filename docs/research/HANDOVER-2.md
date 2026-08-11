# HANDOVER-2: 模型优化基础设施复现指南

> 目标：让其他 agent 可以零差异复现优化实验
> 生成：2026-08-11
> PR: https://github.com/liuh886/alpha_engine/pull/765

---

## 一、快速开始

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
pip install -e .

# 验证安装
python -c "from src.data.foundation import DataFoundation; print('OK')"
```

**必需数据**: `data/providers/us/` 和 `data/providers/cn/` 目录必须存在，包含 Qlib 二进制格式的市场数据。如果没有，需要先运行 provider 构建流程（见第三节）。

---

## 二、可复现的实验

### 2.1 CNx 行业上限 + 因子组优化

**状态**: ✅ 4 候选通过全部门控，可复现

```bash
python scripts/cn_rounds_21_40_v2.py
```

**预期输出**: `artifacts/optimization/cn_rounds_21_40_v2/results.json`

| 候选 | Exc@20 | DD | Share | 门控 |
|---|---|---|---|---|
| r27_all4_cap4 | +34.9% | -13.4% | 0.416 | PASS |
| r26_revliq_cap4 | +33.4% | -11.0% | 0.304 | PASS |
| r37_baseline | +32.1% | -15.6% | 0.466 | PASS |

**配置说明**:
- r27: cn_balanced_ohlcv + cn_volatility_reversal + cn_price_volume_pressure + cn_short_reversal_liquidity
- XGBoost: 300 rounds, lr=0.03, subsample=0.8, colsample_bytree=0.8
- Top-15, strict max-4-per-sector

```bash
# 更全面的 CNx 优化
python scripts/cn_corrected.py        # R1-20: 基线 + 6 配置
python scripts/cn_rounds_21_40_v2.py   # R21-40: 20 配置
python scripts/all4_rounds_41_60.py    # R41-50: 10 配置 (CNx部分)
```

### 2.2 BYD 防御权重 + 滞后优化

**状态**: ✅ 对 v1.3 基线有 +18.3pp 改善，可复现

```bash
python scripts/byd_rounds_51_70.py
```

**预期输出**: `artifacts/optimization/byd_rounds_51_70_v1/results.json`

| 候选 | Exc@20 | DD | Calmar | vs v1.3 |
|---|---|---|---|---|
| r70_max | +82.2% | -22.3% | 3.69 | +18.3pp |
| r56_def50 | +69.6% | -20.7% | 3.36 | +5.7pp |

**配置说明**:
- r70_max: defense=0%, expansion_max=1.5, convex_power=8, max_financed=0.25, hysteresis 5%/-5%
- 使用 v1.3 正式回测数据 (`byd_v1_3_recovery_event_low_vol_confirmation_v1.json`)

```bash
python scripts/byd_corrected.py        # R1-20: 基线 + 5 配置
python scripts/byd_rounds_51_70.py     # R51-70: 20 配置
```

### 2.3 USx — 已由 #770 认证

**状态**: ✅ r11_sampled 已认证为 US x1.2

```bash
# 验证现有认证（不重新训练）
python scripts/validate_model_x1_baselines.py
```

#770 的认证收据: `data/research/experiment_receipts/us_x1_2_certification_v1.json`

### 2.4 QQQR — 无法优化

**状态**: ❌ 确认无法在当前数据条件下优化

**原因**: formal backtest 的 report 数据只包含聚合收益（gross_return），不包含个券（QQQ/QQQI/TQQQ/SGOV）的每日收益。任何权重叠加都是近似值，无法准确复现策略动态。

**要真正优化 QQQR，需要**: ETF 每日 OHLCV 数据（`data/providers/us/features/qqq/`, `qqqi/`, `tqqq/`, `sgov/`）

---

## 三、数据前提

### 3.1 Provider 数据

```bash
# 检查数据是否存在
ls data/providers/us/features/   # 应包含 87+ 股票目录
ls data/providers/cn/features/   # 应包含 108+ 股票目录

# 如果不存在，需要构建
python scripts/build_market_providers.py --csv-dir data/csv_source --market us
python scripts/build_market_providers.py --csv-dir data/csv_source --market cn
```

### 3.2 因子注册表

```bash
# 因子库 DB (可选，离线优化不需要)
ls artifacts/factor_registry.db   # 264 因子的 SQLite DB
```

### 3.3 正式回测数据 (QQQR/BYD 优化需要)

```bash
ls data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json
ls data/research/formal_backtests/byd_v1_3_recovery_event_low_vol_confirmation_v1.json
```

---

## 四、关键方法论差异（与原错误实验对比）

| 维度 | 原始 175 轮 (不可用) | 修正方法 (当前) |
|---|---|---|
| 成本 | flat discount `ret * (1 - cost/cadence)` | turnover × cost_bps / 10000 |
| 行业上限 | 不足时填回任意股票 | strict — 只取合格的 |
| 收益重构 | 稀疏持仓价格 → pct_change → 填零 | report gross_return → 权重比例缩放 |
| BYD 滞后 | 无状态记忆（中间区域回防御） | 真正状态机 (cross threshold → toggle) |
| BYD 基线 | v1.2 | v1.3 |
| 窗口验证 | 全时段单窗口 | 4 个半年窗口 (2024H1-2025H2) |
| 60bps 压力 | 折扣法不可采信 | 实际 turnover × 60bps |

---

## 五、基础设施使用指南

### 5.1 DataFoundation

```python
from src.data.foundation import DataFoundation

# 初始化（线上线下相同代码路径）
foundation = DataFoundation(
    market="us",           # "us" | "cn"
    benchmark="QQQ",       # "QQQ" | "000300"
    provider_uri="data/providers/us",
)
foundation.initialize()

# 获取因子表达式
exprs = foundation.factor_expressions(["momentum_volatility_volume"])

# 加载窗口数据（自动缓存）
wdata = foundation.load_window("2024H1", exprs)
# → {"features": DataFrame, "returns": DataFrame, "benchmark": DataFrame, "eval_dates": [...]}

# 前向窗口（线上 agent）
fw = foundation.load_forward_window(exprs, lookback_sessions=500)

# 数据刷新检测
if foundation.needs_refresh():
    foundation.refresh()
```

### 5.2 FactorLibrary

```python
from src.factors.unified_library import get_factor_library

lib = get_factor_library()

# 查询
active_us = lib.query(market="us", status="active")     # 52 因子
momentum = lib.query(family="momentum")                  # 7 因子
proposed = lib.proposed_factors()                        # 244 因子

# 获取表达式
exprs = lib.expressions_for_groups(["momentum_volatility_volume"])

# 统计
print(lib.stats())
# → {"total_factors": 307, "by_source": {...}, "by_status": {...}}
```

### 5.3 优化器框架

```python
from src.optimization import (
    ExperimentContract, CandidateSpec, CostStructure, WindowSpec,
    ModelType, GateProfile,
    RankerOptimizer, RotatorOptimizer, TimerOptimizer,
)

# 定义实验
contract = ExperimentContract(
    experiment_id="my_grid",
    model_type=ModelType.RANKER,
    market="us",
    benchmark="QQQ",
    cost_structure=CostStructure(base_cost_bps=20.0),
    windows=WindowSpec(labels=("2024H1", "2024H2", "2025H1", "2025H2")),
    candidates=(
        CandidateSpec(candidate_id="baseline", role="baseline", params={...}),
        CandidateSpec(candidate_id="challenger", role="challenger", params={...}),
    ),
    baseline_candidate_id="baseline",
)

# 运行
runner = RankerOptimizer(contract, output_dir="artifacts/optimization")
result = runner.run()
# → {"receipt_path": "artifacts/optimization/my_grid/experiment_receipt.json", ...}
```

或通过 YAML 规格 + CLI：
```bash
python scripts/run_model_optimizer.py --spec configs/optimization/my_grid.yaml
```

---

## 六、已知局限

| 局限 | 影响 | 绕过方式 |
|---|---|---|
| QQQR 缺个券 ETF 日线 | 无法优化权重 | 获取 ETF OHLCV 数据 |
| BYD 收益缩放近似 | 非精确个券收益 | 需 BYD/515180 日线数据 |
| CNx 无 2026H1 验证 | 缺失样本外证据 | 扩展 provider 数据至 2026H1 |
| USx 无需额外优化 | 已由 #770 认证 | 直接使用 #770 结果 |
| 244 Proposed 因子未验证 | 潜在信号未利用 | 运行因子扫描 + 升级管线 |

---

## 七、文件索引

### 核心基础设施
| 文件 | 用途 |
|---|---|
| `src/data/foundation.py` | DataFoundation — 线上线下共享数据层 |
| `src/factors/unified_library.py` | FactorLibrary — 307 因子统一查询 |
| `src/optimization/contracts.py` | 实验合约定义 |
| `src/optimization/metrics.py` | 门控检查 |
| `src/optimization/runner.py` | 运行器基类 |
| `src/optimization/ranker_runner.py` | Ranker 优化器 |
| `src/optimization/rotator_runner.py` | Rotator 优化器 |
| `src/optimization/timer_runner.py` | Timer 优化器 |

### 修正实验脚本
| 文件 | 轮次 | 说明 |
|---|---|---|
| `scripts/cn_corrected.py` | R1-20 | CNx 基线 + 6 配置 |
| `scripts/cn_rounds_21_40_v2.py` | R21-40 | CNx 20 配置 |
| `scripts/byd_corrected.py` | R1-20 | BYD 基线 + 5 配置 |
| `scripts/byd_rounds_51_70.py` | R51-70 | BYD 20 配置 |
| `scripts/qqqr_corrected.py` | R1-20 | QQQR (确认不可优化) |
| `scripts/all4_rounds_41_60.py` | R41-60 | 四模型综合 |

### 认证基线
| 文件 | 说明 |
|---|---|
| `data/research/experiment_receipts/us_x1_2_certification_v1.json` | USx #770 认证 |
| `configs/models/us_x1_2.yaml` | US x1.2 模型合约 |

---

## 八、Agent 复现检查清单

- [ ] `pip install -e .` 成功
- [ ] `DataFoundation(market="us").initialize()` 不报错
- [ ] `get_factor_library().stats()["total_factors"]` ≥ 300
- [ ] `data/providers/us/` 和 `data/providers/cn/` 存在
- [ ] `data/research/formal_backtests/byd_v1_3_*.json` 存在
- [ ] `python scripts/cn_rounds_21_40_v2.py` 在 10 分钟内完成
- [ ] `python scripts/byd_rounds_51_70.py` 在 2 分钟内完成
- [ ] CNx 输出显示 "PASS" ≥ 3 行
- [ ] BYD 输出显示 r70_max 为最高 Calmar
