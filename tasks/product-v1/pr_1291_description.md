# PR #1291 : docs(security): review complete current-operation publication boundary (#1288)

Draft design for #1288, discovered under #1279. This is a concrete owner review packet, not an implementation or deployment authorization.

Anonymous source audit confirms a second bypass: the public repository exposes all four current latest decision ledgers plus CN_27 operating lineage (5/5 HTTP 200). Value-free receipt retains paths, field counts and response hashes only. Pages-only redaction or RLS changes cannot close that bypass. Rewriting copied lineage while retaining sealed hashes would also violate integrity.

Proposed direction: reuse existing private archive/append-only ledger/runtime; replace whole-tree public copy with an explicitly source-bound historical projection whose changed bytes have distinct projection hashes/identity. Preserve canonical model/run/bundle source identities and authorized replay. No new service, scheduler, registry, state DB, strategy or policy mutation. Historical public Git disclosures cannot be undone; do not rewrite sealed history.

Proposal specifies migration slices, affected existing consumers, cross-channel negative checks and privacy-qualified rollback. Owner must approve the publication contract direction and intended live tiers before implementation, as required by #1279. A4 remains FAIL and v1 NO-GO. Existing full quality-only run is also collecting evidence; its failures will remain separate from privacy acceptance.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / P0 安全与数据发布边界；长期研究基础设施的前置安全约束。状态：Draft 设计，尚无实施批准。**

**已发现问题不能被新定位掩盖：** 当前公开 Git/Pages 路径可能携带 current operating weights/targets/ledger 信息；仅修复 Pages 展示或仅修改 Supabase RLS 无法覆盖 Git 历史/当前公开文件。只保留无敏感数值的审计指纹。

**后续工作顺序（设计 PR 中先决策，具体修复另开 Issue/PR）：**
1. 让 owner 明确区分可公开的历史正式研究证据、必须保护的当前策略决策/持仓/因子来源，以及现有真实成员权限。公开/私有层级未经批准不得推断。
2. 审查唯一发布路径，列出每类源、复制范围、静态投影、manifest/hash、模型 replay 与前端消费者，给出**不重写 sealed source**的最小替代：公开历史 projection 拥有独立版本与摘要，私有当期状态沿用已有受保护读取路径。
3. 形成迁移与修复执行拆分：发布前扫描 Git tree/Pages/CI artifacts；匿名 HTTP、实际 entitled、过期、权限撤销、失败回滚的正反测试；不破坏历史 Bundle 身份、hash 验证和 replay。
4. 记录既往公开数据无法通过新发布自动撤回的残余风险，明确停止未来增量暴露及隐私合格的回滚目标。

**预期成果：** 经 owner 审批的 publication/privacy ADR + 文件/消费者迁移矩阵 + 分阶段独立修复任务与负面验收，而不是在设计 PR 里直接改权限或发布。

**验收/Agent 禁令：** #1288 与 A4 保持 FAIL 直至真实跨 Git、Pages、运行权限验证；不复制受限仓位到 #1296 的数据目录；不修改 sealed 内容维持虚假原 hash；不增加第二个后端、scheduler、registry、storage plane。
