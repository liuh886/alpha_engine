# PR #1295 : test: enforce CN x1.2 retirement in complete-suite acceptance (#1294)

Fixes #1294, with evidence for existing health tracker #1227 and release work #1281. The full 500-file backend audit found only two logical failures, both old expectations that retired CN x1.2 must still be actively published. Keep exact historical package/promotion/source hashes, full row evidence and its failed gate; replace active-publication assertions with both update_catalogs modes rejecting retirement and no canonical/active-publication mutations. Active catalogs must match the existing four-strategy registry. No runtime, model, registry, source/evidence changes or new skips.

PASS: 5 targeted tests; the full affected frozen CI-style shard rerun gives 931 passed / 6 existing approved skips; Ruff/diff. Together with unchanged original shards 0-2, all 500 test files are covered once: 3938 passed / 8 policy-approved skips / 0 failures. Exact report/partition/log/XML hashes and skip accounting retained. No failing test skipped or historical research erased.

The original monolithic quality command failed collection MemoryError; its FAIL is preserved. Its other 12 commands passed. This composed backend verification is not a new monolithic quality PASS, a pinned release-candidate certificate, or a test of separate QQQ CLI PR #1293. Privacy #1288, real 20-session proof and owner signoff remain open. Revert this test-only correction to roll back; no production action or automatic merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / 退役模型边界与完整测试可信性；为长期研究平台保留负面研究记忆的基础纪律。**

**本地 Agent 后续任务：**
1. 核查原来的两条旧断言在**retired CN x1.2** 的正式边界已不再成立；维持原模型历史 run、失败研究及 hashes 的可访问性，但更新活跃 catalog 的正/负断言，使其只能与现有四策略 registry 一致。
2. 复跑受影响 shard 的真实测试，保留完整 500 test files 的分片映射、跳过白名单、日志 SHA 与相关已验证输出；如果 CI/依赖锁改变，必须重新生成新候选证据，不得套用旧测试结果。
3. 明确区分“合成四个 shard 3,938 PASS / 8 skips”和“monolithic full-quality command 曾因 MemoryError 失败”；在 #1290/A6 汇总时保留前者的适用范围及后者未完成的集成证明。
4. 将模型生命周期治理作为 #1296 的原则：退役实现可从 active runtime 移除，但 verified historical evidence、失败原因和来源链必须长期可追溯。任何清理工作另建 scoped Issue，不能在本测试 PR 扩大范围。

**预期成果：** 与四策略正式身份一致的测试保障、真实组合质量收据，以及不误激活过期模型的负面覆盖。

**验收/边界：** 不删除历史 evidence、不得新增跳过、不得修改任何运行模型/训练样本/正式签发内容，不把局部测试成功描述成完整 v1 GO；完整 main 候选必须独立复验。
