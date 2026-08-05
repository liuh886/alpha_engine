# CN x1.1 Fallback-Aware 候选认证

Issue: #575  
Source model: #573 / Draft PR #574.

## 认证对象

`CN x1.1 Candidate A — Regime-Gated Sector Breadth`

本轮不得改变模型、阈值、持仓、收益、状态、成本、窗口或数据源。七个核心经济文件必须与#573 artifact逐字节一致。

## 修正内容

原评价合同要求整个组合在至少50%的再平衡期跑赢CSI300。但Risk-off状态的设计目标就是持有CSI300；扣除状态切换成本后，这些期间不可能净跑赢CSI300。

因此只做一项语义修正：

- 删除：`historical_all_period_hit_rate_at_least_50pct`；
- 增加：`historical_risk_on_active_hit_rate_at_least_50pct`。

Risk-off仍需满足：相对表现不劣于显式交易成本拖累。

## 冻结身份

来源：workflow `31021964502`，artifact `8936993760`。

必须保持不变：

- model_spec；
- evaluation summary；
- half-year results；
- yearly state coverage；
- neighboring rules；
- rebalance periods；
- holdings。

哈希在配置文件和Issue #575中固定。任何不一致直接阻断认证。

## 授权边界

全部修正后门槛通过时，授权：

`CN x1.1 Candidate A — Regime-Gated Sector Breadth`

授权含义：形成正式研究候选。它不自动替换生产基准，不自动接入实时信号，`trade_ready=false`；正式升级需用户另行确认。
