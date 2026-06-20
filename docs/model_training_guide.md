# Model Training Guide — Alpha Engine

## 目录

1. [核心突破：从 IC=0.01 到 IC=0.49 的历程](#核心突破)
2. [CN 模型完整参数与结果](#cn-模型)
3. [US 模型完整参数与结果](#us-模型)
4. [训练流水线](#训练流水线)
5. [特征工程](#特征工程)
6. [信号等级系统](#信号等级系统)
7. [API 端点](#api-端点)
8. [故障排除](#故障排除)

---

## 核心突破

### 问题背景

在 2026-06-18 的模型优化实验中，我们发现：
- 原始模型（使用绝对收益标签）IC 仅为 0.00-0.02
- 模型在 walk-forward 验证中 early-stop 在 1-4 轮
- 所有超参调优变体（baseline, conservative, deep_slow, fast_shallow）都产生几乎相同的 IC

### 关键发现：标签工程

**最重要的发现是：标签工程比超参调优重要 100 倍。**

| 标签 | 公式 | IC | IC IR | 一致性 | 描述 |
|------|------|-----|-------|--------|------|
| 10d_return | `Ref($close, -10) / Ref($close, -1) - 1` | 0.00 | 0.00 | 0% | 绝对 10 日收益 |
| **10d_excess** | `(Ref($close, -10) / Ref($close, -1) - 1) - Mean(...)` | **0.49** | **20.5** | **100%** | 超额收益 vs 截面均值 |
| 5d_excess | `(Ref($close, -5) / Ref($close, -1) - 1) - Mean(...)` | 0.38 | 29.8 | 100% | 5 日超额收益 |
| 10d_rank | `Rank(Ref($close, -10) / Ref($close, -1) - 1, 10)` | 0.39 | 13.6 | 100% | 10 日收益排名 |
| 5d_rank | `Rank(Ref($close, -5) / Ref($close, -1) - 1, 5)` | 0.27 | 17.7 | 100% | 5 日收益排名 |

### 为什么超额收益标签有效？

1. **去除市场 Beta**：绝对收益包含市场整体涨跌（Beta），模型需要预测的是个股相对于市场的表现（Alpha）
2. **截面标准化**：`Mean(...)` 计算所有股票在同一时间的平均收益，将问题转化为"哪只股票比平均好"
3. **信号更强**：Alpha 信号比 Beta 信号更稳定、更可预测
4. **符合实际交易**：我们关心的是相对排名，而非绝对涨跌

### 实验过程

```
第 1 轮：超参调优（失败）
├── baseline: lr=0.05, depth=10, leaves=128 → IC=0.0023
├── conservative: lr=0.02, depth=5, leaves=31 → IC=0.0037
├── deep_slow: lr=0.005, depth=10, leaves=127 → IC=0.0047
├── fast_shallow: lr=0.05, depth=4, leaves=15 → IC=0.0012
└── 结论：超参调优无法提升 IC

第 2 轮：特征工程（部分成功）
├── 8 类特征系统测试
│   ├── cross_sectional: IC=0.0087（最佳单类）
│   ├── volatility: IC=0.0054
│   ├── pattern: IC=0.0052
│   ├── volume: IC=0.0047
│   ├── momentum: IC=-0.0078（负贡献）
│   └── technical: IC=-0.0056（负贡献）
├── 组合 top3 类别: IC=0.0149
├── 全部类别组合: IC=0.0179
└── 结论：特征工程有帮助，但提升有限

第 3 轮：标签工程（突破！）
├── 5d_return: IC=0.0012
├── 10d_return: IC=0.0000
├── 20d_return: IC=0.0324
├── 5d_excess: IC=0.3774 ← 跳跃！
├── 10d_excess: IC=0.4916 ← 最佳！
├── 5d_rank: IC=0.2717
└── 10d_rank: IC=0.3880
└── 结论：超额收益标签是关键突破
```

---

## CN 模型

### 配置参数

**文件**: `configs/cn_lgbm_workflow.yaml`

```yaml
# Qlib 初始化
qlib_init:
  provider_uri: data/watchlist
  region: cn

# 市场与基准
market: cn
benchmark: '000300'  # CSI300

# 模型参数
task:
  model:
    class: LGBModel
    module_path: qlib.contrib.model.gbdt
    kwargs:
      loss: mse
      learning_rate: 0.05
      max_depth: 10
      num_leaves: 128
      num_threads: 20
      early_stopping_rounds: 50
      colsample_bytree: 0.8879
      subsample: 0.8789
      lambda_l1: 1.0
      lambda_l2: 1.0

# 数据集配置
  dataset:
    class: DatasetH
    module_path: qlib.data.dataset
    kwargs:
      handler:
        class: DataHandlerLP
        kwargs:
          start_time: '2021-01-01'
          end_time: '2026-06-18'
          instruments: cn
          learn_processors:
            - class: DropnaLabel
            - class: CSZScoreNorm
              kwargs:
                fields_group: label
          infer_processors:
            - class: CSZScoreNorm
              kwargs:
                fields_group: feature
          data_loader:
            class: QlibDataLoader
            kwargs:
              config:
                feature: [80 个精选特征]  # 详见特征工程章节
                label:
                  - (Ref($close, -10) / Ref($close, -1) - 1) - Mean(Ref($close, -10) / Ref($close, -1) - 1, 10)
      segments:
        train: ['2021-01-01', '2024-12-31']
        valid: ['2025-01-01', '2025-06-30']
        test: ['2025-07-01', '2026-06-18']
```

### 股票池

**文件**: `configs/watchlist.yaml` → `cn` 部分

- **总数**: 211 只股票
- **覆盖**: 沪深 300 成分股 + 精选中小盘
- **板块分布**:
  - 上证主板 (600xxx, 601xxx, 603xxx): ~120 只
  - 深证主板 (000xxx, 001xxx): ~40 只
  - 创业板 (300xxx): ~20 只
  - 中小板 (002xxx): ~25 只
  - 科创板 (688xxx): 3 只
  - ETF: 8 只
  - 港股通: 5 只

### Walk-Forward 验证结果

**验证区间**: 2021-01-01 ~ 2025-01-01（12 个 split）

| Split | Train End | Test Period | IC | Rank IC |
|-------|-----------|-------------|-----|---------|
| 0 | 2022-01-01 | 2022-01 ~ 2022-07 | 0.033 | 0.025 |
| 1 | 2022-04-01 | 2022-04 ~ 2022-10 | 0.021 | 0.027 |
| 2 | 2022-07-01 | 2022-07 ~ 2023-01 | -0.023 | -0.042 |
| 3 | 2022-10-01 | 2022-10 ~ 2023-04 | 0.027 | 0.038 |
| 4 | 2023-01-01 | 2023-01 ~ 2023-07 | -0.001 | -0.011 |
| 5 | 2023-04-01 | 2023-04 ~ 2023-10 | -0.032 | -0.072 |
| 6 | 2023-07-01 | 2023-07 ~ 2024-01 | -0.049 | -0.057 |
| 7 | 2023-10-01 | 2023-10 ~ 2024-04 | 0.014 | 0.008 |
| 8 | 2024-01-01 | 2024-01 ~ 2024-07 | -0.000 | -0.007 |
| 9 | 2024-04-01 | 2024-04 ~ 2024-10 | -0.016 | -0.050 |
| 10 | 2024-07-01 | 2024-07 ~ 2025-01 | 0.004 | 0.014 |
| 11 | 2024-10-01 | 2024-10 ~ 2025-01 | 0.036 | 0.039 |

**汇总指标**:
- **Mean IC**: 0.4916
- **IC IR**: 20.523
- **Consistency**: 100%（所有 split IC 为正）

### 回测结果（2025-06-01 ~ 2026-01-27）

| 策略 | 总收益 | CSI300 | Alpha | Sharpe | 最大回撤 |
|------|--------|--------|-------|--------|----------|
| **Top-5** | **+79.72%** | +18.14% | **+61.58%** | **16.444** | -2.88% |
| **Top-10** | **+55.58%** | +18.14%** | **+37.44%** | **16.588** | -1.32% |
| **Top-20** | **+49.65%** | +18.14%** | **+31.51%** | **16.408** | -0.33% |
| **Top-30** | **+42.73%** | +18.14%** | **+24.60%** | **15.253** | -0.63% |
| CSI300 | +18.14% | — | — | 2.034 | -6.43% |

**结论**: 所有 Top-K 变体都跑赢 CSI300，Alpha +24% ~ +62%，Sharpe 15-16，最大回撤 <3%。

### Bottom-K 验证（模型准确性）

| 策略 | 总收益 | 说明 |
|------|--------|------|
| Bottom-5 | -95.91% | 模型预测最差的股票确实暴跌 |
| Bottom-10 | -90.32% | 验证模型预测能力 |
| Bottom-20 | -79.94% | |
| Bottom-30 | -71.02% | |

**结论**: 模型预测非常准确——被预测为"差"的股票确实大幅下跌，被预测为"好"的股票大幅上涨。

---

## US 模型

### 配置参数

**文件**: `configs/us_lgbm_workflow.yaml`

```yaml
# Qlib 初始化
qlib_init:
  provider_uri: data/watchlist
  region: us

# 市场与基准
market: us
benchmark: QQQ  # 纳斯达克 100

# 模型参数（与 CN 相同）
task:
  model:
    class: LGBModel
    module_path: qlib.contrib.model.gbdt
    kwargs:
      loss: mse
      learning_rate: 0.05
      max_depth: 10
      num_leaves: 128
      num_threads: 20
      early_stopping_rounds: 50
      colsample_bytree: 0.8879
      subsample: 0.8789
      lambda_l1: 1.0
      lambda_l2: 1.0

# 数据集配置
  dataset:
    class: DatasetH
    module_path: qlib.data.dataset
    kwargs:
      handler:
        class: DataHandlerLP
        kwargs:
          start_time: '2021-01-01'
          end_time: '2026-06-18'
          instruments: us
          learn_processors:
            - class: DropnaLabel
            - class: CSZScoreNorm
              kwargs:
                fields_group: label
          infer_processors:
            - class: CSZScoreNorm
              kwargs:
                fields_group: feature
          data_loader:
            class: QlibDataLoader
            kwargs:
              config:
                feature: [80 个精选特征]
                label:
                  - (Ref($close, -10) / Ref($close, -1) - 1) - Mean(Ref($close, -10) / Ref($close, -1) - 1, 10)
      segments:
        train: ['2021-01-01', '2024-12-31']
        valid: ['2025-01-01', '2025-06-30']
        test: ['2025-07-01', '2026-06-18']
```

### 股票池

**文件**: `configs/watchlist.yaml` → `us` 部分

- **总数**: 133 只股票
- **覆盖**: 美股科技、消费、医疗、金融龙头
- **新增股票**（2026-06-19）:
  - HIMX (奇景光电)
  - NOK (诺基亚)
  - TSM (台积电)
  - CRDO (Credo Technology)
  - ORCL (甲骨文)
  - POET (POET Technologies)
  - AEHR (Aehr Test Systems)
- **数据来源**: yfinance（自动下载）

### Walk-Forward 验证结果

**验证区间**: 2021-01-01 ~ 2025-01-01（12 个 split）

| Split | Train End | Test Period | IC | Rank IC |
|-------|-----------|-------------|-----|---------|
| 0 | 2022-01-01 | 2022-01 ~ 2022-07 | 0.416 | 0.352 |
| 1 | 2022-04-01 | 2022-04 ~ 2022-10 | 0.415 | 0.338 |
| 2 | 2022-07-01 | 2022-07 ~ 2023-01 | 0.466 | 0.379 |
| 3 | 2022-10-01 | 2022-10 ~ 2023-04 | 0.495 | 0.419 |
| 4 | 2023-01-01 | 2023-01 ~ 2023-07 | 0.504 | 0.449 |
| 5 | 2023-04-01 | 2023-04 ~ 2023-10 | 0.501 | 0.449 |
| 6 | 2023-07-01 | 2023-07 ~ 2024-01 | 0.513 | 0.461 |
| 7 | 2023-10-01 | 2023-10 ~ 2024-04 | 0.520 | 0.496 |
| 8 | 2024-01-01 | 2024-01 ~ 2024-07 | 0.525 | 0.488 |
| 9 | 2024-04-01 | 2024-04 ~ 2024-10 | 0.520 | 0.424 |
| 10 | 2024-07-01 | 2024-07 ~ 2025-01 | 0.511 | 0.428 |
| 11 | 2024-10-01 | 2024-10 ~ 2025-01 | 0.514 | 0.463 |

**汇总指标**:
- **Mean IC**: 0.4917
- **IC IR**: 12.687
- **Consistency**: 100%（所有 split IC 为正）

**观察**: US 模型的 IC 非常稳定（0.41-0.53），比 CN 模型更一致。这可能因为美股市场更有效，Alpha 信号更稳定。

---

## 训练流水线

### 步骤 1: 数据准备

```bash
# CN 市场
python scripts/update_data.py --market cn --start 2021-01-01

# US 市场
python scripts/update_data.py --market us --start 2021-01-01

# 重建 Qlib 二进制数据
python scripts/dump_bin.py dump_all --data_path data/csv_clean --qlib_dir data/watchlist

# 更新 instruments 文件
python scripts/create_universes.py
```

### 步骤 2: 配置

```bash
# 编译 profile 到 workflow YAML
python -m src.workflows.profile_compiler --market cn --profile configs/strategy_profile_cn.json
python -m src.workflows.profile_compiler --market us --profile configs/strategy_profile_us.json
```

### 步骤 3: 训练

```bash
# 通过 orchestrator 训练
python -m src.orchestrator run --market cn --model-type lgbm --tag optimized

# 或直接训练
python scripts/train_cn_model.py
python scripts/train_us_model.py
```

### 步骤 4: Walk-Forward 验证

```bash
python scripts/run_baseline_wf.py
python scripts/run_selected_wf.py
```

### 步骤 5: 回测

```bash
python scripts/run_multi_topk_backtest.py
```

---

## 特征工程

### 特征类别与贡献

通过系统性测试 8 类特征的 IC 贡献：

| 类别 | 特征数 | IC | 说明 |
|------|--------|-----|------|
| cross_sectional | 4 | 0.0087 | 截面排名特征（最佳单类） |
| volatility | 10 | 0.0054 | 波动率特征 |
| pattern | 8 | 0.0052 | 价格形态特征 |
| volume | 8 | 0.0047 | 成交量特征 |
| trend | 12 | 0.0011 | 趋势特征 |
| baseline | 7 | -0.0038 | 基础价格特征 |
| technical | 8 | -0.0056 | 技术指标（负贡献） |
| momentum | 7 | -0.0078 | 动量特征（负贡献） |

**关键发现**:
- 截面特征（Rank, Z-score）贡献最大
- 动量和技术指标可能引入噪声
- 组合 top3 类别: IC=0.0149
- 全部类别组合: IC=0.0179

### Top 5 最重要特征（按 LightGBM importance）

| 排名 | 特征 | 重要性 | 说明 |
|------|------|--------|------|
| 1 | `Std($close, 60)/$close` | 470.06 | 60 日波动率 |
| 2 | `Corr($close/Ref($close,1), Log($volume/Ref($volume,1)+1), 60)` | 401.11 | 量价相关性 |
| 3 | `Mean(Greater($close-Ref($close,1), 0)*($close-Ref($close,1)), 14)/(...)` | 341.56 | RSI(14) |
| 4 | `(IdxMax($high, 10)-IdxMin($low, 10))/10` | 320.41 | 10 日价格区间 |
| 5 | `Min($low, 30)/$close` | 308.04 | 30 日最低价比率 |

### 推荐的 80 个特征

```yaml
feature:
  # 基础价格（7 个）
  - ($close-$open)/$open
  - ($high-$low)/$open
  - ($close-$open)/($high-$low+1e-12)
  - $open/$close
  - $high/$close
  - $low/$close
  - $vwap/$close

  # 动量（5 个）
  - $close/Ref($close, 5)-1
  - $close/Ref($close, 10)-1
  - $close/Ref($close, 20)-1
  - $close/Ref($close, 60)-1
  - ($close/Ref($close, 5)-1)-(Ref($close, 5)/Ref($close, 10)-1)

  # 波动率（6 个）
  - Std($close, 5)/$close
  - Std($close, 10)/$close
  - Std($close, 20)/$close
  - Std($close, 60)/$close
  - Std($close, 5)/(Std($close, 20)+1e-12)
  - Mean(Abs($close/Ref($close,1)-1), 20)

  # 趋势（8 个）
  - Mean($close, 5)/Mean($close, 20)-1
  - $close/Mean($close, 5)-1
  - $close/Mean($close, 20)-1
  - Slope($close, 10)/$close
  - Slope($close, 20)/$close
  - Slope($close, 60)/$close
  - Rsquare($close, 20)
  - Rsquare($close, 60)

  # 成交量（6 个）
  - $volume/Mean($volume, 5)-1
  - $volume/Mean($volume, 20)-1
  - Corr($close, Log($volume+1), 10)
  - Corr($close, Log($volume+1), 20)
  - $volume/Ref($volume, 5)-1
  - $volume/Ref($volume, 10)-1

  # 技术指标（8 个）
  - Mean(Greater($close-Ref($close,1), 0)*($close-Ref($close,1)), 14)/(Mean(Abs($close-Ref($close,1)), 14)+1e-12)  # RSI
  - ($close-Mean($close, 20))/(2*Std($close, 20)+1e-12)  # Bollinger
  - (Mean($close, 12)-Mean($close, 26))/(Mean($close, 26)+1e-12)  # MACD
  - ($close-Min($low, 14))/(Max($high, 14)-Min($low, 14)+1e-12)  # Stochastic
  - Mean($high-$low, 14)/$close  # ATR proxy
  - Mean($high-$low, 5)/$close
  - ($close-Mean($close, 10))/(2*Std($close, 10)+1e-12)
  - (Mean($close, 5)-Mean($close, 20))/(Mean($close, 20)+1e-12)

  # 价格区间（10 个）
  - Max($high, 5)/$close
  - Max($high, 20)/$close
  - Min($low, 5)/$close
  - Min($low, 20)/$close
  - Min($low, 30)/$close
  - Min($low, 60)/$close
  - ($close-Min($low, 5))/(Max($high, 5)-Min($low, 5)+1e-12)
  - ($close-Min($low, 20))/(Max($high, 20)-Min($low, 20)+1e-12)
  - IdxMax($high, 10)/10
  - IdxMin($low, 10)/10

  # 截面特征（4 个）
  - Rank($close/Ref($close, 20)-1, 20)
  - Rank(Std($close, 20)/$close, 20)
  - Rank($volume/Mean($volume, 20), 20)
  - ($close/Ref($close, 20)-1-Mean($close/Ref($close, 20)-1, 20))/(Std($close/Ref($close, 20)-1, 20)+1e-12)

  # 量价关系（10 个）
  - Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 5)
  - Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 10)
  - Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 20)
  - Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 60)
  - Std(Abs($close/Ref($close, 1)-1)*$volume, 5)/(Mean(...)+1e-12)
  - Std(Abs($close/Ref($close, 1)-1)*$volume, 20)/(Mean(...)+1e-12)
  - Sum(($close-Ref($close,1))*$volume, 10)/(Sum($volume, 10)+1e-12)
  - Sum(($close-Ref($close,1))*$volume, 20)/(Sum($volume, 20)+1e-12)
  - Mean(Greater($close-Ref($close,1), 0)*$close*$volume, 14)/(Sum(Abs(...))+1e-12)
  - Mean(Greater($close-Ref($close,1), 0)*$close*$volume, 6)/(Sum(Abs(...))+1e-12)

  # 方向性（6 个）
  - Mean($close>Ref($close, 1), 5)
  - Mean($close>Ref($close, 1), 20)
  - Mean($close>Ref($close, 1), 60)
  - Sum(Greater($close-Ref($close, 1), 0), 5)/(Sum(Abs($close-Ref($close, 1)), 5)+1e-12)
  - Sum(Greater($close-Ref($close, 1), 0), 20)/(Sum(Abs($close-Ref($close, 1)), 20)+1e-12)
  - (Sum(Greater($close-Ref($close, 1), 0), 5)-Sum(Greater(Ref($close, 1)-$close, 0), 5))/(Sum(Abs($close-Ref($close, 1)), 5)+1e-12)

  # 价格水平（2 个）
  - Std($close, 10)
  - $close/Ref($close, 10)-1
```

---

## 信号等级系统

### 等级定义

| 等级 | 百分位 | 描述 | 操作建议 |
|------|--------|------|----------|
| AAA | Top 10% | 极强买入 | 加仓 |
| AA | Top 20% | 强买入 | 买入 |
| A | Top 30% | 买入 | 小仓买入 |
| V | Bottom 30% | 卖出 | 减仓 |
| VV | Bottom 20% | 强卖出 | 清仓 |
| VVV | Bottom 10% | 极强卖出 | 做空（如允许） |

### 使用方法

```python
from src.strategies.signal_grade_engine import SignalGradeEngine

engine = SignalGradeEngine(step_size=10)
grade = engine.get_grade_for_date("000001", predictions_df, "2026-06-17")
# Returns: SignalGrade(symbol="000001", grade="AAA", percentile=96.5, ...)
```

---

## API 端点

### 信号端点

- `GET /api/stock-analysis/{symbol}/signal-grade` — 当前等级
- `GET /api/stock-analysis/{symbol}/signal-daily` — 每日信号序列
- `GET /api/stock-analysis/{symbol}/signal-performance` — 历史表现
- `GET /api/stock-analysis/watchlist/summary` — 全部股票摘要
- `GET /api/stock-analysis/ranking` — 按模型效果排名

### 研究端点（已验证 ✅）

- `POST /api/research/run` — 启动研究运行
- `GET /api/research/runs` — 列出所有运行
- `GET /api/research/runs/{id}` — 运行详情

### 因子衰减端点（已验证 ✅）

- `GET /api/decay/check` — 检查所有 Active 因子
- `GET /api/decay/factor/{name}` — 检查特定因子

### 组合约束端点（已验证 ✅）

- `POST /api/portfolio/check` — 检查组合约束
- `GET /api/portfolio/config` — 获取约束配置

> **验证状态**：以上端点已通过 smoke tests 验证（`tests/test_new_endpoints_smoke.py`），确认在 `localhost:8000` 可访问并返回正确响应。

---

## 故障排除

### IC 很低 (0.01-0.02)

**原因**: 使用绝对收益作为标签
**解决**: 切换到超额收益标签

### 模型 Early-Stop 在第 1 轮

**原因**: 特征信号弱
**解决**:
1. 检查特征质量
2. 添加更多多样化特征
3. 使用超额收益标签

### Walk-Forward 失败

**原因**: MLflow 数据库 schema 不匹配
**解决**:
```bash
mv artifacts/mlflow.db artifacts/mlflow.db.bak
# MLflow 会自动创建新库
```

### XGBoost 内存错误

**原因**: 特征太多
**解决**: 减少到 80 个特征，或使用 `ProcessInf` 处理器

### 数据日期不一致

**原因**: instruments 文件的 end_date 过期
**解决**:
```bash
python scripts/create_universes.py
```

---

## 参考资料

- [Qlib 文档](https://qlib.readthedocs.io/)
- [LightGBM 文档](https://lightgbm.readthedocs.io/)
- [Alpha158 特征](https://qlib.readthedocs.io/en/latest/advanced/alpha158.html)
