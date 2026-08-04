# v4.13 donor formal-state2 SGOV/TQQQ 风险预算：结果与独立审计

**证据日期：** 2026-08-04  
**实验：** `qqqi_qqq_tqqq_donor_state2_sgov_tqqq_v4_13_research`  
**当前基线：** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**专项工作流：** `QQQI v4.2 Donor State2 SGOV TQQQ` run `30864102710`  
**Evidence artifact：** `8875454941`  
**Artifact digest：** `sha256:b9bbabd4e4ef2e362906a469a2b3394d7a812612721086d30c98bf5f74a5ba00`  
**状态：** research-only；not trade-ready

## 执行结论

v4.13 将 v4.12 的跨资产事件研究进一步收窄为与 v4.2 完全同构的问题：

> 当冻结的 v4.2 已正式进入 state 2 后，是否应将该 episode 的 TQQQ 风险预算设为50%、75%或100%，其余配置为BIL／SGOV？

本实验完整保留：

- v4.2 的 state 0、state 1和state 2日期序列；
- state 0的100% QQQI；
- state 1的50% QQQI／50% QQQ；
- VIX／VXN、价格恢复和退出逻辑；
- 收盘信号、下一开盘执行；
- 每单位换手10 bps成本。

只有已经确认的 formal state-2 episode 内部权重可以变化。

最终分类：

`donor_formal_state2_transfer_signal_not_stable`

独立审计分类：

`audit_pass_nonpromotion_result_valid`

本轮得到三个清晰结论：

1. **独立事件数量已不再是主要瓶颈。** 六组 donor 产生205个 formal state-2 episode、55个宏观日期簇；
2. **跨资产迁移本身有一定信息。** Leave-one-asset-out AUC为0.599、IC为0.126，六个资产中五个方向为正；
3. **时间稳定性仍然不足。** 完整宏观簇留出 AUC仅0.537、IC仅0.042，顶／底四分位差为-0.41%，未通过 donor gate。

目标端同样显示明显的时间不稳定：

- 2017—2019主窗口中，joint相对v4.2 CAGR提高1.38个百分点，两个日历年为正；
- 但Calmar仅提高0.062，低于0.10门槛；
- 2020—2023隔离窗口中，joint CAGR落后v4.2 8.51个百分点，Calmar下降0.200；
- 2024—2026实际产品窗口中，joint CAGR落后6.20个百分点，最大回撤恶化2.79个百分点，Calmar下降0.355。

因此，2017—2019的局部胜出不能解释为稳定击败 v4.2。v4.13不进入shadow，v4.2和所有行动性告警保持不变。

## 1. 研究设计

### 1.1 Donor formal state-2 episode

使用六组固定 donor：

| Underlying | 3x ETF |
|---|---|
| SPY | UPRO |
| IWM | TNA |
| DIA | UDOW |
| XLK | TECL |
| SOXX | SOXL |
| XLF | FAS |

每个 donor 将 underlying 同时作为防守和普通风险资产，将3x ETF作为杠杆资产，使用冻结的价格／VIX状态机生成正式的执行状态：

- episode始于下一开盘执行的 `1→2`；
- episode结束于最后一个连续 executed state-2交易日；
- episode标签为3x ETF相对BIL的整段对数收益差；
- QQQ、TQQQ、QQQI、SGOV和VXN不进入 donor 拟合。

### 1.2 固定特征与模型

信号收盘时使用14个特征：

- underlying 5日、20日收益；
- 相对MA20、MA50、MA200距离；
- MA20五日斜率；
- 20日实现波动率；
- 63日回撤；
- VIX五日变化、20日高位回落、252日分位；
- donor breadth高于MA20和MA50的比例；
- executed state 1持续交易日数。

模型固定为：

- donor中位数补值；
- 标准化；
- L2 Logistic Regression；
- `C=1.0`；
- balanced class weight；
- liblinear；
- 固定随机种子。

### 1.3 双重 donor 验证

必须同时通过：

1. Leave-one-macro-cluster-out；
2. Leave-one-asset-out。

宏观簇以30个自然日为窗口，同一冲击中的不同 donor episode 不得被拆入训练与验证两侧。

### 1.4 目标权重

每个目标 formal state-2 episode 仅读取入场前收盘概率一次，并冻结至 episode结束：

- `p < 0.40`：50%现金／50% TQQQ；
- `0.40 ≤ p < 0.60`：25%现金／75% TQQQ；
- `p ≥ 0.60`：100% TQQQ。

长历史 proxy 使用BIL，实际产品使用SGOV。现金或目标特征在个别信号日缺失时，由预注册的 donor median imputer处理；若某目标年份根本没有可用的双类别 donor训练集，则保持v4.2的75% TQQQ且阻断shadow。本次三个目标范围均实现100%模型覆盖。

## 2. Donor formal state-2 证据

### 2.1 样本规模

- donor formal state-2 episode：**205个**；
- 宏观日期簇：**55个**；
- donor资产：6个；
- 最大单资产episode占比：24.39%；
- 正标签比例：41.46%。

事件数量与资产分散度均通过门槛。

### 2.2 宏观簇 OOF

| 指标 | 结果 | 门槛 | 判断 |
|---|---:|---:|---|
| ROC AUC | **0.537** | ≥0.55 | 未通过 |
| Spearman IC | **0.042** | ≥0.05 | 未通过 |
| 顶／底四分位差 | **-0.41%** | >0 | 未通过 |
| 最大正簇贡献占比 | 10.56% | ≤30% | 通过 |
| 最大单资产episode占比 | 24.39% | ≤40% | 通过 |

宏观簇完整留出未通过。模型并非完全随机，但其跨时间排序不足以支持目标配置。

### 2.3 Leave-one-asset-out

| 指标 | 结果 | 门槛 | 判断 |
|---|---:|---:|---|
| ROC AUC | **0.599** | ≥0.55 | 通过 |
| Spearman IC | **0.126** | ≥0.05 | 通过 |
| 顶／底四分位差 | **+2.72%** | >0 | 通过 |
| 正向资产数 | **5/6** | ≥4 | 通过 |

资产分层：

| Donor | Episode | 高概率平均超额 | 低概率平均超额 | 高－低差 |
|---|---:|---:|---:|---:|
| DIA | 26 | +0.64% | -2.75% | +3.39% |
| IWM | 34 | +1.65% | +0.58% | +1.07% |
| SOXX | 50 | +2.28% | +3.09% | **-0.80%** |
| SPY | 23 | +1.84% | -1.80% | +3.64% |
| XLF | 34 | +1.43% | -3.59% | +5.02% |
| XLK | 38 | +6.63% | +2.45% | +4.18% |

这表明跨资产信息并未完全消失，问题主要来自时间／宏观regime不稳定，而不是某一个 donor独占结果。

## 3. 2017—2019 主窗口

精确同窗：2017-01-03至2019-12-31，共754个交易日。共有7个 formal state-2 episode：

- low：3个；
- medium：1个；
- high：3个；
- 模型覆盖率：100%。

| 策略 | CAGR | Sharpe | Sortino | 最大回撤 | Calmar | 换手 |
|---|---:|---:|---:|---:|---:|---:|
| Frozen v4.2 | 23.43% | 1.124 | 1.571 | -22.46% | 1.043 | 40.0 |
| 固定25%现金／75% TQQQ | 22.86% | 1.135 | 1.586 | -22.45% | 1.018 | 45.0 |
| Defensive-only | 23.73% | **1.197** | **1.687** | -22.45% | 1.057 | 45.0 |
| Offensive-only | 23.93% | 1.114 | 1.573 | -22.45% | 1.066 | 45.0 |
| Joint donor budget | **24.81%** | 1.169 | 1.663 | -22.45% | **1.105** | 45.0 |

Joint相对v4.2：

- CAGR +1.38个百分点；
- 最大回撤基本不变；
- Sortino +0.092；
- Calmar +0.062；
- 换手增加12.5%；
- 2018、2019相对收益为正，2017无发生配置变化的目标episode；
- 最大正episode贡献占比45.63%。

除Calmar门槛外，其余主窗口要求通过。Calmar要求至少提高0.10，而实际仅提高0.062，因此主窗口整体未通过。

## 4. 2020—2023 隔离窗口

精确同窗：2020-01-02至2023-12-29，共1,006个交易日，12个目标episode。

| 策略 | CAGR | Sortino | 最大回撤 | Calmar |
|---|---:|---:|---:|---:|
| Frozen v4.2 | **34.46%** | **1.504** | -38.92% | **0.885** |
| Fixed cash residual | 30.98% | 1.429 | -38.68% | 0.801 |
| Defensive-only | 23.95% | 1.233 | -37.83% | 0.633 |
| Offensive-only | 33.09% | 1.476 | -38.68% | 0.856 |
| Joint donor budget | 25.95% | 1.286 | -37.83% | 0.686 |

Joint相对v4.2：

- CAGR -8.51个百分点；
- Calmar -0.200；
- 最大回撤改善1.09个百分点；
- 低概率episode共162个state-2交易日，显著削弱了2020—2023的盈利恢复。

隔离窗口中CAGR与Calmar同时为负，触发 contradiction gate。

## 5. 2024—2026 实际产品窗口

精确同窗：2024-01-30至2026-07-31，共613个交易日，12个 formal state-2 episode：

- low：5个；
- medium：2个；
- high：5个；
- 七个信号episode使用预注册median imputation；
- 模型覆盖率：100%。

| 策略 | CAGR | Sharpe | Sortino | 最大回撤 | Calmar | 换手 |
|---|---:|---:|---:|---:|---:|---:|
| Frozen v4.2 | **31.55%** | **1.201** | **1.728** | -24.67% | **1.279** | 55.0 |
| Fixed cash residual | 28.91% | 1.158 | 1.666 | -24.17% | 1.196 | 65.0 |
| Defensive-only | 28.14% | 1.170 | 1.698 | **-23.47%** | 1.199 | 65.0 |
| Offensive-only | 26.11% | 1.047 | 1.479 | -26.45% | 0.987 | 65.0 |
| Joint donor budget | 25.35% | 1.053 | 1.498 | **-27.45%** | 0.924 | 65.0 |

Joint相对v4.2：

- CAGR -6.20个百分点；
- Calmar -0.355；
- 最大回撤恶化2.79个百分点；
- Sortino明显下降；
- 三项 contradiction gate全部未通过。

高概率episode在2024年8—9月连续放大了短期亏损；低概率配置又在2025—2026部分强势episode中削弱了收益。该模型既未稳定识别防守episode，也未稳定识别应放大杠杆的episode。

## 6. 预注册门槛

### 6.1 Donor gate

通过：

- episode数量；
- 宏观簇数量；
- 样本集中度；
- LOAO AUC、IC、四分位差和正向资产数。

未通过：

- macro-cluster OOF AUC；
- macro-cluster OOF IC；
- macro-cluster OOF四分位差。

Donor gate整体失败。

### 6.2 Primary gate

通过：

- CAGR改善；
- 最大回撤约束；
- Sortino；
- 两个正相对收益年份；
- episode集中度；
- 换手；
- 对三组ablation的比较；
- 100%模型覆盖。

未通过：

- Calmar改善仅0.062，低于0.10门槛。

### 6.3 Contradiction gate

全部未通过：

- 2020—2023 CAGR和Calmar同时为负；
- 2024+ CAGR和Calmar同时为负；
- 实际最大回撤恶化2.79个百分点，高于2个百分点上限。

## 7. 独立审计

独立审计没有调用报告函数，直接从artifact CSV和JSON复算：

- manifest 52/52文件 SHA-256全部匹配；
- 205个donor episode和55个宏观簇复算一致；
- cluster-OOF AUC 0.5373529412、IC 0.0416821050、顶底差-0.0041228005复算一致；
- LOAO AUC 0.5985294118、IC 0.1260645485、顶底差0.0272228747复算一致；
- 三个目标scope逐日索引一致；
- 每日权重合计为1；
- state 0／state 1逐日权重与v4.2一致；
- 成本等于换手乘以10 bps；
- 所有策略的总收益、CAGR、最大回撤和Calmar复算一致。

审计结论：

`audit_pass_nonpromotion_result_valid`

## 8. 当前研究决策

保留：

- 205个donor formal state-2 episode库；
- macro-cluster与LOAO双重验证框架；
- 目标年度donor-only walk-forward；
- target episode全覆盖和median-imputation执行；
- state 0／state 1不变的SGOV/TQQQ runtime；
- 三段证据隔离框架。

拒绝：

- 当前14因子Logistic donor概率；
- 当前50%／75%／100% state-2映射；
- 根据2017—2019局部结果放宽Calmar门槛；
- 根据2020—2026反转概率；
- 搜索0.40／0.60阈值；
- 改变现金／TQQQ权重；
- 使用QQQ episode重新拟合。

v4.2继续作为唯一行动性研究基线和告警权重来源。v4.13不进入shadow。

下一步不应继续调整同一个分类器。真正仍然缺失的是**跨宏观regime的时间样本**，而不是资产episode数量。若继续研究，只能通过更长的、独立的历史周期或前瞻episode增加时间维度证据，例如经过实际重叠验证的机械日重置3x donor proxy；不能在2008—2026同一历史上继续修改模型与阈值。
