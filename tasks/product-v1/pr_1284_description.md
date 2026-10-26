# PR #1284 : docs(evidence): account for 20-session operating gaps (#1277)

Implements the evidence audit for #1277; keeps the issue and A1 BLOCKED. Baseline main 58a56c14c; through 2026-10-23. The 20-session US/CN ledger records missing sessions and exact archive/observation hashes, latest capture per formal attempt, and the current strategy cadences. 211 captures / 27 formal attempts provide only 7 observed sessions per market and 0 independently qualified. Manual intervention counts remain unknown. Old five-strategy packets are retained without retroactive promotion.

PASS: all selected Git blobs, archive/member hashes and sizes; existing authoritative acceptance report; 16 negative/cadence/holiday/duplicate tests. Latest attempt 40169478271 failed publication after semantic-no-change; no old green fallback or synthetic session credit. Actual due/recovery, independent review and 20 real qualified sessions remain BLOCKED/NOT_TESTED.

Public audit excludes protected allocations/targets. No runtime, strategy, workflow, data or sealed evidence mutation. Rollback: revert audit projection only. Separate observed jq false exit defect will be handled in its own issue/PR. Owner review required; no release or automatic merge.

---

<!-- infrastructure-alignment-2026-10-26 -->
## 2026-10-26 战略对齐｜本地 Agent 执行指引

**归属：Track A / P0 运行事实可靠性；新研究基础设施未来可以复用运行审计方法，但本 PR 不扩展成通用数据管道。**

**本地 Agent 下一步：**
1. 以 #1277 为权威，在现有 receipt/archive 中逐时段枚举 US/CN **20 个合格交易时段**：provider/formal/factor/decision/delivery 截止、应运行/无需运行、unchanged/delayed/blocked、人工干预和证据哈希。不得以抓取次数或旧五策略包代替真实时段。
2. 继续清点缺口；基于当前审计只证明 7 个观察时段/市场、0 个独立合格，其他时段保持 MISSING/NOT_TESTED。收集后必须有独立复核，不能由本 PR 的测试通过冒充证明。
3. 对 CN_27 的 30 个交易时段决策节奏单独证明一次实际 due-cycle 或明确的隔离确定性用例；不可要求每个交易日换仓，也不可把合成测试计入实盘观察时段。
4. 跟踪 #1286 对 semantic-no-change 的修复，合并后用真实流水验证恢复；历史运行 #40169478271 的失败不能被覆盖。
5. 形成未来可复用的**运行证据字段定义**（仅引用现有 ledger/receipt），作为 #1296 RI-01 研究数据新鲜度审计的可借鉴输入，不创建第二日志源。

**预期成果：** 可逐日检查并独立审核的合格/缺失/阻塞运行矩阵，严格区别数据新鲜度、模型应评估和发布成功，并能定位修复入口。

**验收/边界：** A1 在真实 20-session 与独立审阅完成前保持 BLOCKED；保留 source SHA 和负面 run，不改变冻结模型、节奏、因子、权重、已发布证据或增加 workflow。当前 PR 是历史审计文件，不应在此偷偷加入运行代码。
