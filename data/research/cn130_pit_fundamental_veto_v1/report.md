# CN130 PIT基本面质量过滤与R0短名单实验

> 2022H2–2023H2只校准组件与架构；2024–2025只允许一次冻结验证。

## 最终裁决

- Decision: `fundamental_component_not_supported`
- Selected components: none
- Selected architecture: none
- 不自动创建CN x1.1；`research_only=true`。

## 组件校准

| Component | Mean IC | Incremental IC | Positive windows | Worst window | Spread | Sector share | Fiscal positive | Gate | Selected |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| inverse_leverage | 0.0167 | 0.0223 | 2/3 | -0.0265 | 0.43% | 48.3% | 2 | FAIL | NO |
| asset_turnover | 0.0057 | 0.0019 | 1/3 | -0.0201 | -0.14% | 40.4% | 3 | FAIL | NO |
| net_margin | -0.0273 | -0.0213 | 0/3 | -0.0438 | -0.48% | 32.7% | 1 | FAIL | NO |
| roe_proxy | -0.0343 | -0.0324 | 0/3 | -0.0462 | -0.89% | 34.4% | 1 | FAIL | NO |
| net_income_yoy_robust | -0.0503 | -0.0509 | 0/3 | -0.0643 | -0.80% | 38.5% | 0 | FAIL | NO |
| revenue_yoy | -0.0712 | -0.0704 | 0/3 | -0.0944 | -1.01% | 28.2% | 0 | FAIL | NO |

## 解释边界

- 组件和架构只从2022–2023校准。
- 若组件或架构校准失败，2024–2025不会用于选择。
- 2026只报告，不改变裁决。
- 当前池为静态研究池，仍存在生存者偏差。
