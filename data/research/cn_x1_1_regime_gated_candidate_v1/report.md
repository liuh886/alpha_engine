# CN x1.1 Candidate A — Regime-Gated Sector Breadth

**Decision:** `cn_x1_1_regime_gated_candidate_authorized`

## 授权结果

- Candidate authorized: True
- Candidate name: `CN x1.1 Candidate A — Regime-Gated Sector Breadth`
- Model rules changed: false
- Economic evidence changed: false
- Automatic production promotion: false
- `trade_ready=false`；本次仅授权研究候选，不自动替换生产基准。

## 冻结模型

- Risk-on：CN x1.0 R0分数 → 行业Top3广度 → 四行业 → 每行业Top1 → 四股等权。
- Risk-off：100% CSI300 fallback。
- 状态门：CSI300高于MA200、60日动量为正、CN130广度≥50%，三项两票通过。
- 十个交易日再平衡；延迟一个交易日执行；20bps/换手。

## 核心证据

- 2022H2—2025H2相对超额：54.93%
- 历史最大回撤：-24.44%
- 正超额半年：5/7
- Risk-on主动胜率：59.0%
- Risk-on占比：44.3%
- Risk-on相对超额：57.12%
- Risk-off相对超额：-1.39%，与显式成本拖累一致。
- 2026报告期相对超额：2.77%

## 评价合同修正

原合同把Risk-off的CSI300 fallback也要求逐期跑赢CSI300；扣除状态切换成本后，该要求在定义上不可满足。最终合同只将50%胜率门应用于Risk-on主动袖套，同时继续要求Risk-off表现不劣于显式成本拖累。其它门槛均未改变。

## 冻结经济证据身份

- `evaluation_summary.csv`: `fac8421e868d7f0e547abb9c799c2941cfeb51dc3d032edbef73fb87382b3c81`
- `half_year_results.csv`: `e3752b82dc96d162bcb5bb0fcfbcea7909a49a9accc67f05ed58617b9d3b3025`
- `holdings.csv`: `dc73b399b1dee8ce759f9e1c61535e650a83b31392ced3bda4560c233aa0b2d9`
- `model_spec.json`: `27809294e0fc5d5d2e3bb2dcaef3ad3cb31f99583b0854bf2079340d33f54a3c`
- `neighbor_rule_summary.csv`: `f4737e1d7a1d90329e490893ed42e0f475f3de3fed0f395c5c36930209df3a14`
- `rebalance_periods.csv`: `5fd1416596ab2a208ced0ecbea76ce6ad60e762c3342d4d082215adf4379adb7`
- `yearly_state_coverage.csv`: `288e9f182c2937efeb81440a06d8f4930aefbac104492230adcb931da9192771`

## 候选边界

- `at_least_two_neighbor_rules_positive`: PASS
- `both_states_present_2023_to_2025`: PASS
- `combined_2026_relative_excess_positive`: PASS
- `frozen_economic_identity_verified`: PASS
- `historical_40bps_relative_excess_positive`: PASS
- `historical_max_drawdown_above_minus_25pct`: PASS
- `historical_positive_half_years_at_least_5_of_7`: PASS
- `historical_relative_excess_positive`: PASS
- `historical_risk_on_active_hit_rate_at_least_50pct`: PASS
- `historical_worst_half_year_above_minus_10pct`: PASS
- `leave_one_top_name_positive`: PASS
- `leave_one_top_sector_positive`: PASS
- `risk_off_relative_no_worse_than_cost_drag`: PASS
- `risk_on_relative_excess_positive`: PASS
- `risk_on_share_between_25_and_80pct`: PASS

本候选仍基于固定CN130精选池，存在静态池生存者偏差。正式升级、前端接入和生产交易信号发布需另行明确决定。
