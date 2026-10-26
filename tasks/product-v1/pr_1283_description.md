# PR #1283 : docs(product): reconcile Direction A authority and legacy handoff (#1278)

## User outcome / exact Issue
Implements #1278 (W0). Local agents can follow one current authority path without restoring retired Research Studio pages. README and AGENTS point to the existing Console contract; three legacy documents retain history with explicit supersession notices.

## Baseline and scope
Main 58a56c14c, formal evidence cutoff 2026-10-23. Checked exact current routes, registry (QQQ v4.3 / US x1.3 / CN_27 v1.3 / BYD v1.3), ADR-0003 and recovery/access contracts. Draft architecture #1276 remains reviewable, not a v1 release declaration. No runtime, permissions, strategies, workflow or sealed evidence changes.

## Validation and negative path
PASS: all 25 added local links resolve; four routes and registry parity; each legacy document carries a historical notice; existing legacy-web boundary check; git diff --check. The old matrix's rejection of /system and retired ZIP/offline/connected promises are explicitly non-authoritative. No historical tasks deleted.

## Remaining blockers
#828 retains superseded roadmap statements; #1113 records a specific failed publication; #1227 records weekly full-suite failures. None is closed based on a newer green scoped CI. W1–W4 and A0–A7 evidence remain separate. No live UAT or 20-session qualification claimed.

## Rollback / review
Revert this docs-only commit; sealed evidence is unaffected. No new permanent runtime complexity. Owner/architecture review required before merge; no deployment requested.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / 产品文档权威与 Agent 启动入口；该 PR 仍是历史文档协调任务。**

**接下来由本地 Agent 完成：**
1. 在原有文档范围内核查 README、AGENTS、ADR-0003、`docs/product/strategy_console.md`、legacy Vision/Capability Matrix 的**权威顺序**。Direction A v1（#1276）仍主导当前已支持功能；#1296 仅是长期研究基础设施方向的 Draft，不得在未经 owner 批准前改称已实施。
2. 给本地 Agent 提供清晰的“先读什么”路径：现行四策略 CLI/Console→数据权威/冻结研究契约→长期 #1296 规划；保留历史 PR/模型的研究事实，但标为 retired/superseded。
3. 核对 #1296 与本 PR 的链接、命名及含义不互相矛盾；如果需扩展 10 个既有文件之外的实际文档，请先列出范围并请求独立审查，不借 #1278 大面积重写产品愿景。
4. 确保历史 `TASKS.md` 与旧矩阵不能使 Agent 恢复 ZIP 导入、独立 Research IDE、过期五策略页面等退役执行路径。

**预期成果：** 一个可验证的 canonical start-here 阅读导航；每份旧文档有明确当前权威指针；新基础设施规划可被发现、但不抢占 v1 权威。

**验收与边界：** 链接可达，四个真实 route/registry 一致，所有 retirement notice 正确，原 25 links/相关测试仍通过；文档改动不修改策略、数据或权限。新 RI-01/02 的实施需要 #1296 架构批准后另起 Issue。
