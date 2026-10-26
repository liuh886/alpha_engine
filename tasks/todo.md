# Alpha Engine 开放 PR 推进与基础设施演进实施计划 (Task Master Plan)

> **基准主线**：`main` @ `58a56c14c` (数据截止 2026-10-23)
> **双轨战略 (Dual-Track)**：
> - **Track A (当前冲刺交付)**: Direction A v1 个人量化工作站收口、四策略控制台、核心缺陷修复与 A0–A7 门禁硬核闭环。
> - **Track B (下一阶段演进)**: PR #1296 驱动的单一操作员“可复用金融数据产品 + 证据治理投研基础设施”研讨与分阶段演进 (RI-01 ~ RI-05)。
> **核心铁律**：`research_only=true` / `trade_ready=false`，不可变数据与证据，Fail-closed，保留失败记录，绝不伪造通过。

---

## 阶段规划概览

| 阶段 | 核心任务与对应 PR | 关键成果标准 (DoD) | 状态 |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **规范与核心缺陷修复**<br>(PR #1283, #1286, #1293, #1295) | 确立文档唯一权威；修复 no-change 发布；修复 QQQ 本地回放；纠正退市策略断言；单体分片测试 3,938 项全绿。 | **已完成** (4个PR已合入 main，测试全绿) |
| **Phase 2** | **阶段性审计与事实证据归档**<br>(PR #1284, #1287, #1289, #1290) | 真实记录 20-session 缺口 (A1 BLOCKED)；走查四策略旅程；归档本地回放证据；交付单操作员运维手册与 A0–A7 NO-GO 判定书。 | **已完成** (4个证据/手册PR已合入 main) |
| **Phase 3** | **P0 隐私安全缺陷技术攻坚**<br>(PR #1291 方案转化与 #1288 修复代码) | 实现 `sync-formal-model-runs.mjs` 公开脱敏投影与私有归档隔离；通过直接匿名 HTTP 负面拦截测试；将门禁 A4 由 FAIL 变更为 PASS。 | **待攻坚** (核心焦点：修复 A4 FAIL) |
| **Phase 4** | **集成 SHA 全量回归与 v1 Release Candidate**<br>(PR #1276 章程转正与冻结集成) | 固定单一集成 Commit；复跑完整门禁；验证隐私合规的回滚目标；形成 Owner 最终 A7 决策包。 | **待执行** |
| **Phase 5** | **Track B: 通用投研基础设施启动研讨**<br>(PR #1296 启动、D1–D5 裁定与 RI-01/02 拆票) | 完成 D1–D5 架构裁定；拆解 RI-01 (数据资产与消费者审计) 与 RI-02 (PIT 历史信息状态) 独立工单；启动下一阶段演进。 | **待研讨** |

---

## 详细可核查步骤 (Checkable Steps)

### Phase 1: 规范确立与核心缺陷修复 (Track A)
- [x] **1.0 隔离测试分支端到端验证**：模拟 PR #1283, #1286, #1293, #1295, #1284, #1287, #1289, #1290 连续合并，无任何文件冲突，43 项直接相关测试全绿通过。
- [x] **1.1 PR #1283 (W0 文档权威对齐 - #1278)**：
  - [x] 核查 README, AGENTS, ADR-0003, `strategy_console.md`, legacy Vision/Capability Matrix 权威层级。
  - [x] 确保提供清晰的 Agent "start here" 路径（4策略 CLI/Console -> 冻结研究契约 -> 长期 #1296）。
  - [x] 确保 `TASKS.md` 与旧矩阵彻底屏蔽 ZIP 导入、独立 IDE、旧五策略等退役路径。
  - [x] 合并 PR #1283 (merge commit: `bfcb811e358014343b4c4410232a0ab8c992bac3`)。
- [x] **1.2 PR #1286 (缺陷修复：无决策变更发布中断 - #1285)**：
  - [x] 审查 `formal-backtest-refresh.yml` 中的 `jq -e` 布尔转换逻辑，保证合法 `publication_required=false` 顺利放行，非法输入严密 fail-closed。
  - [x] 复跑 71 项发布增量与工作流治理测试，确保 39 workflows 零违规。
  - [x] 合并 PR #1286 (merge commit: `e74e1affe680f1caa3507558ea574c95bf665cab`)。
- [x] **1.3 PR #1293 (核心修复：QQQ 本地回放解封 - #1292)**：
  - [x] 审查 `formal_model_replay.py` 最小改动范围，复用现有权威验证器与 Yahoo 研究契约，移除不必要的商业数据源阻断。
  - [x] 运行 34 项 replay/rules-gate 测试，验证 BYD 回归用例与缺源负面测试全绿。
  - [x] 合并 PR #1293 (merge commit: `874492a748e5bdd1614d8470107b08c0c1c5f916`)。
- [x] **1.4 PR #1295 (测试纠偏：CN x1.2 退市断言修正 - #1294)**：
  - [x] 审查 `test_materialize_cn_x1_2_evidence_bundle.py`，确保活跃 catalog 仅与四策略一致，历史哈希完整可溯。
  - [x] 验证后端测试分片覆盖（3,938 passed, 8 approved skips, 0 failures），确认消除了过时断言导致的报错。
  - [x] 合并 PR #1295 (merge commit: `f51e352afc4cea85a36a2aa89796ab33005b93f6`)。

### Phase 2: 事实证据归档与运维手册收口 (Track A)
- [x] **2.1 PR #1284 (W1 审计：20 交易日运行证据 - #1277)**：
  - [x] 核对 20 交易日枚举缺口（7 个已观察，0 个独立合规），保持门禁 A1 为 BLOCKED，不粉饰事实。
  - [x] 合并 PR #1284 (merge commit: `96271f2f923d72e7cdb13f85e6ab44d0d87d54ad`)。
- [x] **2.2 PR #1287 (W2 审计：四策略交互走查与泄露实证 - #1279)**：
  - [x] 核实桌面/移动端四策略 8 条交互链路走查截图与日志，保留对 #1288 泄露缺陷的客观指纹记录。
  - [x] 合并 PR #1287 (merge commit: `1e1584050f4373ef120ae5ef8948719a0d10ff54`)。
- [x] **2.3 PR #1289 (W3 审计：本地回放证据封存 - #1282)**：
  - [x] 核查 CN_27 与 QQQ accepted reference 的本地复现证据（容差 1e-6），保持 A5 待 Owner 独立验收。
  - [x] 合并 PR #1289 (merge commit: `eea14be380cf8d91cdbc75c7749dc6ec400efcca`)。
- [x] **2.4 PR #1290 (W4 交付：单操作员运行手册与 NO-GO 判定包 - #1281)**：
  - [x] 审查 `owner_local_workstation_runbook.md` 操作手册的真实可操作性（从环境安装、只读诊断到异常恢复）。
  - [x] 确认 A0–A7 客观判定为 NO-GO（A1/A2/A3/A5/A6 BLOCKED, A4 FAIL, A7 NOT_TESTED）。
  - [x] 合并 PR #1290 (merge commit: `6ec70004eeb2973223688db49feb90e81089c630`)。

### Phase 3: P0 隐私泄露攻坚与门禁 A4 闭环 (Track A 核心阻碍)
- [ ] **3.1 审查 PR #1291 架构方案**：
  - [ ] 明确公开历史投影（Public Historical Projection）与私有状态归档（Private Canonical Store）的隔离边界。
  - [ ] 确保公开 projection 拥有独立哈希与清单，不伪造原 canonical bundle 哈希。
- [ ] **3.2 实施脱敏投影代码切片**：
  - [ ] 改造 `sync-formal-model-runs.mjs`，在构建公开静态资源时剔除 `operating_state`、最新目标仓位与敏感执行信息。
  - [ ] 保持私有归档/Supabase RLS 中当前运行状态的授权读取能力。
- [ ] **3.3 编写匿名穿透负面测试与验证**：
  - [ ] 编写测试针对 Git 树、Pages 输出文件、网络请求进行直接匿名扫描，断言 100% 不含敏感仓位字段。
  - [ ] 重新评估门禁 A4，完成由 FAIL 到 PASS 的实证闭环。

### Phase 4: 集成 SHA 质量门禁与 v1 Release Candidate
- [ ] **4.1 冻结集成 SHA**：在所有修复与脱敏代码合入后，打出稳定 Release Candidate。
- [ ] **4.2 运行完整质量门禁**：后端分片测试、前端 Vitest、Playwright 浏览器测试、Lint、构建打包全绿验证。
- [ ] **4.3 更新 PR #1276**：更新章程中的 A0–A7 状态矩阵（A4 PASS, A5 PASS, A6 PASS 等），提交 Owner 签署 A7 决策。

### Phase 5: Track B — 通用投研基础设施启动研讨 (PR #1296)
- [ ] **5.1 组织 D1–D5 核心架构决策研讨**：
  - [ ] D1: 明确“投研基础设施”为长期定位，Direction A v1 保持为当前交付边界。
  - [ ] D2: 优先本地数据发现与 PIT 时点访问，暂不恢复浏览器端研究 IDE。
  - [ ] D3: 严守数据权限与可得性前置审计，不盲目引入未授权外部源。
  - [ ] D4: 以多空截面与 RDI 阻塞案例作为典型基础设施消费者。
  - [ ] D5: 拆解首批委派任务 RI-01 与 RI-02。
- [ ] **5.2 拆解与开启 RI-01 与 RI-02 独立工作单**：
  - [ ] RI-01: 数据资产与消费者全量血缘审计矩阵。
  - [ ] RI-02: 跨领域 PIT 历史信息状态语义 ADR 与负面测试集。

---

## 阶段验收与复盘 (Review Section)
- [x] **Phase 1 验收通过 (2026-10-26)**:
  - **PR #1283** (W0 / #1278) 合并入 `main` (`bfcb811e3`)：完成 README、AGENTS、ADR-0003 与战略控制台契约对齐，锁定 4 策略权威，建立 Agent start-here 导航。
  - **PR #1286** (Fix / #1285) 合并入 `main` (`e74e1affe`)：解决合法 `publication_required=false` 下 `jq -e` 中断问题，71 项发布与工作流治理测试全绿，工作流预算 39/45 零违规。
  - **PR #1293** (Fix / #1292) 合并入 `main` (`874492a74`)：解封 QQQ 本地研究回放，复用 Yahoo 研究契约与权威验证器，34 项回放与规则门禁测试全绿。
  - **PR #1295** (Test / #1294) 合并入 `main` (`f51e352af`)：修正 CN x1.2 退市断言，消除全量后端 500 个测试文件在活跃发布检查上的报错，保留历史研究数据。
  - **回归验证**：更新后 `main` 分支执行受影响的 43 项核心测试 100% 通过 (9.83s)，`test_check_ci_governance.py` 15 项治理测试全绿 (4.71s)，`git diff --check` 零告警。
- [x] **Phase 2 验收通过 (2026-10-26)**:
  - **PR #1284** (W1 / #1277) 合并入 `main` (`96271f2f9`)：如实记录 20 交易日运行审计缺口（7 个已观察，0 个独立合规），保持门禁 A1 为 BLOCKED，不伪造数据。
  - **PR #1287** (W2 / #1279) 合并入 `main` (`1e1584050`)：完成四策略 8 条全端链路走查并封存真实截图，记录公开 Git/Pages 对当前运营状态的泄露指纹，保持门禁 A4 为 FAIL。
  - **PR #1289** (W3 / #1282) 合并入 `main` (`eea14be38`)：封存 CN_27 与 QQQ 本地回放可复现证据，保持 A5 待 Owner 独立验收。
  - **PR #1290** (W4 / #1281) 合并入 `main` (`6ec70004e`)：交付个人工作站单操作员运行手册 `docs/operations/owner_local_workstation_runbook.md`，汇总 A0–A7 阶段性判定书（当前裁决为 NO-GO）。

