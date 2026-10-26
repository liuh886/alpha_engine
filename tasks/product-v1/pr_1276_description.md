# PR #1276 : docs(product): Direction A v1 personal quant workstation, A0–A7 release gates and local Agent roadmap

## Owner decision: **Direction A ratified** on 2026-10-25

**Alpha Engine v1.0 = personal, single-operator professional quantitative research workstation.** Two supported modes:
1. Existing **local CLI research** using pinned governed data, validation and immutable evidence.
2. Existing **read-only four-strategy Strategy Console**, including current observations, governed historical performance, linked instrument explanations and Operating Status.

This is aligned with accepted [ADR-0003](docs/adr/0003-single-user-local-quant-research-platform.md). Existing public historical artifacts vs protected current Strategy Operations / Supabase RLS stay intact. **Out of v1:** paid subscription expansion, multi-tenant SaaS, external onboarding, autonomous orders, extra main-nav research IDE, new scheduler/state backend. RDI remains separate **unvalidated** research (#1272).

### What changed in this design PR
- `docs/product/product_completion_charter_2026-10-25.md`: owner-ratified scope, excluded expansion and current authority.
- `docs/product/product_completion_scorecard_2026-10-25.md`: original subjective 70/100 baseline kept; **A0–A7 hard v1 release gates** introduced with PASS/FAIL/BLOCKED/NOT_TESTED, evidence cutoffs and owner signoff (no score inflation).
- `docs/product/local_agent_delivery_contract_2026-10-25.md`: local Agent handoff discipline, scope and negative-path evidence.
- `docs/product/v1_direction_a_agent_roadmap_2026-10-25.md`: concrete W0–W4 scoped work orders and sequencing.

### GitHub Agent-ready issues
- W0 / P0 **#1278** — authoritative product docs and retired contract reconciliation (first task).
- W1 / P0 **#1277** — actual **20 eligible completed exchange sessions per CN/US market**, 4 strategies with correct declared decision cadences; honest blocked/no-change, real vs synthetic proof separate.
- W1b + W2 / P0-P1 **#1279** — four-strategy browser/operator task UAT and existing privacy/RLS negative tests.
- W3 / P1 **#1282** — one accepted US and one accepted CN reproducible local research reference; reuse existing #324/#325/#826 only for required upstream source/training issues.
- W4 / P1 **#1281** — owner-local runbook, actual release/rollback receipts and A0–A7 gate packet.

### v1 release decision
v1 signoff requires **all A0–A6 evidence gates PASS** and explicit owner **A7 GO**; green unit tests or historic strategy alpha do not substitute for reliable operations, PIT truth, accurate UX, local research reproducibility or privacy. 20-session evidence is a **real market observation gate**; CN_27's 30-session due cycle may require separate actual due evidence.

### Limits of this PR
**Documentation/architecture only.** No source code, accepted model identities/parameters, schema, Supabase policy, workflows, routes, trading code, formal evidence or prod release are changed. Proposed development and acceptance details remain reviewable. Keep PR **Draft** until owner accepts architecture and test criteria.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / 当前 v1 产品范围与发布门禁；与 #1296 的关系：短期交付范围 vs 长期基础设施愿景。** 本 PR 仍为 Draft，不因新定位自动批准合并或改变 A0–A7。

**本地 Agent 后续任务：**
1. 对照 #1296 中的长期定位补一份**范围分层说明**：v1 保持 single-operator、本地受治理 CLI 研究与只读四策略 Console；未来研究基础设施以可复用数据产品和实验能力为中心。不要删除已通过审查的 v1 验收规则。
2. 用 #1283/1284/1287/1289/1290/1291/1293/1295 的最新结果逐个更新 A0–A7 的 **PASS/FAIL/BLOCKED/NOT_TESTED 与证据来源**；不得把其他 PR 上的通过结果冒充 main 已集成发布。
3. 明确以后新增研究数据能力属于 #1296 后续单独 Issue，不得恢复已退休的浏览器 Research Studio、Decision Desk、CN x1.2 或增加工作流。
4. 保留 v1 决策真相：A4 公开发布安全缺陷仍是 release-blocking，真实 20-session、权限 UAT、可复现研究、回滚与 owner A7 仍需验证。

**预期成果：** 一份没有双重权威的 v1 completion charter + release gates + local Agent roadmap，并链接 #1296 长期定位而不重写现有权威文档。

**验收/边界：** 四策略 registry 与既有 Strategy Console/API 保持不变；每一 gate 的证据 SHA、日期和阻塞来源可核；仅文档范围的必要修正；实施与发布必须走原 Issue/PR，owner 审查后才可合并。
