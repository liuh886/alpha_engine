# QQQ v4.29 VVIX state-0 二级防守研究结果

**Date:** 2026-08-07  
**Issue:** #627  
**Evidence workflow:** `31196763204`  
**Artifact:** `9001124632`  
**Digest:** `sha256:8345b5c3b40c14d32c7ef12921366f2a9cb7a307d958b2555a7382ae49ae3fa4`  
**Decision:** `vvix_drawdown_selector_promising_joint_gate_failed`

## 结论

VVIX 对近期急性冲击具有真实的回撤保护能力，但不能作为稳定的 v4.3 state-0 selector。

冻结的 `252-session rolling 80th percentile` VVIX stress 在实际 QQQI/SGOV 窗口显著降低回撤，却在 2010+ QQQ/BIL 长机制窗口降低 CAGR、恶化最大回撤和 Calmar。该结果说明 VVIX 更接近 **crash detector**，而不是稳定的 **bear-regime detector**。

因此：

- v4.2 继续作为正式研究基线和 alert source；
- v4.27 Panic Repair 继续作为当前最强的进攻型事件增强器，但仍是 research-only；
- v4.29 不进入 v4.3 candidate；
- 禁止在当前历史上搜索 VVIX percentile、rolling window、50/50 defensive weight、persistence/cooldown/delay；
- 下一阶段应寻找能识别持续熊市 / 慢风险状态的新信息，而不是继续叠加急性恐慌指标。

## Phase 0 数据审计

- Cboe VVIX 交易日覆盖率：**99.95%**；
- VVIX 历史范围：2006-03-06 至 2026-08-06；
- 2010-10-18 起的 QQQ 交易日历仅 2 个 VVIX 缺失日；
- actual SGOV open-to-open return coverage：**100%**；
- proxy BIL open-to-open return coverage：**100%**；
- 无 alternate provider、source splicing 或 forward fill。

## 实际 QQQI / SGOV 产品窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | VVIX guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | 34.05% | -24.21% | 1.272 | 1.846 | 1.406 | 56.0 | 0 |
| v4.27 Panic Repair | **37.79%** | -24.21% | 1.361 | 2.004 | 1.561 | 55.0 | 0 |
| v4.2 + VVIX state-0 defense | 31.31% | **-19.40%** | 1.277 | 1.823 | 1.614 | 81.0 | 76 |
| v4.27 + VVIX state-0 defense | **34.97%** | **-19.40%** | **1.372** | **1.992** | **1.802** | 80.0 | 76 |

Joint 相对 v4.2：

- CAGR：`+0.916 pp`；
- Max DD：改善 `+4.812 pp`；
- Calmar：`+0.396`。

实际窗口显示 VVIX selector 的回撤控制是真实的，但 CAGR 提升只差一点仍未达到预注册 `+1.00 pp` 门槛。

### 时间分段

Early segment：

- v4.2：CAGR 18.88%，Max DD -24.21%，Calmar 0.780；
- joint：CAGR 23.37%，Max DD -19.40%，Calmar 1.205。

Late segment：

- v4.2：CAGR 60.42%，Max DD -15.47%，Calmar 3.904；
- joint：CAGR 54.37%，Max DD -15.47%，Calmar 3.514。

因此 VVIX 在近期危机型阶段有保护价值，但在更顺畅的上涨阶段产生机会成本。

## 2010+ QQQ / BIL 长机制窗口

| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | VVIX guard sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | **25.72%** | **-38.92%** | **1.017** | **1.446** | **0.661** | 235.5 | 0 |
| v4.27 Panic Repair | 26.51% | -39.73% | 1.038 | 1.480 | 0.667 | 235.0 | 0 |
| v4.2 + VVIX state-0 defense | 21.35% | -42.03% | 0.935 | 1.328 | 0.508 | 462.5 | 572 |
| v4.27 + VVIX state-0 defense | 22.11% | **-42.76%** | 0.958 | 1.365 | 0.517 | 462.0 | 572 |

Joint 相对 v4.2：

- CAGR：`-3.608 pp`；
- Max DD：恶化 `-3.841 pp`；
- Calmar：`-0.144`。

Guard 分布在 16 个年份，最大单年只占约 11%，因此失败不是单一年份集中造成的，而是机制本身长期不稳定。

### 长历史时间分段

Early segment：

- v4.2：CAGR 17.74%，Max DD -27.56%，Calmar 0.644；
- joint：CAGR 14.65%，Max DD -26.59%，Calmar 0.551。

Late segment：

- v4.2：CAGR 38.70%，Max DD -38.92%，Calmar 0.994；
- joint：CAGR 34.22%，Max DD -42.76%，Calmar 0.800。

两个分段的 Calmar 都没有超过 v4.2。

## Episode 归因

长 proxy 共出现约 99 个 changed episodes。VVIX 有能力保护真正的急性冲击：

- 2020-02-19 → 2020-04-08：相对 v4.2 `+7.72%`；
- 2025-04-03 → 2025-05-13：`+4.56%`；
- 2018-03-20 → 2018-04-04：`+3.18%`；
- 2021-10-15 → 2021-12-08：`+3.06%`；
- 2022-02-11 → 2022-03-16：`+2.44%`。

但错误防守很多，典型机会成本包括：

- 2021-12-10 → 2021-12-27：`-4.04%`；
- 2020-10-29 → 2020-11-04：`-3.52%`；
- 2015-01-29 → 2015-02-13：`-2.55%`；
- 2012-12-31 → 2013-01-02：`-2.47%`；
- 2020-02-03 → 2020-02-05：`-2.39%`。

其结构是：VVIX 能识别“市场正在害怕波动”，但并不能稳定区分“持续熊市”与“恐慌后的快速修复”。把 state 0 机械切成 50% 现金，会在大量 relief rally / 快速恢复阶段损失 beta。

## 最大回撤诊断

长 proxy 的 v4.2 最大回撤：

- peak：2021-11-19；
- trough：2022-10-12；
- Max DD：-38.92%。

Joint 在相同 peak / trough 路径上恶化至 **-42.76%**。

因此 VVIX 并没有解决最关键的慢熊路径；它只是对其中少数急跌段有效。

## v4.3 candidate gate

| Gate | Result |
|---|---|
| actual CAGR delta >= +1.00 pp | FAIL |
| actual Max DD improvement >= +2.00 pp | PASS |
| actual Calmar delta >= +0.15 | PASS |
| proxy CAGR delta >= 0.00 pp | FAIL |
| proxy Max DD improvement >= +3.00 pp | FAIL |
| proxy Calmar delta >= +0.05 | FAIL |
| early/late chronological Calmar not worse | FAIL |
| largest positive episode share <= 50% | FAIL |
| proxy guard years >= 4 | PASS |
| largest guard-year share <= 50% | PASS |

不满足 v4.3 candidate 标准。

## 研究方向更新

当前 QQQ v-series 的结构性认识：

1. **进攻端**：v4.27 的 deep panic → v4.2 repair → temporary TQQQ boost 仍然是最有希望的新信息；
2. **state-2 防守端**：v4.28 已证明 VIX/VIX3M backwardation 与正式 state 2 零重叠，现有 VIX/VXN gating 已经足够；
3. **state-0 防守端**：主要回撤确实发生在 state 0，但 VVIX 只能识别 acute crash，不能稳定识别 slow bear；
4. 下一步需要的是 **慢风险 / 持续风险的独立信息**，不是更敏感的 volatility alarm。

下一条 admissible research 应优先审计长期、point-in-time-safe 的 **option tail pricing / skew** 或直接信用利差水平等真正新信息。任何新来源先做数据与信息增量 Phase 0，再允许进入 portfolio outcome experiment。
