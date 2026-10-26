# PR #1289 : docs(evidence): pin bounded CN and QQQ replay acceptance (#1282)

W3 / #1282: bounded accepted CN and QQQ local replay evidence; A5 awaits owner acceptance. Baseline main 58a56c14c, accepted cutoff 2026-10-23.

CN frozen history through 2026-09-04 repeats twice at the predeclared 1e-6 tolerance; missing-source copy fails closed. Original 25 replay/data-recipe/rules-gate tests pass.

The original generic QQQ CLI data_blocked receipt is preserved. Follow-up #1293 removes its duplicate professional-only gate by reusing the existing authoritative verifier, which already accepts the frozen Yahoo research contract: three identical successful CLI receipts, 34 affected tests. No Tiingo purchase or provider substitution is required for that contract. Frozen economic-prefix integrity is separate from the recomputed decision path, appended economics and continuity; full historical economics are not independently recalculated from current prices. Implementation awaits review/merge.

No source/model/pool/cost changes, new runner/workflow or sealed evidence rewrites. Failed research stays failed; owner A5 scope acceptance remains pending. No release or automatic merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / v1 A5 可复现研究验收；也是 #1296 可复用研究证据层的参考案例。**

**本地 Agent 下一步：**
1. 冻结与核实 CN_27 及 QQQ accepted reference 的 **确切 source/model/evaluator/benchmark/calendar/cost/adjustment/decision cutoff 身份**，区分证明决策路径可重放、历史 economics 前缀 hash 检查、真正重新计算历史经济结果三种不同声明。
2. 对 CN 已通过的两次复现保留独立 receipt、声明容差 1e-6 与缺源负面用例；未覆盖到 2026-10-23 的全部最新运行，不要扩写成“所有历史/未来研究可重现”。
3. #1293 的 QQQ CLI 三次成功仍属**未合并分支的证据**：待该代码审查并整合后，再在锁定的实际集成 commit 上重复 US 参考实验，验证 missing/malformed/hash drift 后明确阻塞；不得要求购买 Tiingo 或放松原 accepted Yahoo research contract。
4. 以这两个例子整理最小通用 **experiment receipt 对照表**（冻结输入、研究参数、测试窗口、成本、运行器、结果/失败），供 #1296 RI-02/RI-04 复用；不要在该 PR 新建研究引擎。

**预期成果：** 可由本地研究者依既定入口重复的一个 US 与一个 CN 基准实验，及明确不可验证部分/数据缺口的证据包。

**验收/边界：** A5 只在 owner 对证明范围、集成 SHA、失败情况独立验收后更改状态；不重算或改写 frozen sealed historical economics，不替换退休模型，不生成新正式策略/信号。
