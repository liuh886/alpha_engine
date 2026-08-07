# QQQ v4.28 波动率期限结构研究结果

**Date:** 2026-08-07  
**Issue:** #623  
**Evidence workflow:** `31195685168`  
**Artifact:** `9000694021`  
**Digest:** `sha256:86e856dd71cd9cc502fbb61d64270eec96397bdfb2e4ae13166b414426843ff0`  
**Decision:** `v4_28_term_structure_not_supported`

## 结论

v4.28 不支持进入 v4.3 candidate，也不支持继续搜索 VIX9D/VIX、VIX/VIX3M 阈值或 state-2 cap 权重。

两个预注册因子都没有给 v4.2 带来独立、稳定的新增价值：

1. `VIX9D < VIX` 对 v4.27 Panic Repair 的确认只在 2025-04 事件中把 boost 推迟一个交易日，减少了收益；
2. `VIX > VIX3M` 虽然在 2014+ proxy 样本中出现 300 个交易日，但与正式 executed state 2 的交集为 **0**，因此 50% TQQQ cap 从未触发；
3. 这说明 v4.2 现有 VIX/VXN normalization 已经在进入 state 2 之前排除了 backwardation 风险，期限结构 guard 在当前架构中是冗余信息；
4. joint candidate 的表面收益提升几乎完全来自已经存在的 v4.27 Panic Repair，而不是新期限结构因子。

因此 v4.2 继续作为正式研究基线和 alert source；v4.27 继续作为最有希望的进攻型事件增强器，但仍不是正式模型。

## Phase 0 数据审计

Cboe 官方 VIX9D / VIX3M 数据通过预注册的数据门：

| 指数 | 2014+ QQQ 交易日覆盖率 | 首个历史值 | 截止 |
|---|---:|---|---|
| VIX9D | 100.00% | 2011-01-04 | 2026-08-06 |
| VIX3M | 100.00% | 2009-09-18 | 2026-08-06 |

主机制窗口从 2014-01-01 起算，避免把 VIX9D 2013 年 launch 前的 back-calculated history 当作当时可观察信息。

## 实际 QQQI 产品窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|
| v4.2 | 34.05% | -24.21% | 1.272 | 1.846 | 1.406 | 56.0 |
| v4.27 Panic Repair | **37.79%** | -24.21% | **1.361** | **2.004** | **1.561** | 55.0 |
| v4.27 + VIX9D timing | 37.42% | -24.21% | 1.351 | 1.989 | 1.546 | 55.0 |
| v4.2 + backwardation guard | 34.05% | -24.21% | 1.272 | 1.846 | 1.406 | 56.0 |
| joint | 37.42% | -24.21% | 1.351 | 1.989 | 1.546 | 55.0 |

v4.27 的两个实际 boost episode：

- 2025-04-25 → 2025-05-12：相对 v4.2 `+4.62%`；
- 2026-04-07 → 2026-04-09：相对 v4.2 `+2.29%`。

加入 VIX9D timing 后，第一个 episode 延迟到 2025-04-28，贡献降至 `+3.93%`；第二个 episode 不变。

## 2014+ QQQ proxy 机制窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|
| v4.2 | 26.82% | **-38.92%** | 1.025 | 1.463 | 0.689 | 188.0 |
| v4.27 Panic Repair | **27.82%** | -39.73% | **1.051** | **1.505** | **0.700** | 188.0 |
| v4.27 + VIX9D timing | 27.76% | -39.73% | 1.049 | 1.502 | 0.699 | 188.0 |
| v4.2 + backwardation guard | 26.82% | **-38.92%** | 1.025 | 1.463 | 0.689 | 188.0 |
| joint | 27.76% | -39.73% | 1.049 | 1.502 | 0.699 | 188.0 |

v4.27 的三个可靠 CNN-history proxy episode 均为正：

- 2021-10-15 → 2021-11-26：`+3.53%`；
- 2025-04-25 → 2025-05-12：`+4.25%`；
- 2026-04-07 → 2026-04-09：`+2.15%`。

但长期 proxy 最大回撤从 -38.92% 变为 -39.73%，说明 v4.27 是进攻增强器，不是回撤控制器。

## v4.3 gate

预注册 gate：

- actual CAGR：PASS；
- actual Max DD：PASS；
- actual Calmar：PASS；
- proxy CAGR：PASS；
- proxy Max DD：**FAIL**；
- chronological Calmar：PASS；
- event concentration：**FAIL**。

Joint 相对 v4.2：

- actual CAGR `+3.37 pp`；
- actual Max DD `0.00 pp`；
- actual Calmar `+0.139`；
- proxy CAGR `+0.93 pp`；
- proxy Max DD `-0.80 pp`（恶化）；
- 最大正贡献 episode 占全部正贡献 `63.14%`。

不满足 v4.3 candidate 标准。

## 新的结构性认识：回撤主要不是 state 2 问题

从 v4.28 evidence 的 v4.2 daily trace 重新归因：

### 实际产品最大回撤

- peak：2024-12-16；
- trough：2025-04-04；
- Max DD：-24.21%；
- 期间 75 个交易日中：state 0 = **70**，state 1 = 2，state 2 = 3；
- state 0 子路径复合收益约 `-16.75%`。

### 2014+ proxy 最大回撤

- peak：2021-11-19；
- trough：2022-10-12；
- Max DD：-38.92%；
- 期间 225 个交易日中：state 0 = **220**，state 1 = 3，state 2 = 2；
- state 0 子路径复合收益约 `-32.51%`。

因此继续管理 state 2 杠杆不是当前最大缺口。真正未解决的问题是：

> **v4.2 已经知道什么时候进入 defensive state 0，但 state 0 仍保持 100% QQQI 的权益 beta。模型需要一个独立因子判断何时把 state 0 升级为更强的现金 / SGOV 防守。**

## 下一步研究边界

关闭以下方向，不再在当前历史上调参：

- VIX9D/VIX threshold search；
- VIX/VIX3M threshold search；
- backwardation state-2 cap 权重搜索；
- 期限结构 smoothing / persistence / delay 搜索。

下一条 admissible hypothesis 使用 **VVIX（vol-of-vol）** 作为独立尾部风险信息，研究其能否在 state 0 内识别需要二级防守的高风险子状态。

VVIX 与当前因子族的角色不同：VIX/VXN 表示预期波动水平，VIX9D/VIX3M 表示期限结构，而 VVIX 表示 VIX 自身未来波动的不确定性。第一轮只允许一个点时安全的 frozen stress definition 和一个固定防守风险预算，不做阈值/权重 grid。
