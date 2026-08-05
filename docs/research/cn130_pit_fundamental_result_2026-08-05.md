# CN130 PIT基本面行业内选股实验结果

Date: 2026-08-05  
Issue: #542  
Draft PR: #543  
Price provider cutoff: 2026-08-03  
Status: completed on frozen PIT inputs  
Boundary: `research_only=true`, `trade_ready=false`

## Research question

此前研究已经拒绝完整CN130横截面排序、简单现金门槛和静态技术因子的市场状态条件化，但保留了一个稳定的组合转换基线：

`R0 score -> four sectors by top-three score breadth -> Top1 security per sector -> equal weight`

本轮不再调整行业选择或仓位，而只检验一个新信息问题：PIT基本面能否改善四个已选行业中的Top1选择。

## Immutable inputs

- CN130成员不变；
- 10个A股交易日持有期，延迟一个交易日执行；
- 价格provider identity：`abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`；
- PIT基本面事件SHA256：`9d0babbf78a9a95272c15a94b56306194ff0a320d4fb92de4f7f78951fc7b8c7`；
- 基本面事实来自Sina财务报表，并以CNINFO定期报告披露日期作为`available_at`；
- 2024H1、2024H2、2025H1、2025H2为冻结验证窗口；
- 2026H1与2026H2_PARTIAL仅报告；
- 交易成本测试为10、20、40bps。

## Stage 0 — PIT coverage

数据资格门槛通过：

- 130只股票中128只有基本面事件，来源覆盖率98.46%；
- 缺失标的仅为`301666`、`688521`；
- 四个验证窗口共50个再平衡日期全部通过覆盖门槛；
- 每个日期的全池可用率约96.9%–100%；
- 已选行业的最低覆盖率约91.4%–100%；
- 2019年以后各主要财务期的中位有效组件数为6。

因此，本轮失败不能归因于基本面缺失或fallback频繁触发。

## Predeclared candidates

- `F0_r0_sector_4x1`：既有R0行业内Top1基线；
- `F1_fundamental_top1`：R0选择行业，基本面综合分选择行业Top1；
- `F2_half_blend`：行业内R0与基本面排名各50%；
- `F3_half_blend_fallback`：F2在行业覆盖不足时回退R0。

基本面综合分等权包含：营收同比、稳健净利润同比、净利率、ROE代理、资产周转率、逆杠杆和披露新鲜度。字段、方向、权重和覆盖阈值均在验证前冻结。

## Selection results at 20bps

| Candidate | Relative excess | Increment vs F0 | 40bps excess | Max drawdown | Worst window | Positive windows | Precision@4 | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| F0 R0 sector 4x1 | **+67.34%** | — | **+53.59%** | -18.38% | +7.30% | 4/4 | 50.5% | baseline |
| F1 fundamental Top1 | +12.90% | -54.43% | +7.65% | -31.85% | -10.95% | 2/4 | 49.5% | fail |
| F2 50/50 blend | -17.61% | -84.94% | -23.32% | -34.87% | -10.09% | 1/4 | 43.5% | fail |
| F3 blend + fallback | -17.61% | -84.94% | -23.32% | -34.87% | -10.09% | 1/4 | 43.5% | fail |

### Window evidence

F1 fundamental Top1:

- 2024H1: -10.95% relative excess;
- 2024H2: -0.34%;
- 2025H1: +5.44%;
- 2025H2: +20.65%.

F2/F3:

- 2024H1: -10.09%;
- 2024H2: -4.82%;
- 2025H1: -5.12%;
- 2025H2: +1.48%.

The pure fundamental rule becomes stronger only in the later validation windows. The equal-rank blend does not interpolate between F0 and F1; it repeatedly selects compromise names that are not at the extreme tail of either signal.

## Robustness

F1 remains positive after removing its largest name or sector contributor, but only narrowly:

- leave-one-name relative excess: +4.56%;
- leave-one-sector relative excess: +3.84%.

This is far below the F0 baseline:

- leave-one-name: +52.59%;
- leave-one-sector: +24.35%.

F2/F3 are negative under both leave-one tests. F3 never invokes fallback because coverage is sufficient on all selected sectors, so F2 and F3 are identical by construction on this dataset.

## Reporting-only windows

F1 is approximately tied with F0 in 2026H1 (+20.46% versus +20.03% relative excess), but reverses sharply in 2026H2_PARTIAL (-15.63% versus F0 +0.80%). F2/F3 are negative in both reporting windows.

These windows do not change the formal decision, but reinforce that the current fundamental composite is not stable enough to replace the technical tail selector.

## Final decision

`pit_fundamental_model_not_supported`

- Stage 0 data coverage is supported.
- Fundamental-only industry Top1 is not supported.
- A global 50/50 rank blend is decisively rejected.
- No candidate is created or promoted as CN x1.1.

## Research interpretation

The experiment rejects the assumption that a broad equal-weight fundamental composite should replace R0 inside every selected sector. It does not reject PIT fundamentals as an information source.

The next bounded hypothesis is narrower:

1. preserve R0 as the primary within-sector ranking signal;
2. use fundamentals as a veto or shortlist reranker rather than a full replacement;
3. select fundamental components only from 2022–2023 calibration evidence;
4. freeze one shortlist/filter architecture before reopening 2024–2025 validation.

Recommended next candidates are therefore not new blend weights. They are:

- R0 Top3 shortlist, fundamental score selects one;
- remove the bottom fundamental tercile, then take the highest remaining R0 name;
- component-qualified R0 Top1, with fallback only when no name passes.

The shortlist size, component inclusion and sign must be selected on 2022–2023 only.

## Integrity and infrastructure notes

- The complete event store, coverage status, score ledgers, holdings and contribution records remain in Actions artifacts.
- The first live model execution exposed an object/nullable boolean-mask bug; a real-data regression test was added before the frozen rerun.
- PIT event population is substantially more expensive than model evaluation. Future work should version the exact-cutoff event store as an immutable provider artifact and reuse it across model experiments.
- The CN130 pool remains static and therefore carries survivorship bias.
