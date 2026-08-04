# BYD / 515180 前瞻防守袖套账本

## 目标

历史研究支持 `v1_dividend_75_25_supported_historical`，但没有 fresh historical holdout。本账本只回答一个问题：在 2026-08-04 以后真实到达的数据上，用 515180 替代 canonical BYD V1.0 的 25% 现金袖套，是否持续优于完全相同风险预算下的现金基线。

本阶段不修改 BYD V1.0，不重新启用 V1.3，也不研究全仓 BYD/ETF 二元轮动。

## 冻结比较组

- `byd_v1_cash`：V1.0 为 75% 时保留 25% 现金；V1.0 为 100% 时全仓 BYD。
- `v1_dividend_75_25`：V1.0 为 75% 时配置 25% 515180；V1.0 为 100% 时全仓 BYD。
- `fixed_75_25`：固定 75% BYD + 25% 515180，仅作静态分散基准。

## 数据边界

BYD 不重新抓取。每个 paired observation 引用 `data/research/byd_prospective_shadow/observations/` 中已经封存的观察文件及 SHA-256。

515180 使用以下 immutable base：

- artifact ZIP SHA-256：`7e077664516b74546ec118f2bf0484ee650577a0898623f3f0cb8623397e061f`
- adjusted SHA-256：`2173afbe2fcbc8875de55ce0ff9bcb25b1c9f184c5cd273ade682244393c67a5`
- manifest SHA-256：`7f19639e6540ebb71eac7e52dab270df4b20b59bcf764c2dc6843045de21e4ec`
- cutoff：`2026-08-03`

新 ETF 行只使用供应商在截止日之后的相对路径，通过 2026-08-03 锚点 chain-link 到 canonical basis。历史行不得覆盖。独立未复权来源只用于确认，不拼接、不补值。

## 执行语义

- 收盘产生目标权重。
- 下一 BYD 与 515180 共同 independently confirmed eligible open 执行。
- 首个前瞻区间从现金开始。
- 非共同有效开盘不推进实际仓位。
- 20 bps 和 40 bps 两套成本。
- 换仓成本按 BYD、515180、现金三类权重的绝对变化总和计算。

## 不可变证据

每日 observation、成熟 horizon outcome 和完整 defense episode outcome 均保存为独立 JSON。已存在文件若字节变化，运行立即失败。`ledger.csv`、`scorecard.json` 和 `manifest.json` 都是可重建索引，不是数据源。

结算只允许使用 paired observation：

- 5、10、20 个共同有效开盘；
- 完整 V1.0 防守 episode；
- candidate 相对 cash baseline 的成本后增量收益。

## 再评估门槛

在讨论晋级前至少需要：

- 12 个月真正前瞻时间；
- 6 个完整防守 episode；
- 至少两个市场状态；
- 至少一个 515180 现金分红周期；
- 20 bps 下累计增量收益为正；
- 40 bps 下累计增量收益不为负；
- candidate Calmar 不低于 cash baseline；
- 最大单事件贡献不超过正增量的 40%；
- 最大单季度贡献不超过 60%。

事件不足时只能延长观察期，不降低门槛。

- `research_only=true`
- `trade_ready=false`
- `shadow_only=true`
