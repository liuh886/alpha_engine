# CN130 PIT基本面质量过滤与R0短名单实验结果

Date: 2026-08-05  
Issue: #544  
Draft PR: #545  
Status: calibration completed; frozen validation remained closed  
Boundary: `research_only=true`, `trade_ready=false`

## Research question

上一轮已经证明，完整覆盖的PIT基本面等权综合分不能替代R0，也不能通过50/50全行业排名融合改善R0。本轮将问题进一步收窄：只在2022H2–2023H2校准六个可解释的PIT基本面组件；只有组件稳定通过后，才允许用它们对R0 Top3短名单进行重排或作为质量否决条件。

## Immutable inputs and feasibility amendment

- CN130成员、行业分类、10交易日预测期和价格provider均不变；
- PIT事件SHA256：`9d0babbf78a9a95272c15a94b56306194ff0a320d4fb92de4f7f78951fc7b8c7`；
- 原计划包含2022H1，但该窗口在不可变价格provider中不足250个purged训练交易日；
- 在查看任何组件输出前，校准窗口冻结为2022H2、2023H1和2023H2；
- 组件和候选架构必须在3/3校准半年均为正，其他门槛不变；
- 2024–2025验证数据未被用于组件或架构选择。

## Final decision

`fundamental_component_not_supported`

- Supported components: 0；
- Selected architecture: none；
- Frozen validation opened: no；
- No CN x1.1 candidate is created。

## Component calibration

| Component | Mean Rank IC | Incremental IC | Positive windows | Worst window | Mean spread | Max sector share | Positive fiscal classes | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| inverse leverage | **0.0167** | **0.0223** | 2/3 | -0.0265 | +0.43% | 48.3% | 2/3 | fail |
| asset turnover | +0.0057 | +0.0019 | 1/3 | -0.0201 | -0.14% | 40.4% | 3/3 | fail |
| net margin | -0.0273 | -0.0213 | 0/3 | -0.0438 | -0.48% | 32.7% | 1/3 | fail |
| ROE proxy | -0.0343 | -0.0324 | 0/3 | -0.0462 | -0.89% | 34.4% | 1/3 | fail |
| robust net-income YoY | -0.0503 | -0.0509 | 0/3 | -0.0643 | -0.80% | 38.5% | 0/3 | fail |
| revenue YoY | -0.0712 | -0.0704 | 0/3 | -0.0944 | -1.01% | 28.2% | 0/3 | fail |

### Closest component: inverse leverage

Inverse leverage is the only component that clears the average Rank IC and incremental IC thresholds:

- 2022H2 Rank IC: +0.0591；
- 2023H1: -0.0265；
- 2023H2: +0.0174；
- Mean Rank IC: +0.0167；
- Mean incremental IC: +0.0223。

It still fails three preregistered conditions:

1. only 2/3 calibration windows are positive rather than 3/3；
2. the worst window, -0.0265, is below the -0.025 floor；
3. only two fiscal-period classes have positive average IC rather than three。

The miss is narrow but real. Reopening the threshold to admit it would be result-driven and was not allowed.

### Growth and profitability components

Revenue growth, net-income growth, margin and ROE are negative in every calibration half-year. Their incremental IC after removing contemporaneous R0 rank is also negative. For a 10-session horizon inside R0-selected sectors, stale accounting levels and year-on-year growth do not act as a stable positive quality signal.

This result should not be inverted mechanically. A negative calibration sign may reflect expectation pricing, reporting lag, cyclicality or short-horizon mean reversion; treating “worse fundamentals” as a tradable positive factor would require a separate economic hypothesis and preregistration.

## Why validation remained closed

The experiment was explicitly staged:

1. component calibration；
2. architecture calibration；
3. one-shot frozen validation。

Because no component passed Stage A, S1/S2/S3 were not evaluated for selection and the 2024–2025 validation gate was never opened. Empty architecture and validation tables are therefore a governed stop result, not missing evidence.

## Research interpretation

The current evidence rejects three increasingly narrow uses of static accounting fundamentals:

- replacing R0 within selected sectors；
- globally blending R0 and fundamentals；
- using a positive-direction accounting quality composite as a shortlist reranker or veto。

The failure is now sufficiently consistent that continuing to rearrange the same six statement fields is unlikely to produce a robust CN x1.1.

The next new-model search should change the information type rather than the weight or architecture. The highest-priority candidates are:

1. **fundamental surprise at disclosure** — quarter-on-quarter or year-on-year change relative to the company’s own prior trajectory, measured only when the report becomes available；
2. **event-time post-disclosure behavior** — gap, abnormal volume and 1–5 day residual reaction after earnings or performance-forecast announcements；
3. **corporate-action and forecast events** — dividends, buybacks, placements, unlocks, performance forecasts and earnings revisions；
4. **PIT size and risk controls** — shares outstanding and market capitalization, enabling real size-neutral and residual targets。

The most defensible next model is therefore an event-conditioned R0 tail model, not another static fundamental ranker.

## Integrity and evidence

Independent workflow run `30999539903` passed:

- locked environment installation；
- Ruff and focused tests；
- immutable price and PIT event artifact verification；
- three feasible calibration R0 ledger rebuilds；
- two complete staged experiment runs；
- byte-for-byte deterministic comparison；
- complete evidence packaging。

Artifact: `cn130-pit-fundamental-veto-30999539903`

- id: `8927662386`；
- digest: `sha256:92b4948a4bf291741a19a95a112fdb6e7fc6ee0c9c1966bae69ce63d17213348`；
- size: 8,972,269 bytes。

The full fiscal-period diagnostics and calibration score ledgers remain in the artifact. The repository commits the decision, execution identity, component summary, half-year summary and this report.
