# CN130 横截面排序与轮动完整回测报告

> 研究保持 `cn_selected_equities_v3` 的130个成员不变，并严格采用“先验证排序、再决定是否开启轮动优化”的顺序。

## 执行身份

- Provider identity: `abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`
- 数据截止：2026-08-03。
- Universe SHA256: `4ce5b95e60d38a13e4852fb6f7a3a6437b55d6da0fb317ad553d114e85158529`。
- Classification SHA256: `d1ef3bd06c0953c7e78fa0ba99c372da714ddce67203909d195d73e9eec61d15`。
- `research_only=true`；`trade_ready=false`；静态池存在生存者偏差。

## 关键事实

1. R1 与 R0 的最低日度横截面秩相关为 1.000000，gain标签完全一致：True。减去同一天沪深300收益不会改变股票之间的顺序，因此 R1 没有新增信息。
2. PIT 市值覆盖为0%，完整 R3 被数据门槛阻断；成交额只作为流动性代理，R3 partial 不具备晋级资格。
3. 四个选择窗口中，没有候选同时满足正 Mean Rank IC、至少3/4窗口正 spread、且单一正窗口贡献低于50%。

## 排序候选汇总（2024H1–2025H2）

| 候选 | 特征族 | Mean Rank IC | Mean Rank ICIR | Mean Spread | 正Spread窗口 | 最大正窗口占比 | 基础门槛 |
|---|---|---:|---:|---:|---:|---:|---|
| r2_industry_relative_rank | momentum_reversal | 0.0096 | 0.033 | 0.86% | 2/4 | 66.3% | FAIL |
| r2_industry_relative_rank | current_cn_ohlcv | 0.0048 | 0.006 | 0.84% | 2/4 | 72.5% | FAIL |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | 0.0011 | 0.001 | 0.53% | 3/4 | 55.7% | FAIL |
| r1_benchmark_relative_rank | current_cn_ohlcv | 0.0011 | 0.001 | 0.53% | 3/4 | 55.7% | FAIL |
| r4_two_stage_hierarchical_rank | momentum_reversal | 0.0008 | 0.019 | 0.60% | 2/4 | 62.4% | FAIL |
| r3_risk_residual_rank | momentum_reversal | -0.0002 | -0.005 | 0.71% | 3/4 | 79.5% | FAIL |
| r4_two_stage_hierarchical_rank | current_cn_ohlcv | -0.0011 | -0.011 | 0.47% | 3/4 | 84.5% | FAIL |
| r2_industry_relative_rank | governed_technical_extension | -0.0053 | -0.033 | 0.74% | 3/4 | 66.1% | FAIL |
| r4_two_stage_hierarchical_rank | governed_technical_extension | -0.0061 | -0.056 | 0.38% | 2/4 | 76.5% | FAIL |
| r4_two_stage_hierarchical_rank | volume_volatility | -0.0077 | -0.058 | 0.39% | 4/4 | 87.8% | FAIL |
| r3_risk_residual_rank | volume_volatility | -0.0085 | -0.045 | 0.57% | 2/4 | 73.2% | FAIL |
| r2_industry_relative_rank | volume_volatility | -0.0095 | -0.046 | 0.58% | 3/4 | 73.0% | FAIL |
| r3_risk_residual_rank | governed_technical_extension | -0.0098 | -0.067 | 0.49% | 2/4 | 69.6% | FAIL |
| r3_risk_residual_rank | current_cn_ohlcv | -0.0129 | -0.074 | 0.36% | 2/4 | 60.0% | FAIL |

## 分窗口证据

| 窗口 | 候选 | 特征族 | Rank IC | Top–Bottom Spread |
|---|---|---|---:|---:|
| 2024H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | -0.0100 | 0.15% |
| 2024H1 | r1_benchmark_relative_rank | current_cn_ohlcv | -0.0100 | 0.15% |
| 2024H1 | r2_industry_relative_rank | current_cn_ohlcv | -0.0374 | -0.49% |
| 2024H1 | r2_industry_relative_rank | governed_technical_extension | -0.0682 | -0.61% |
| 2024H1 | r2_industry_relative_rank | momentum_reversal | -0.0368 | -0.52% |
| 2024H1 | r2_industry_relative_rank | volume_volatility | -0.0289 | -0.62% |
| 2024H1 | r3_risk_residual_rank | current_cn_ohlcv | -0.0556 | -0.93% |
| 2024H1 | r3_risk_residual_rank | governed_technical_extension | -0.0530 | -0.65% |
| 2024H1 | r3_risk_residual_rank | momentum_reversal | -0.0696 | -0.77% |
| 2024H1 | r3_risk_residual_rank | volume_volatility | -0.0710 | -1.16% |
| 2024H1 | r4_two_stage_hierarchical_rank | current_cn_ohlcv | -0.0180 | 0.05% |
| 2024H1 | r4_two_stage_hierarchical_rank | governed_technical_extension | -0.0374 | -0.23% |
| 2024H1 | r4_two_stage_hierarchical_rank | momentum_reversal | -0.0214 | -0.05% |
| 2024H1 | r4_two_stage_hierarchical_rank | volume_volatility | -0.0092 | 0.09% |
| 2024H2 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | -0.0528 | -0.34% |
| 2024H2 | r1_benchmark_relative_rank | current_cn_ohlcv | -0.0528 | -0.34% |
| 2024H2 | r2_industry_relative_rank | current_cn_ohlcv | -0.0559 | -0.22% |
| 2024H2 | r2_industry_relative_rank | governed_technical_extension | -0.0381 | 0.00% |
| 2024H2 | r2_industry_relative_rank | momentum_reversal | -0.0546 | -0.48% |
| 2024H2 | r2_industry_relative_rank | volume_volatility | -0.0243 | 0.31% |
| 2024H2 | r3_risk_residual_rank | current_cn_ohlcv | -0.0725 | -0.41% |
| 2024H2 | r3_risk_residual_rank | governed_technical_extension | -0.0550 | -0.30% |
| 2024H2 | r3_risk_residual_rank | momentum_reversal | -0.0273 | 0.10% |
| 2024H2 | r3_risk_residual_rank | volume_volatility | -0.0711 | -0.28% |
| 2024H2 | r4_two_stage_hierarchical_rank | current_cn_ohlcv | -0.0391 | -0.23% |
| 2024H2 | r4_two_stage_hierarchical_rank | governed_technical_extension | -0.0344 | -0.17% |
| 2024H2 | r4_two_stage_hierarchical_rank | momentum_reversal | -0.0369 | -0.12% |
| 2024H2 | r4_two_stage_hierarchical_rank | volume_volatility | -0.0215 | 0.03% |
| 2025H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | 0.0544 | 1.38% |
| 2025H1 | r1_benchmark_relative_rank | current_cn_ohlcv | 0.0544 | 1.38% |
| 2025H1 | r2_industry_relative_rank | current_cn_ohlcv | 0.0360 | 1.12% |
| 2025H1 | r2_industry_relative_rank | governed_technical_extension | 0.0393 | 1.21% |
| 2025H1 | r2_industry_relative_rank | momentum_reversal | 0.0519 | 1.50% |
| 2025H1 | r2_industry_relative_rank | volume_volatility | 0.0022 | 0.49% |
| 2025H1 | r3_risk_residual_rank | current_cn_ohlcv | 0.0362 | 1.11% |
| 2025H1 | r3_risk_residual_rank | governed_technical_extension | 0.0109 | 0.88% |
| 2025H1 | r3_risk_residual_rank | momentum_reversal | 0.0116 | 0.63% |
| 2025H1 | r3_risk_residual_rank | volume_volatility | 0.0234 | 1.00% |
| 2025H1 | r4_two_stage_hierarchical_rank | current_cn_ohlcv | 0.0165 | 0.28% |
| 2025H1 | r4_two_stage_hierarchical_rank | governed_technical_extension | 0.0289 | 0.45% |
| 2025H1 | r4_two_stage_hierarchical_rank | momentum_reversal | 0.0334 | 0.96% |
| 2025H1 | r4_two_stage_hierarchical_rank | volume_volatility | -0.0106 | 0.07% |
| 2025H2 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | 0.0129 | 0.95% |
| 2025H2 | r1_benchmark_relative_rank | current_cn_ohlcv | 0.0129 | 0.95% |
| 2025H2 | r2_industry_relative_rank | current_cn_ohlcv | 0.0766 | 2.95% |
| 2025H2 | r2_industry_relative_rank | governed_technical_extension | 0.0458 | 2.36% |
| 2025H2 | r2_industry_relative_rank | momentum_reversal | 0.0778 | 2.95% |
| 2025H2 | r2_industry_relative_rank | volume_volatility | 0.0130 | 2.14% |
| 2025H2 | r3_risk_residual_rank | current_cn_ohlcv | 0.0403 | 1.67% |
| 2025H2 | r3_risk_residual_rank | governed_technical_extension | 0.0578 | 2.02% |
| 2025H2 | r3_risk_residual_rank | momentum_reversal | 0.0847 | 2.86% |
| 2025H2 | r3_risk_residual_rank | volume_volatility | 0.0844 | 2.72% |
| 2025H2 | r4_two_stage_hierarchical_rank | current_cn_ohlcv | 0.0361 | 1.80% |
| 2025H2 | r4_two_stage_hierarchical_rank | governed_technical_extension | 0.0186 | 1.47% |
| 2025H2 | r4_two_stage_hierarchical_rank | momentum_reversal | 0.0280 | 1.59% |
| 2025H2 | r4_two_stage_hierarchical_rank | volume_volatility | 0.0104 | 1.36% |

## 2026 报告窗口（不参与选择）

2026H1 已被此前研究消费；2026H2 仅含截至2026-08-03可实现的前瞻样本。二者只用于观察，不改变排序裁决。

| 窗口 | 候选 | 特征族 | 有效日期 | Rank IC | Top–Bottom Spread |
|---|---|---|---:|---:|---:|
| 2026H1 | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | 116 | 0.0784 | 3.99% |
| 2026H1 | r1_benchmark_relative_rank | current_cn_ohlcv | 116 | 0.0784 | 3.99% |
| 2026H1 | r2_industry_relative_rank | current_cn_ohlcv | 116 | 0.0720 | 4.08% |
| 2026H1 | r2_industry_relative_rank | governed_technical_extension | 116 | 0.0805 | 4.06% |
| 2026H1 | r2_industry_relative_rank | momentum_reversal | 116 | 0.0773 | 3.88% |
| 2026H1 | r2_industry_relative_rank | volume_volatility | 116 | 0.0406 | 3.26% |
| 2026H1 | r4_two_stage_hierarchical_rank | current_cn_ohlcv | 116 | 0.0309 | 1.68% |
| 2026H1 | r4_two_stage_hierarchical_rank | governed_technical_extension | 116 | 0.0240 | 1.80% |
| 2026H1 | r4_two_stage_hierarchical_rank | momentum_reversal | 116 | 0.0442 | 1.98% |
| 2026H1 | r4_two_stage_hierarchical_rank | volume_volatility | 116 | 0.0024 | 1.26% |
| 2026H2_PARTIAL | r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | 13 | -0.5497 | -18.70% |
| 2026H2_PARTIAL | r1_benchmark_relative_rank | current_cn_ohlcv | 13 | -0.5497 | -18.70% |
| 2026H2_PARTIAL | r2_industry_relative_rank | current_cn_ohlcv | 13 | -0.5771 | -18.75% |
| 2026H2_PARTIAL | r2_industry_relative_rank | governed_technical_extension | 13 | -0.5730 | -19.34% |
| 2026H2_PARTIAL | r2_industry_relative_rank | momentum_reversal | 13 | -0.3467 | -11.81% |
| 2026H2_PARTIAL | r2_industry_relative_rank | volume_volatility | 13 | -0.5970 | -20.68% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | current_cn_ohlcv | 13 | -0.2877 | -10.33% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | governed_technical_extension | 13 | -0.2818 | -9.45% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | momentum_reversal | 13 | -0.1853 | -7.01% |
| 2026H2_PARTIAL | r4_two_stage_hierarchical_rank | volume_volatility | 13 | -0.2753 | -10.35% |

2026H1 的全面转强与 2026H2 部分窗口的全面反转共同说明：信号方向高度依赖市场状态。R4-momentum 在2026H2将 Rank IC 从 R0 的约 -0.550 缓和至约 -0.185，但仍未恢复为正。

## 诊断性 Top15 经济结果

这些结果仅用于说明排序统计与组合收益可能脱钩，不用于反向选择模型，也未开启 P1–P5 轮动搜索。

| 候选 | 特征族 | 资格 | 成本 | 总收益 | 沪深300 | 复合相对超额 | 最大回撤 | 正超额窗口 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| r2_industry_relative_rank | current_cn_ohlcv | eligible | 20bps | 109.98% | 39.29% | 50.75% | -27.86% | 3/4 |
| r2_industry_relative_rank | volume_volatility | eligible | 20bps | 108.33% | 39.29% | 49.57% | -27.29% | 3/4 |
| r3_risk_residual_rank | momentum_reversal | ineligible_partial_r3 | 20bps | 87.57% | 39.29% | 34.66% | -24.48% | 3/4 |
| r2_industry_relative_rank | momentum_reversal | eligible | 20bps | 85.51% | 39.29% | 33.18% | -20.39% | 2/4 |
| r0_cn_x1_0_raw_return_rank | current_cn_ohlcv | eligible | 20bps | 84.71% | 39.29% | 32.61% | -21.60% | 4/4 |
| r1_benchmark_relative_rank | current_cn_ohlcv | eligible | 20bps | 84.71% | 39.29% | 32.61% | -21.60% | 4/4 |
| r3_risk_residual_rank | governed_technical_extension | ineligible_partial_r3 | 20bps | 76.81% | 39.29% | 26.93% | -29.15% | 2/4 |
| r4_two_stage_hierarchical_rank | volume_volatility | eligible | 20bps | 74.50% | 39.29% | 25.27% | -17.76% | 3/4 |
| r3_risk_residual_rank | current_cn_ohlcv | ineligible_partial_r3 | 20bps | 73.85% | 39.29% | 24.81% | -23.69% | 3/4 |
| r2_industry_relative_rank | governed_technical_extension | eligible | 20bps | 70.83% | 39.29% | 22.64% | -32.60% | 2/4 |
| r4_two_stage_hierarchical_rank | governed_technical_extension | eligible | 20bps | 69.17% | 39.29% | 21.45% | -27.14% | 2/4 |
| r4_two_stage_hierarchical_rank | momentum_reversal | eligible | 20bps | 63.78% | 39.29% | 17.58% | -20.36% | 2/4 |
| r4_two_stage_hierarchical_rank | current_cn_ohlcv | eligible | 20bps | 62.40% | 39.29% | 16.59% | -20.96% | 3/4 |
| r3_risk_residual_rank | volume_volatility | ineligible_partial_r3 | 20bps | 39.20% | 39.29% | -0.07% | -25.11% | 2/4 |

## 最终裁决

- Decision: `cn130_cross_sectional_ranking_not_supported`。
- 没有冻结排序胜者，因此遵守预注册 stop rule，P1–P5 轮动组合没有进入正式比较。
- CN x1.1 candidate：否；自动升级：否。

## 结论

固定 CN130 并不是当前失败的主要原因。核心问题是信号具有明显的窗口依赖：2024年多数候选方向错误，2025年尤其2025H2又明显转强。行业相对标签能在2025H2改善排序，但无法修复2024年的失效；两阶段R4降低行业集中，却同时稀释了有效窗口的分离度。部分Top15组合仍取得较高收益，恰恰说明组合收益可能来自行业Beta、集中暴露或窗口路径，不能替代横截面排序证据。现阶段不能把这些结果解释为稳定的行业轮动能力。

## 限制

- 当前结果只对绑定的2026-08-03 provider快照成立；Issue #345 的快照漂移仍未解除。
- 静态精选池存在生存者偏差。
- 2026H1已消费、2026H2不完整，未进入模型选择。
- 完整R3需要PIT市值/股本数据后重新预注册。
