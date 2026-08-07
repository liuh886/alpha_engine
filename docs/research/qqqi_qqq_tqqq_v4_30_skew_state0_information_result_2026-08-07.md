# QQQ v4.30 Cboe SKEW state-0 信息审计结果

**Date:** 2026-08-07  
**Issue:** #632  
**Evidence workflow:** `31197702404`  
**Artifact:** `9001519983`  
**Digest:** `sha256:7ec2ecbc21bf44249a0854c631fa4866f93078ab2a69c8e1641d45ca2e6a88cf`  
**Decision:** `skew_state0_information_not_stable`

## 结论

v4.30 修正了 v4.25 的一个数据状态认识，但没有产生可进入 portfolio 实验的 SKEW 风险因子。

### 数据状态更新

v4.25 当时只能确认 Cboe SKEW methodology，没有配置到可审计的 immutable numeric history，因此正确地阻止了 outcome model。

v4.30 重新只探测官方 Cboe daily-history endpoint 后确认：

- 官方 SKEW 数值历史现在可直接获取；
- first observation：**1990-01-02**；
- last observation：**2026-08-06**；
- 2010-10-18 起 QQQ 交易日历：3974 sessions；
- available：3969；missing：5；
- coverage：**99.87%**；
- maximum consecutive missing sessions：1；
- first-date 和 coverage gate 均 PASS；
- 无第三方历史、无 source splicing、无 forward fill。

因此 `option_tail_pricing/SKEW` 的“numeric history unresolved”数据阻塞已经解除。

### 但信息方向不成立

冻结定义：

`high SKEW = SKEW close >= point-in-time rolling 252-session 80th percentile`

只观察 executed formal v4.2 state 0；信号在 close 产生，forward path 从下一开盘以后第一个可执行 open-to-open return 开始。仅预注册 20d / 60d 两个慢风险 horizon。

结果没有支持“高 SKEW = 更危险的 state 0”。

## Full sample

| Group | Obs | Years | 20d median ret | 20d q10 ret | 20d median MaxDD | 60d median ret | 60d q10 ret | 60d median MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ordinary | 1357 | 14 | 1.50% | -5.41% | -3.48% | 4.37% | -8.09% | -6.24% |
| high SKEW | 380 | 12 | 1.33% | **-4.99%** | **-2.47%** | **5.37%** | **-2.44%** | **-4.79%** |

高 SKEW 的 20d/60d tail return 和 median MaxDD 反而整体更好。

## Early half

| Group | 20d q10 ret | 20d median MaxDD | 60d q10 ret | 60d median MaxDD |
|---|---:|---:|---:|---:|
| ordinary | -2.32% | -2.70% | -0.49% | -4.91% |
| high SKEW | -3.76% | -2.84% | -1.88% | **-4.67%** |

Early 只有 20d median MaxDD 符合原风险假设；60d 已不成立。

## Late half

| Group | 20d q10 ret | 20d median MaxDD | 60d q10 ret | 60d median MaxDD |
|---|---:|---:|---:|---:|
| ordinary | -7.91% | -4.97% | -12.84% | -11.09% |
| high SKEW | **-5.32%** | **-2.42%** | **-3.50%** | **-5.89%** |

Late half 的方向完全与“高 SKEW 是风险升级器”相反。

## Information gate

- high-SKEW years >= 8：PASS（12 years）；
- largest year share <= 35%：PASS（21.32%）；
- worse 20d median MaxDD early：PASS；
- worse 20d median MaxDD late：FAIL；
- worse 60d median MaxDD early：FAIL；
- worse 60d median MaxDD late：FAIL；
- worse q10 return in one horizon across both halves：FAIL；
- full-sample drawdown sign agreement：FAIL。

`portfolio_experiment_authorized = false`。

## 解释

SKEW 衡量的是期权市场中尾部风险定价 / 对冲需求，而不是“未来一定会发生更深下跌”。在本样本中，高 SKEW 很可能同时反映：

- 投资者已经为尾部保护付费；
- 尾部风险被更充分地价格化；
- 或者高 SKEW 经常发生于主体趋势仍然健康但保护需求偏高的环境。

无论机制解释如何，数据本身不支持把 `high SKEW` 当作 state-0 二级防守 selector。

更重要的是：**不允许在看到结果后把规则反转成 low-SKEW defense。** 这会成为典型的 post-result inversion。

## 研究纪律

关闭当前历史上的以下方向：

- SKEW absolute threshold search；
- rolling window / quantile search；
- high→low SKEW post-result inversion；
- 20d/60d horizon search；
- SKEW + VVIX / term structure / breadth / HYG-SHY 组合搜索。

本实验没有构建 portfolio，没有修改 v4.2、v4.27、alert source 或 Telegram。

## 下一步

v4.28 / v4.29 / v4.30 连续告诉我们同一个事实：

- state 2 风险已经被 v4.2 管得较好；
- acute fear / vol-of-vol 能抓 crash，但不能稳定管理慢熊；
- option tail pricing 也不是一个简单单调的 state-0 防守 selector。

下一步优先检查一个**不新增数据源、与慢熊定义直接一致的结构因子**：formal state 0 内的 long-term trend deterioration，例如 v4.2 已有 MA200 本身的下降方向。该实验只能使用现有 MA200 参数与一个结构性 sign rule，不能搜索 MA 窗口或斜率阈值。
