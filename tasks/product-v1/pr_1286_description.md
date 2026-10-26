# PR #1286 : fix(ops): allow verified latest-main semantic no-change (#1285)

Fixes #1285, observed during #1277 at actual run 40169478271:1 on main 58a56c14c. When another reviewed release reaches main while a candidate runs, latest-main comparison can legitimately return publication_required=false. jq -e previously exited 1 before reaching the existing semantic-no-change success branch. Convert only a validated boolean to a string so both true and false survive -e; null/strings/numbers remain errors.

PASS: 71 publication delta, formal refresh and trigger tests; regression invokes the actual YAML jq expression for true/false/invalid inputs; Ruff; existing governance inventory (39 workflows / 0 violations); diff check. Original failed operating evidence remains immutable. Actual post-merge recovery NOT_TESTED and 20-session A1 remains BLOCKED.

One existing workflow line and one workflow-bound test group; no scheduler/strategy/schema/policy/data changes. Rollback: revert this narrow commit; no sealed evidence changes. Owner review required, no production dispatch or automatic merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / P0 最小运行故障修复；也符合 #1296“复用现有 pipeline、不叠加基础设施”的原则。**

**本地 Agent 后续动作：**
1. 在当前 PR 的既定改动范围内核查实际 workflow YAML：合法布尔 `publication_required=true/false` 均能通过 `jq -e` 解析，`null`/字符串/数字/缺字段继续 fail closed。
2. 保证 no-change 只在 **verified latest-main semantic equality** 成立时跳过重复发布；真正需要发布、来源异常或身份不符时不能被成功分支吞掉。
3. 复跑原来的 71 项相关测试、CI 治理/工作流数量与适用的 PR gates，保留旧失败 run 及负面测试，不为了“运行成功”改策略、正式数据或证据。
4. **合并后另行记录**一次真实 formal-refresh/latest-main no-change 的 production receipt 与日期，交由 #1284/#1277 的 20-session 统计使用；若未观察到，只能标 NOT_TESTED。

**预期成果：** 一个局部可回滚的 YAML/测试修复，消除合法 no-change 引起的非业务失败，并向日常可靠性审计提供真实可观测证据。

**验收/出界：** 不添 scheduler/workflow、不修改发布准入、不同步旧研究源，也不把本次 71 项 PASS 当作 A1 或正式 release PASS。新数据目录/API 不属于此 PR。
