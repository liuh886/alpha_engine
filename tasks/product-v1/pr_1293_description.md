# PR #1293 : fix(research): reuse accepted QQQ replay contract (#1292)

Fixes #1292, advances the accepted US reference work in #1282. Main 58a56c14c's generic replay CLI required professional_source_ready=true even though the active accepted QQQ source contract/lineage explicitly use governed Yahoo research data. The existing authoritative formal verifier already supports that exact hash-bound contract.

Reuse the authoritative verifier and remove duplicated evaluation/validation. Bind its ETF manifest through the verified recipe, reject missing/malformed/hash-drifted source bindings, retain exact accepted model/run/economic identity and all existing failure checks. No new runner/provider fallback, model, data contract, registry, cost, source promotion or workflow. Historical economics are retained exactly; the existing gate recomputes the decision path and verifies appended economics/continuity. It does not claim historical economics were recomputed from restated current prices.

Validation: 34 replay/data-recipe/rules-gate tests PASS (including real committed BYD regression), Ruff/diff PASS. Actual final QQQ CLI replay succeeded and matched two earlier runs: three identical successful receipts with professional_source_ready=false. An additional concurrent-load ArrayMemoryError is explicitly retained, followed by successful isolated execution; no false-green. Evidence receipt included. Code isolated in a separate worktree while baseline full-suite auditing continued.

The previous US-blocked assessment was too broad: the generic CLI failed, while the existing authoritative source path worked. No Tiingo purchase is needed for this declared research contract. A5 owner acceptance, full privacy repair, 20-session operations and overall v1 release remain separate. Rollback this CLI routing change only; canonical sealed evidence unchanged. Owner review before merge; no production dispatch or automatic merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / 接受模型的确定性本地 replay 修复；未来通用研究基础设施的“单一权威验证器”示范。**

**本地 Agent 下一步：**
1. 审查并保持现有最小代码范围：`alpha research replay qqq_v4_3` 应使用 accepted hash-bound Yahoo research recipe 和原 formal verifier；不得因通用 CLI 误加 professional-source 条件；专业数据供应商不是该冻结研究契约的必要前提。
2. 重跑当前分支的成功 replay 和 missing/malformed/manifest/hash-drift/identity-mismatch 负面用例，并核查被同文件影响的 BYD/CN 路径无语义漂移；重新评估并保留已观察到的并发 ArrayMemoryError，不把隔离成功等同于并发压力通过。
3. 在合并后于**集成 SHA**上执行一次锁定 US reference 并向 #1289/#1282 的 A5 证据包提供精确运行命令、输入/输出 hash、相等性/容差、不能声称独立重算的历史经济部分。
4. 从现有实现提炼可以被 #1296 RI-04 使用的参考执行范式：确定性 source-bound data→canonical evaluator→不可变 receipt，**只写建议/文档或独立后续 Issue**，绝不在本缺陷 PR 增加第二个 runner。

**预期成果：** 真实 accepted QQQ 契约下的最小可回滚 CLI 修复、正/反回放证据与跨策略回归，作为可复现研究能力的局部证明。

**验收/边界：** 不增 provider fallback、模型/权重、训练策略、自动推广或新工作流；不得宣称交易就绪或全历史收益独立复算；owner 接受后才可用于 v1 A5 验收。
