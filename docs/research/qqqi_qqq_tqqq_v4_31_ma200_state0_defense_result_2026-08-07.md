# QQQ v4.31 Falling-MA200 state-0 二级防守研究结果

**Date:** 2026-08-07  
**Issue:** #635  
**Evidence workflow:** `31198407170`  
**Artifact:** `9001802761`  
**Digest:** `sha256:2dc49bc244081ab66a91f52d5f81b83007384fd6176f69219b14284904dfa23d`  
**Decision:** `ma200_drawdown_selector_promising_joint_gate_failed`

## 结论

v4.31 首次证明了一个能在长历史稳定识别 **persistent bear** 的 state-0 慢风险 selector：现有 v4.2 SMA(200) 的下降方向。

但冻结的“MA200 下行期间持续 50% Treasury-bill 防守，直到 MA200 自己重新上升”退出逻辑过慢，在快速修复阶段产生明显机会成本，因此 joint 仍未达到 v4.3 candidate gate。

因此：

- `MA200 falling` 作为 **进入二级防守的慢变量**值得保留；
- “等待 MA200 转升再释放防守”作为退出逻辑被否决；
- 不允许搜索 MA 窗口、斜率 lookback / magnitude、50/50 权重、确认天数；
- 下一条 admissible architecture 只允许使用现有 v4.2 fast-repair 语义改善释放时机，不新增阈值。

## 冻结规则

- `ma200_falling_at_close = ma_long[t] < ma_long[t-1]`；
- `ma_long` 直接复用 v4.2 已有 QQQ SMA(200)；
- signal close，next open execution；
- only executed formal state 0；
- actual：50% QQQI / 50% SGOV；
- proxy：50% QQQ / 50% BIL；
- state 1 / state 2 完全不变；
- 与 v4.27 组合时，本实验采用 defense precedence；
- 10 bps / turnover unit。

## 实际 QQQI / SGOV 产品窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | Guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | 34.05% | -24.21% | 1.272 | 1.846 | 1.406 | 56.0 | 0 |
| v4.27 Panic Repair | **37.79%** | -24.21% | **1.361** | **2.004** | 1.561 | 55.0 | 0 |
| v4.2 + falling-MA200 defense | 31.80% | **-21.65%** | 1.265 | 1.798 | 1.469 | 57.0 | 20 |
| v4.27 + falling-MA200 defense | 34.41% | **-21.65%** | 1.333 | 1.916 | **1.590** | 56.0 | 20 |

Joint 相对 v4.2：

- CAGR `+0.36 pp`；
- Max DD 改善 `+2.57 pp`；
- Calmar `+0.183`。

因此实际窗口已经同时改善回撤和风险调整收益，但没有达到预注册 `CAGR +1.00 pp` 门槛。

### 实际冲突路径

MA200 defense 在实际窗口只触发一个主要 episode：

- 2025-04-04 → 2025-05-02，20 sessions；
- 单独 MA200 defense 相对 v4.2：`-4.16%`；
- 这段正是 2025 crash 后快速修复，MA200 因长期滞后仍然下行，导致现金防守错失反弹。

Joint changed episode：

- 2025-04-04 → 2025-05-13：相对 v4.2 `-1.63%`；
- 2026-04-07 → 2026-04-10：`+2.34%`。

说明 v4.31 的主要问题不是进入防守，而是防守释放太晚并压制了 v4.27 recovery boost。

## QQQ / BIL 长机制窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | Guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | **25.72%** | -38.92% | 1.017 | 1.446 | 0.661 | 235.5 | 0 |
| v4.27 Panic Repair | 26.51% | -39.73% | 1.038 | 1.480 | 0.667 | 235.5 | 0 |
| v4.2 + falling-MA200 defense | 23.54% | **-29.88%** | 0.990 | 1.394 | **0.788** | 287.5 | 370 |
| v4.27 + falling-MA200 defense | 24.17% | -30.80% | 1.009 | 1.423 | 0.784 | 287.5 | 370 |

Joint 相对 v4.2：

- CAGR `-1.55 pp`；
- Max DD 改善 **`+8.12 pp`**；
- Calmar `+0.124`。

这与 v4.29 VVIX 的长历史失败形成鲜明对比：MA200 falling 确实识别到了慢熊风险。

### 关键正贡献：2022 slow bear

MA200 defense 最大正贡献 episode：

- 2022-04-12 → 2023-01-26；
- 199 sessions；
- candidate return `-6.28%`；
- v4.2 return `-15.03%`；
- 相对收益 **`+10.30%`**。

这正是我们寻找的 persistent-bear protection。

### 快速修复中的机会成本

典型负 episode：

- 2011-08-19 → 2011-08-30：`-3.90%`；
- 2020-03-23 → 2020-03-25：`-3.88%`；
- 2020-04-06 → 2020-04-07：`-3.13%`；
- 2012-12-31 → 2013-01-02：`-2.70%`；
- 2011-08-09 → 2011-08-12：`-2.57%`。

共同特征：市场已经开始快速 repair，但 MA200 作为 200 日慢变量仍然下降。

## 时间稳定性

Proxy early：

- v4.2：CAGR 17.74%，Max DD -27.56%，Calmar 0.644；
- joint：CAGR 14.03%，Max DD -26.89%，Calmar 0.522。

Proxy late：

- v4.2：CAGR 38.70%，Max DD -38.92%，Calmar 0.994；
- joint：CAGR 41.06%，Max DD -30.80%，Calmar 1.333。

Selector 在后半样本尤其 2022 显著有效，但 early half 的快速修复机会成本使 chronological gate 失败。

## v4.3 candidate gate

PASS：

- actual Max DD；
- actual Calmar；
- proxy Max DD；
- proxy Calmar；
- proxy guard years（11 years）；
- actual / proxy turnover。

FAIL：

- actual CAGR；
- proxy CAGR；
- chronological Calmar；
- event concentration；
- guard-year concentration（最大年份约 50.81%）。

因此 `v4_3_candidate_supported = false`。

## 新的架构认识

v4.31 不是“MA200 因子失败”，而是明确拆出了 **entry 与 exit 的时间尺度必须不同**：

- **Entry**：MA200 falling 是有价值的慢熊识别器；
- **Exit**：MA200 rising 太迟，不能作为 recovery release；
- **Fast release** 应该复用已经成熟的 v4.2 repair 语义，而不是新增参数。

下一轮只允许测试一个结构：

> `state0 AND MA200 falling AND NOT repair_ready -> strong defense`

其中 `repair_ready` 完全复用：

`early_repair AND NOT stress_price_failure AND (vix_easing OR vix_normalized)`。

当 repair_ready 出现时，下一开盘立即恢复 source allocation；若 repair 再次失败且 MA200 仍下行，二级防守可重新生效。

该结构不改变任何 MA / VIX 阈值、任何资产权重，也不改变 formal v4.2 state trace。
