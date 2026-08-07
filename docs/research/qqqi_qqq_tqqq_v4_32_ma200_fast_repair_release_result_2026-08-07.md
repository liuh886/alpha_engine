# QQQ v4.32 MA200 慢熊防守 + Fast Repair Release 研究结果

**Date:** 2026-08-07  
**Issue:** #637  
**Evidence workflow:** `31199213453`  
**Artifact:** `9002121715`  
**Digest:** `sha256:ccfe83d4760ce08ee067e3464e588c49441e4f0965a9e1b3ceb9b65ed70f5651`  
**Decision:** `fast_release_defense_promising_gate_failed`

## 结论

v4.32 证明了 v4.31 的架构诊断是正确的：**慢变量决定进入强防守、快变量决定释放**，能够明显降低 v4.31 在 2025 快速修复阶段的机会成本，同时保留大部分 2022 慢熊保护。

但 `early_repair` 仍然是一个偏慢的 release gate。实际窗口已经达到“收益 + 回撤同时改善”，长历史后半段也非常强，但 2011–2020 的 proxy early half 仍因 V 型修复释放太慢而拖累 CAGR 和 Calmar，因此不能成为 retrospective v4.3 candidate。

不允许搜索 MA200、权重或 v4.27 参数。下一步仅允许把 release 简化到 v4.2 已有的更基础价格修复语义：

`NOT stress_price_failure AND (vix_easing OR vix_normalized)`

其中 `NOT stress_price_failure` 等价于 QQQ 已重新站上现有 MA20；不新增任何 MA 或阈值。

## 实际 QQQI / SGOV 产品窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | Guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | 34.05% | -24.21% | 1.272 | 1.846 | 1.406 | 56.0 | 0 |
| v4.27 Panic Repair | **37.79%** | -24.21% | 1.361 | 2.004 | 1.561 | 55.0 | 0 |
| v4.2 + v4.32 defense | 32.57% | **-21.65%** | 1.287 | 1.833 | 1.505 | 60.0 | 15 |
| v4.27 + v4.32 defense | **36.50%** | **-21.65%** | **1.387** | **2.008** | **1.686** | 58.5 | 15 |

Joint 相对 v4.2：

- CAGR：`+2.45 pp`；
- Max DD：改善 `+2.57 pp`；
- Calmar：`+0.280`。

实际窗口的收益、回撤、Calmar 三项 retrospective gate 均 PASS。

### 2025 冲突修复

v4.31 的实际 2025-04→05 joint changed episode 相对 v4.2 为约 `-1.63%`。

v4.32 使用 fast repair release 后：

- 2025-04-04 → 2025-04-25 的防守段缩短；
- 随后 v4.27 recovery boost 可以恢复；
- joint 2025-04-04 → 2025-05-13 changed episode 相对 v4.2 转为约 **`+2.24%`**。

2026-04 的 recovery episode 仍保持正贡献，约 `+2.34%`。

这证明“防守释放优先级”确实是 v4.31 的核心冲突，而不是 MA200 慢熊 selector 本身错误。

## QQQ / BIL 长机制窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | Guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | **25.72%** | -38.92% | 1.017 | 1.446 | 0.661 | 235.5 | 0 |
| v4.27 Panic Repair | 26.51% | -39.73% | 1.038 | 1.480 | 0.667 | 235.5 | 0 |
| v4.2 + v4.32 defense | 23.47% | **-29.63%** | 0.984 | 1.385 | **0.792** | 321.5 | 286 |
| v4.27 + v4.32 defense | 24.28% | **-30.55%** | 1.007 | 1.422 | **0.795** | 321.0 | 286 |

Joint 相对 v4.2：

- CAGR：`-1.44 pp`；
- Max DD：改善 **`+8.37 pp`**；
- Calmar：`+0.134`。

因此 slow-bear protection 被保留，而且回撤改善甚至略强于 v4.31；但长期 CAGR 仍未回到 v4.2。

## 时间稳定性

### Actual early 60%

- v4.2：CAGR 18.88%，Max DD -24.21%，Calmar 0.780；
- joint：CAGR 20.64%，Max DD -21.65%，Calmar **0.954**。

### Actual late 40%

- v4.2：CAGR 60.42%，Max DD -15.47%，Calmar 3.904；
- joint：CAGR 64.16%，Max DD -15.47%，Calmar **4.147**。

Actual 两段均改善。

### Proxy early 60%

- v4.2：CAGR 17.74%，Max DD -27.56%，Calmar **0.644**；
- joint：CAGR 13.63%，Max DD -26.89%，Calmar **0.507**。

### Proxy late 40%

- v4.2：CAGR 38.70%，Max DD -38.92%，Calmar 0.994；
- joint：CAGR 42.12%，Max DD -30.55%，Calmar **1.379**。

长期后半样本明显优于 v4.2，但 early half 仍失败，故 chronological gate FAIL。

## 为什么 `early_repair` 仍偏慢

v4.2 的 `early_repair` 不是简单的“价格重新站上 MA20”。它要求：

- early breakout；或
- QQQ > MA20 且 MA20 已经开始上升。

而 `stress_price_failure` 本身就是 `QQQ < MA20`。

因此在 2016、2020 等 V 型修复中，会出现：

- QQQ 已重新站上 MA20；
- VIX 已 easing / normalized；
- 但 MA20 尚未转升或 breakout 尚未完成；
- `early_repair = false`；
- v4.32 仍继续强防守数日。

典型负 episode：

- 2016-02-24 → 2016-03-02：约 `-3.39%`；
- 2020-03-23 → 2020-03-25：约 `-3.88%`；
- 2020-04-06 → 2020-04-07：约 `-3.13%`；
- 2011-08-19 → 2011-08-30：约 `-3.90%`。

这些不是 MA200 entry 错误，而是 release 仍晚于最基础的价格 / 波动率修复。

## Retrospective v4.3 candidate gate

PASS：

- actual CAGR；
- actual Max DD；
- actual Calmar；
- proxy Max DD；
- proxy Calmar；
- proxy guard years；
- actual / proxy turnover。

FAIL：

- proxy CAGR；
- chronological Calmar（proxy early）。

因此：

`retrospective_v4_3_candidate_supported = false`。

## 下一步：最后一个最简 release 结构

冻结下一条 admissible release：

`fast_price_vol_repair = NOT stress_price_failure AND (vix_easing OR vix_normalized)`

`strong_defense = ma200_falling AND NOT fast_price_vol_repair`

理由：

- MA200 falling 继续只负责慢熊 entry；
- QQQ 重新站上现有 MA20 表示最基础价格修复；
- VIX easing / normalized 提供波动率确认；
- 全部是 v4.2 已存在字段；
- 不新增 MA、阈值、lookback、权重、persistence 或 cooldown。

如果这个结构仍无法在 proxy early / late 同时成立，则关闭“单一 MA200 state-0 selector + deterministic release”路线，不再继续调 release 条件。

## Promotion boundary

即使下一条 retrospective experiment 全部通过，也只允许形成 `v4.3 retrospective candidate`。

正式 v4.3 必须经过一段没有参与 v4.27 / v4.31 / v4.32 设计的 prospective/shadow evidence，并由后续独立决策明确晋级。当前 v4.2 与 alert source 保持不变。
