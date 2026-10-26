# PR #1296 : docs(architecture): propose Investment Research Infrastructure direction and staged transition

## Purpose — product-direction discussion, not a new feature release

**Proposal:** Alpha Engine should evolve into a **single-operator, evidence-governed Investment Research Infrastructure**: reusable historical/PIT data products, common experiment prerequisites and durable research evidence for many possible hypotheses. The **existing four-strategy Strategy Console and Direction A v1 remain the current delivery scope**.

This **Draft PR is intentionally documentation-only**. It does **not** authorize new providers, a new research IDE, schemas, pipelines, strategies, model promotions, trade execution, security/RLS modifications or deployment.

### Why now — findings from current main `58a56c14c` (formal US/CN cutoff 2026-10-23)

- **Keep, don't rebuild:** the selected US87/CN130 pools, `fundamental_event_store_v1`, `corporate_action_store_v1`, `model_data_bundle_v1`, Alpha158, frozen research and immutable evidence already provide reusable capabilities.
- Published Model Data Bundle has **5 ready / 3 partial components** and **2 blocked training profiles**. These statuses are *specific to existing profiles*, not blanket historical-information/PIT readiness.
- New investment ideas still require explicit review of historical availability, revisions, information-time joins, source licences, missing event vs zero, and researcher-facing data discovery. RDI's #1272 source family history is **not** PIT-certified.
- **Urgent unchanged obligation:** #1288 and draft #1291 describe current operating fields visible in public Git/Pages. Treat this as **v1 release-blocking P0**, independent of the broader infrastructure ambition.
- v1 is **not certified** by the recent audit: #1284 reports 0 independently qualified sessions, while #1287/#1289/#1290 preserve UAT/replay/release gaps. #1293 and #1295 offer useful isolated repairs, not an integrated release PASS.

### Files to review (3 new docs)

1. [Product thesis / architecture boundaries](https://github.com/liuh886/alpha_engine/blob/docs/investment-research-infrastructure-20261026/docs/product/investment_research_infrastructure_charter_2026-10-26.md): model-independent infrastructure positioning, data/experiment contracts, owner decisions D1–D5.
2. [Evidence-based baseline & current PR audit](https://github.com/liuh886/alpha_engine/blob/docs/investment-research-infrastructure-20261026/docs/architecture/investment_research_infrastructure_baseline_2026-10-26.md): canonical assets, dated 8-component readiness, RDI gaps and exact current blockers.
3. [Dual-track roadmap and scoped Agent work orders](https://github.com/liuh886/alpha_engine/blob/docs/investment-research-infrastructure-20261026/docs/product/investment_research_infrastructure_roadmap_2026-10-26.md): protect current v1 work, then B0 inventory → B1 PIT contract convergence → B2 smallest as-of slice → B3 two heterogeneous research journeys → B4/B5 usability and complexity reduction; RI-01 through RI-05 with positive/negative DoD.

### Compatibility with latest PRs (not competing merge work)

- **#1276 draft** Direction A v1 / A0–A7: **preserved**; this PR proposes a longer-lived product *umbrella* rather than reopening v1 implementation.
- **#1283, #1284, #1287, #1289, #1290**: docs authority, real-session acceptance, four-strategy UAT, local replay, release/rollback remain their own reviewed tasks.
- **#1291 / #1288**: privacy/publication repair remains P0; don't expose current signals in any new research artefact.
- **#1293, #1295**: reuse single authoritative replay and existing retirement tests; avoid duplicate runners.
- **#324, #325, #826, #1074, #1272**: reuse their existing issues and evidence; no duplicate implementation epics at this stage.

### Architectural decision requests

- **D1:** Accept Investment Research Infrastructure as long-term positioning while Direction A v1 remains release scope?
- **D2:** Prioritize local data discovery/PIT access over restoring a browser research IDE?
- **D3:** Audit source coverage, first availability, licence/redistribution and retention *before* adding providers?
- **D4:** Use cross-sectional study and RDI **readiness/blocked** as diverse infrastructure cases, without claiming new predictive alpha?
- **D5:** After owner review, open **RI-01 data lineage inventory** and **RI-02 PIT information-state semantics** as narrow Agent issues first?

### Validation and no-go boundaries

- Verified all three new files are readable from this branch and cross-linked.
- No existing tracked source, CI workflow, current strategy, runtime entitlement, active registry, immutable evidence or public asset is edited by this PR.
- Planning does **not** pass v1 A0–A7. No real multi-session operational acceptance or investment outcome is claimed.
- **Request:** review as Draft; no auto-merge. Ratify, reject or amend D1–D5 and RI-01/02 before delegating code.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track B / 长期平台转型；状态：Draft / 决策待批准。**

**开发主线：** 从“为四个策略搭配管线”改为“可复用的金融数据产品 + 历史信息状态 + 可复现实验 + 不可变研究证据”。当前 Direction A v1 的四策略只读 Console 不退出、不扩为研究 IDE。

**后续工作与预期交付（按依赖顺序）：**
1. **RI-01 / B0：资产与消费者审计（首个可委派任务候选）**：逐类列出 US87/CN130、参考 ETF、行情、基本面、公司行为、Alpha158、RDI 事件的权威路径、实际覆盖/可得时间、数据权利、调用方、缺口和证据链接；提供横截面与 RDI 两条既有研究路径的复用图。结果：可审阅的真实数据目录和阻塞清单，而非新数据库。
2. **RI-02 / B1：历史信息状态契约（第二候选）**：统一解释 event/released/available/retrieved/revised、PIT 股票池、raw/adjusted、缺失与未观测；为跨领域 as-of 查询写契约映射及负面案例。结果：不引入新事实权威的 ADR 草案与测试矩阵。
3. **RI-03 / B2：最小可用 PIT 数据切片**：仅在 RI-01/02 证明确有接口缺口时，利用既有 reader/manifest 实现一种受约束的本地复用方式；后到修订、上市前标的、缺来源、越权数据必须拒绝。结果：冻结输入与可复现的查询/失败 receipt。
4. **RI-04 / B3：两类研究消费者验证**：截面研究与 RDI readiness 共用数据和证据协议，但不混同模型逻辑；RDI 历史事件不可得时如实 BLOCKED。结果：两条独立的研究复用实例及负面证据。
5. **RI-05 / B4–B5：研究工作流与维护成本优化**：测量准备一个新研究问题的人工步骤、重复 ETL、数据副本及复现时间，只有发现真实摩擦才改现有 CLI/测试。结果：有前后对照的减少重复工作证据。

**预期成果（本规划 PR）：** 在 owner 审批 D1–D5 后形成可执行且互不重叠的研究基础设施路线图；第一轮由 RI-01 交付 source/consumer/rights/cutoff 审计矩阵，RI-02 交付跨领域历史信息状态 ADR 与负面测试矩阵。RI-03/04/05 保持候选阶段，仅依据前序实证缺口创建后续 Issue。任何阶段都要能证明自己减少了数据和实验准备的重复工作，而不是增加模型或工作流数量。

**验收/出界：** 先审核 D1–D5，批准后再为 RI-01/02 建立独立 Issue/PR；不在本 PR 修改产品代码、模型、权重、数据契约、CI、RLS 或正式证据；不要把 5 ready / 3 partial / 2 blocked profiles 误写成“全平台就绪”。#324/#325/#826/#1272 已有的数据/训练任务须复用，不能另立平行实现。

**与 Open PR 的执行顺序：** P0 首先处理 #1291 的公开发布边界并延续 #1287 的权限审计；#1286/#1284 负责运行正确性和真实 20-session 证据；#1293/#1289 负责 US/CN 本地复现；#1295 负责旧模型退役测试；#1283 收敛历史文档；#1290 汇总 release NO-GO/GO；#1276 保持 v1 产品交付范围。本 PR 不能替代这些 PR 的原有验收。
