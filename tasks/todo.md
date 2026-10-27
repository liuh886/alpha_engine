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
| **Phase 3** | **P0 隐私安全缺陷技术攻坚**<br>(PR #1291 方案转化与 #1288 修复代码) | 实现 `sync-formal-model-runs.mjs` 公开脱敏投影；但公共仓库中仍然存在原始决策账本与未脱敏 lineage Blob，完整安全边界未闭环。 | **公开投影修复已合并、完整隔离待验证** (A4 维持 FAIL) |
| **Phase 4** | **集成 SHA 全量回归与 v1 Release Candidate**<br>(PR #1276 章程转正与冻结集成) | 产品章程与 Scorecard 合并完成；但缺少统一集成 SHA 下的真实发布验证、生产韧性闭环与隐私合规恢复验证，RC 尚未验收。 | **章程已合并、RC 待执行** (A7 维持 NOT_TESTED / NO-GO) |
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

### Phase 3: P0 隐私泄露攻坚与门禁 A4 闭环 (重新打开 #1288 安全验收)
- [x] **3.1 审查并合入 PR #1291 架构方案**：
  - [x] 明确公开历史投影（Public Historical Projection）与私有状态归档（Private Canonical Store）的隔离边界。
  - [x] 确保公开 projection 拥有独立哈希与清单，不伪造原 canonical bundle 哈希。
  - [x] PR #1291 已合并入 `main` (`2940d4104`)。
- [x] **3.2 实施脱敏投影代码切片**：
  - [x] 改造 `sync-formal-model-runs.mjs`，在构建公开静态资源时剔除 `operating_state`、最新目标仓位与敏感执行信息。
  - [x] 编写 `tests/test_public_source_boundary.py`（32 项 Pages 本地输出脱敏测试全绿）。
- [ ] **3.3 重新打开 #1288 安全验收与五大暴露面治理** (`docs/architecture/current_operations_security_audit_1288.md`)：
  - [x] **五大表面全景审计**：审计公开 Git、历史 Git、Pages、Actions Artifacts 和当前写入路径。
  - [ ] **止血动作 (Stop The Bleed)**：
    - [ ] 修改 `scripts/refresh_cn_27_v1_3_formal.py`，停止将 `operating_state` 嵌入公共回测包的 `lineage.json`（对齐 BYD v1.3 解耦模式）。
    - [ ] 调整 daily workflows (`cn27-current-target.yml` 等)，停止向公开 Git 提交 `strategy_signal_ledgers`。
  - [ ] **迁移至受保护权威存储**：依据 ADR-0004，将实时运行状态完全迁移至 Supabase RLS / 私有凭据存储。
  - [ ] **门禁 A4 严格验收**：编写全仓库直接 Git 扫描与制品扫描测试，在公共仓库 Git 追踪完全脱敏前，**门禁 A4 绝不标记为 PASS，维持 FAIL**。

### Phase 4: 集成 SHA 质量门禁与 v1 Release Candidate (章程已合并、RC 待执行)
- [x] **4.1 合并产品章程与权威基准线**：合并 PR #1276，与 Track B 边界明确对齐 (`8fa9405f4`)。
- [ ] **4.2 消除口径矛盾与基准核验**：
  - [x] 纠正产品记分卡 `product_completion_scorecard_2026-10-25.md`：A4 维持 FAIL，A7 维持 NOT_TESTED / NO-GO，消除与 `w4_release_review_2026-10-25.json` 之间的矛盾。
- [ ] **4.3 统一集成 SHA 质量验证**：在固定集成 SHA 下复跑全量门禁与前后端测试。
- [ ] **4.4 真实生产运行与 Release Candidate 验收**：要求至少完成一次真实成功且隐私合格的每日正式发布，验证灾难恢复/回滚目标，形成 Owner 最终 A7 决策包 (A7 当前维持 NOT_TESTED / NO-GO)。

### Phase 4.5: Gate A1 真实运维韧性与根因修复 (Run 40321512230 专项攻坚)
- [x] **4.5.0 调查并保留 Run 40321512230 独立证据** (`docs/evidence/product_v1/incident_run_40321512230_2026-10-26.md` / `.json`)：
  - [x] 解耦为两个独立问题：INC-20261026-BYD (前瞻时序倒置/退出码缺陷) 与 INC-20261026-CN27 (Tushare限频/Sina成交量误杀)。
  - [x] 完整保留真实截止日 (`2026-10-23` vs `2026-10-26`)、来源记录与 22 个受影响标的阻塞证据。
- [x] **4.5.1 BYD 前瞻观察链路时序倒置与异常分类治理**：
  - [x] 在 `scripts/refresh_byd_v1_3_formal.py` 中将未覆盖目标截止日的前瞻数据错误映射为 `DataBlockedError` (退出码 10)，使未完成前瞻生成时保持 `retained / degraded` 降级发布，不触发致命熔断。
  - [x] 调整 `.github/workflows/byd-prospective-shadow.yml` 定时计划 (前移至 15:45 CST / 07:45 UTC)，跑在 16:30 CST 正式刷新之前。
- [x] **4.5.2 CN 行情 Provider 容错与成交量口径解耦**：
  - [x] 修复 `scripts/data/refresh_selected_pool_prices.py` overlap 校验过严缺陷：将价格/因子硬断言与 volume 解耦，避免因新浪成交量单位差异（股 vs 手）误将有效价格切片报废。
  - [x] 验证 30 项价格刷新与 23 项 v2 回归测试全部通过。
- [x] **4.5.3 端到端回归与测试验证**：验证 BYD 数据缺失下的优雅降级 (exit code 10)，以及解绑成交量后 CN 选股池价格刷新全绿。

### Phase 5: Track B — 通用投研基础设施启动研讨 (PR #1296)
- [x] **5.1 启动 RI-01 与 RI-02 并行推进 (无需等待 v1 发布)**：
  - [x] **RI-01 数据资产与消费者全量血缘审计矩阵** (`docs/architecture/investment_research_data_product_inventory_2026-10-26.md`)：梳理 US87/CN130、参考资产、价格、基本面、公司行为、Alpha158、RDI 事件、数据权利与消费链路。
  - [x] **RI-02 跨领域 PIT 历史信息状态语义 ADR 草案** (`docs/architecture/adr-0005-point-in-time-information-state-semantics.md`)：确立五时间戳模型、不可追溯修订原则、缺失/零值语义及负面测试矩阵 (PIT-NEG-01 ~ PIT-NEG-05)。
- [x] **5.2 推进 PR #1296 落地与 Track B 规划转正**:
  - [x] **5.2.1 同步 PR #1296 至 main 最新基线**：核对 PR #1296 分支与 main 差异，确认 A-P0-01/02 及 RI-01/02 实证项在 main 闭环。
  - [x] **5.2.2 澄清并推荐 D1–D5 产品决策**：向 Owner 明确 D1–D5 的决策建议（全 Agree），将 PR #1296 转为 Ready for Review。
  - [x] **5.2.3 合并 PR #1296 确立官方规划**：PR #1296 已正式合并入 `main` (`8e681b8f9`)，确立 Track B 基础设施章程、基线与 Roadmap。
  - [x] **5.2.4 交付 RI-03A 最小垂直切片设计规范**：撰写并冻结 `docs/architecture/ri-03a-reusable-research-data-slice-spec.md`，确立微切片请求与收据协议，冻结 CN 4 标的正常样本与 688676/301666 真实阻断样本，明确不增加重复数据库或调度器。
  - [x] **5.2.5 落地 RI-03B 第一条可复用 research data slice 实现与 CLI 入口**:
    - [x] **5.2.5.1 [Core] 实现微切片核心读取器与校验器 (`src/data/research_slice.py`)**：实现 `DataSliceRequest`、`DataSliceReceipt`、`get_research_data_slice()`，支持内存切片、PIT 拦截（`announced_at <= cutoff`）、生命周期与股票池核验，返回确定性 `data_hash` 与证据收据。
    - [x] **5.2.5.2 [CLI] 扩展 `alpha data slice` 命令行接口 (`src/cli/main.py`)**：添加 `--market`、`--pool`、`--symbols`、`--start`、`--end`、`--cutoff`、`--price-mode`、`--output` 参数支持，标准输出或文件输出格式化收据，blocked 退出码 10，ready 退出码 0。
    - [x] **5.2.5.3 [Test] 编写完整契约与负面测试套件 (`tests/test_research_data_slice.py`)**：覆盖 Happy Path 样本（CN 4 标的）、PIT 违规阻断（金盘科技 688676）、未上市阻断（301666）、时序越界、源文件字节不变性、命令行调用与脱敏安全（零 operating_state），8 项测试全部通过。
    - [x] **5.2.5.4 [Verify] 全量代码审查与测试通过**：运行 `uv run pytest tests/test_research_data_slice.py`、`uv run ruff check`、`git diff --check`，确保零警告零破坏。
- [x] **5.3 [Track B / RI-04] 双消费者数据复用效果实验与报告 (Dual-Consumer Reuse Experiment)**:
  - [x] **5.3.1 [Core] 实施双消费者实验执行器 (`src/research/dual_consumer_reuse_experiment.py`)**：
    - 消费者一：接入既有 CN 横截面研究（选股池 4 标的动量与波动率特征计算、截面排序）；
    - 消费者二：接入 A 股 RDI 前瞻风险事件 readiness（沪深 300 指数 7/14/28 交易日窗口验证）；
    - 两个独立研究领域 100% 共享 `get_research_data_slice()`，零重复数据清洗。
  - [x] **5.3.2 [Doc] 编写实验报告与证据封存 (`docs/architecture/ri-04-dual-consumer-reuse-experiment.md`)**：详述两个消费者共享切片的架构、Happy/Blocked 场景表现、密码学收据指纹与研究者减负对比。
  - [x] **5.3.3 [Test] 编写跨领域复用测试套件 (`tests/test_ri04_dual_consumer_reuse.py`)**：覆盖消费者一正常/阻断、消费者二正常/尾部阻断（拒绝编造缺失交易日）、收据加密绑定及严禁生成实盘交易信号边界。
  - [x] **5.3.4 [Verify] 全量回归与代码静态检查**：确保 pytest、ruff 与 git diff 全绿通过（14 项投研切片测试在 2.90s 全绿）。
- [x] **5.4 [Track B / RI-05] 开发者与研究员效率度量与摩擦消除 (Researcher Efficiency Metrics & Friction Reduction)**:
  - [x] **5.4.1 [Spec & Baseline] 测量基准与问题定义 (`docs/architecture/ri-05-researcher-efficiency-metrics.md`)**：
    - 固定端到端研究场景：美股科技龙头横截面低波动超额收益研究（`AAPL`, `GOOGL`, `MSFT`, `NVDA` vs `QQQ`）；
    - 实测度量指标：胶水代码减少 89.58%（48 行降至 5 行，DoD 要求 >80%）；手工环节减少 71.43%（7 步降至 2 步，DoD 要求 >60%）；PIT 拦截率从 0% 提升至 100%；数学结果绝对误差 0.00000000；
    - 明确痛点：CLI 终端提取切片仅产生 JSON 收据，丢弃清洗后的表格数据，导致研究员不得不再次编写 Python 代码提取。
  - [x] **5.4.2 [Optimize & Eliminate] 消除冗余路径与最痛接口精简**：
    - 在 `src/cli/main.py` 为 `alpha data slice` 新增 `--data-output` 参数，直接一键导出清洗好的 CSV 数据；
    - 严格 Fail-Closed 负面控制：遇到阻断（如 PIT 违规）严禁生成 CSV，并自动清除残留文件，返回退出码 10；
    - 在 `src/data/research_slice.py` 中为 `DataSliceResult` 引入 `is_ready` 与 `is_blocked` 便捷属性；
    - 坚持零多余数据库引入，零后台守护进程。
  - [x] **5.4.3 [Test & Evidence] 编写度量验证测试与负面证明 (`tests/test_ri05_efficiency_metrics.py`)**：
    - 编写 5 项严密测试：数学等价性断言、效率降低阈值断言、CLI `--data-output` 导出断言、违规阻断不产出数据断言、零数据库治理不变性断言；5 项测试 1.57s 全绿。
  - [x] **5.4.4 [Verify & Gate] 全量回归验证与提交推送**：
    - 运行全量投研数据切片与复用套件（19 项测试 3.40s 全绿）、ruff 静态检查全绿、git diff 零错误。

### Phase 5.5: Track B 深度校准与严谨契约整改 (RI-04/RI-05/PIT 语义深化)
- [x] **5.5.1 [Core / P1] 修复 `alpha data slice --data-output` 破坏性删除缺陷**:
  - 改用安全原子化写入：成功时通过临时文件原子重命名生成；
  - 遇到阻断时严禁调用 `unlink()` 删除用户在指定路径上已存在的任何文件，保持现有文件安全；
  - 编写 `test_ri05_cli_data_output_blocked_does_not_delete_existing_file` 负面断言，保持退出码 10 并明确阻断信息。
- [x] **5.5.2 [PIT Contract / Core] 修正 `src/data/research_slice.py` 契约语义与真实资质分级**:
  - 澄清 `status: ready` 仅代表“满足股票池治理与观测截止日约束 (`end_date <= as_of_cutoff`)”，绝非“全量严格 PIT 认证”；
  - 在 `receipt` 中增加明确资质与局限性声明：`pit_qualification: "observation_cutoff_verified_not_revision_certified"`、`pit_certified: false`，并在 `pit_limitations` 中显式列出供应商首次可得时间未核验与未跟踪多版本修订等局限；
  - 更新切片契约测试，断言资质与局限性声明的存在与合规性。
- [x] **5.5.3 [RI-04 / P1] RDI 真实风险事件绑定与缺失阻断**:
  - 在 `src/research/dual_consumer_reuse_experiment.py` 中，接入 #1272 权威事实源（`docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json` 与 `contracts.py`）；
  - 强制要求提供具备首次发布时间 (`announced_at`)、可得时间 (`available_at`) 及来源哈希的真实风险事件；
  - 当缺少经核验的事件历史（如 2026 年 7–10 月历史事件未完成归档覆盖）时，严格保持 `status: blocked` 与 `reason: blocked_event_pit_coverage`，坚决不虚假放行。
- [x] **5.5.4 [RI-05 / P1] 区分实测与估算，采用真实执行轨迹度量**:
  - 在 `src/research/efficiency_benchmark.py` 中彻底移除固定假设赋值；
  - 明确区分为：定性工作流步骤估算（`heuristic_manual_steps`: 7 步降至 2 步）与真实运行时度量（AST 语句复杂度降低 47.83%、tracemalloc 真实内存开销、perf_counter 执行耗时、实际执行越界查询验证的 PIT 拦截结果）；
  - 报告中绝不再将定性估算的固定百分比宣称为已实证。
- [x] **5.5.5 [Doc & Test / P1] 文档修正、经验沉淀与全量回归**:
  - 更新 `ri-03a-reusable-research-data-slice-spec.md`、`ri-04-dual-consumer-reuse-experiment.md` 与 `ri-05-researcher-efficiency-metrics.md`；
  - 更新测试套件 `test_research_data_slice.py`、`test_ri04_dual_consumer_reuse.py`、`test_ri05_efficiency_metrics.py`（全量 22 项测试全绿）；
  - 记录教训至 `tasks/lessons.md`。

### Phase 5.6: RI-03/04/05 集成验收审查与历史可得性证据再验证
- [x] **5.6.1 [Audit] 三项纠偏缺口闭环客观审查**：核验 RDI 事件来源绑定、执行轨迹度量实测、CLI 非破坏性安全写入的代码与测试实现。
- [x] **5.6.2 [Provenance] 明确历史可得性证据链再验证**：
  - 价格可得性证据：`data/research/market_evidence/{market}/catalog.json` 与逐标的 JSON 哈希；
  - 公司行为可得性证据：`data/research/source_reconciliations/cn27/price-basis-v1.json` 原生公告 PDF、源 URL 与 SHA256；
  - 宏观/参考可得性证据：`configs/pools/reference_instrument_registry_v1.yaml` 与 `#1272` `RiskEvent` 时间戳约束；
  - 资质明确边界：限定为 `observation_cutoff_verified_not_revision_certified`。
- [x] **5.6.3 [Acceptance Artifact] 交付集成验收报告与签发意见**。

### Phase 6.0: 真实投资假设驱动的端到端研究流水线 (OOS & Walk-Forward 落地)
- [x] **6.0.1 [Hypothesis] 真实量化投资假设定义**：明确截面因子超额收益假设（美股核心科技龙头低波动与短期反转复合超额收益），选定治理标的池（`us_selected_equities_v2` 中 8 大龙头：`AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMZN`, `META`, `AVGO`, `TSLA`）与基准（`QQQ`）。
- [x] **6.0.2 [Data Slice] 基础设施切片提取与可得性收据封存**：声明 `DataSliceRequest`，通过 Track B 统一数据切片接口 `get_research_data_slice()` 提取，生成具备 SHA-256 密码学哈希的数据切片，严密遵守观测截止日约束。
- [x] **6.0.3 [OOS & Walk-Forward] 样本外评估与滚动步进设计**：
  - 实现 `src/research/walkforward/contracts.py` 与 `src/research/walkforward/pipeline.py`；
  - 划分 3 轮 Expanding-window Walk-Forward 折叠：Fold 1 (2025H1), Fold 2 (2025H2), Fold 3 (2026 Tail)；
  - 严密防未来函数设计：前序会话 $t-1$ 收盘决定仓位并在第 $t$ 会话执行；技术指标预热严密取自 In-Sample 尾部；越界截止日 fail-closed 阻断。
- [x] **6.0.4 [Sealed Result & Tests] 结果封存、血缘收据与契约测试**：
  - 编写 `tests/test_walkforward_study.py`（5 项契约测试：Happy Path、确定性哈希一致性、未来函数阻断、未上市标的阻断、零多余数据库不变性）；
  - 封存完整研究成果报告 `docs/research/us_tech_vol_reversal_walkforward_2026.md`，密码学研究哈希为 `4b94fc2a7181f77464827eb9083b976f1a86b402296f65d82153f02462b23ba8`；
  - 2025–2026 样本外累积超额收益 +36.37% (总收益 +79.51% vs QQQ +43.14%)，样本外平均夏普比率 1.3907。

### Phase 6.1: Walk-Forward Engine v0.2 方法学深化与计算引擎重构
- [x] **6.1.1 [P0 / Math] Spearman IC 计算公式修复与退化测试**:
  - 重构 `_compute_spearman_ic`，复用 `scipy.stats.spearmanr` 消除样本协方差与总体标准差分母不一致缺陷；
  - 编写独立单测覆盖完全正相关 (+1.0)、完全负相关 (-1.0)、并列排名与常数退化序列 (0.0)。
- [x] **6.1.2 [P0 / Gate] Fail-Closed Fold 完整性与总收益防静默放行**:
  - 重构 `run_walkforward_study()`：若预声明的任意一个 Fold `status != "ready"`，则整体状态必须标记为 `"blocked"`，严禁静默删除缺失折叠并输出残缺总收益；
  - 增加测试断言验证该 Fail-Closed 机制。
- [x] **6.1.3 [P0 / Methodology] 真实 Purge 边际执行与训练期超参数选择 (Train-Select-Freeze-OOS)**:
  - 实际执行 `purged_margin_days`：训练期最后 20 个交易日（180 个样本）严密从训练集中剥离，杜绝前瞻标签或滞后特征污染；
  - 实施 In-Sample 阶段超参数网格选择（`w_rev`, `w_vol`, `top_k`），根据训练期绩效自动优选并**冻结参数**；
  - OOS 测试折叠严格应用对应训练期冻结的参数进行外推模拟，实现真正的 Train $\to$ Select $\to$ Freeze $\to$ OOS。
- [x] **6.1.4 [P1 / Reality] 交易成本、滑点与逐日连续净值敏感性分析**:
  - 引入单边摩擦模型（3 bps 佣金 + 5 bps 滑点，单边 8 bps / 0.0008）；
  - 提供多档成本敏感性检验（0 bps 毛收益、8 bps 标准机构摩擦、15 bps 高摩擦压力测试）；
  - 将各 Fold 逐日净收益按时间序列无缝拼接为全周期连续净值曲线，计算真实的全局连续最大回撤与年化复合 Sharpe 比率。
- [x] **6.1.5 [P1 / Governance] 研究证据收据更新与 PIT 资质声明修正**:
  - 收据与代码中彻底移除将预热数据描述为 "certified" 的措辞，澄清其仅通过观测截止日核验；
  - 明确标注固定 8 标的池存在的幸存者偏差与固定成员假设；
  - 更新并封存报告 `docs/research/us_tech_vol_reversal_walkforward_2026.md`。

### Phase 6.2: Walk-Forward Engine v0.3 会话完整性、绝对 Fail-Closed 与资产负债级摩擦会计
- [x] **6.2.1 [P0 / Session Integrity] 首日会话完整覆盖与锚定日初始化**:
  - 修正测试区间驱动逻辑：将 In-Sample 最后一个有效交易日作为锚定日 ($T_{anchor} \le T_{train\_cutoff}$)，在 $T_{anchor}$ 收盘计算信号并在 $T_{test\_start}$ 首日开盘/收盘间执行第一笔收益；
  - 断言验证：每个 Fold 的输出收益条数 `len(daily_net_returns)` 必须严格等于测试区间所有交易日数 `len(test_sessions)`，折叠边界零丢失（Fold 1 为 122 日、Fold 2 为 128 日、Fold 3 为 170 日，总计 420 交易日全覆盖）。
- [x] **6.2.2 [P0 / Strict Fail-Closed] 消除四类静默放行漏洞与编写独立负面测试**:
  - 候选股票不足 `top_k`：拒绝 `continue` 跳过，强制阻断并标记 `insufficient_candidates_for_top_k`；
  - 基准收益缺失或为 NaN：拒绝填 0.0，强制阻断并标记 `missing_benchmark_data`；
  - 训练样本不足以执行 Purge：拒绝退回未剪裁分支，强制阻断并标记 `insufficient_train_sessions_for_purged_margin`；
  - 无有效模拟收益：强制阻断并标记 `incomplete_simulation_sessions`；
  - 编写 4 项对应负面测试全部绿灯通过。
- [x] **6.2.3 [P1 / Lineage Binding] 实验配置完整绑定至研究收据与研究哈希**:
  - 将完整 `config.to_dict()`、当前 Git Commit SHA、数据依赖切片与评估规则完整嵌入 `study_payload`；
  - 确保任何参数、时间区间或代码版本的变动都会直接改变 `study_hash`。
- [x] **6.2.4 [P1 / Accounting Fidelity] 资产负债级持仓漂移与换手成本一致性**:
  - 实施真实权重漂移计算：$w_{i, t}^{drift} = \frac{w_{i, t-1}(1 + r_{i, t})}{1 + r_{gross, t}}$；
  - 明确换手定义为单边换手率 $\text{Turnover}_t = \frac{1}{2} \sum |w_{i, t}^{target} - w_{i, t}^{drift}|$；
  - 首日从纯现金建仓扣除完整单边费用（Turnover = 1.0），后续换手计入组合漂移再平衡；
  - 敏感性分析：标准 8 bps 净收益 +50.98%（超额 +9.60%），高摩擦 15 bps 净收益 +43.44%（超额 +2.06%）。
- [x] **6.2.5 [Doc & Gate] 更新报告、全量回归与经验沉淀**:
  - 更新 `docs/research/us_tech_vol_reversal_walkforward_2026.md`；
  - 运行全量测试验证（11 项 Walk-Forward 测试 + 22 项 Track B 测试全绿），更新 `tasks/todo.md` 与 `tasks/lessons.md`。

### Phase 6.3: Walk-Forward Engine v0.3.1 交易所日历核验、源码哈希绑定与独立 Fold 清仓闭环
- [x] **6.3.1 [P0 / Lineage & Git Hygiene] 绑定执行源码 SHA-256 并严格要求 Git SHA (严禁未知回退)**:
  - 实现源码 SHA-256 计算：覆盖 `pipeline.py`、`contracts.py`、`research_slice.py`；
  - 严格化 `_get_git_commit()`：如果不在有效 git 仓库或执行失败，禁止返回 `"unknown"`，直接抛出 `RuntimeError` 拒绝发布；
  - 在 `WalkForwardStudyResult` 和 `study_payload` 中嵌入 `code_source_sha256`。
- [x] **6.3.2 [P1 / Calendar Integrity] 接入 `exchange_calendars` 严格校验交易日集合**:
  - 针对 `market == "us"` 接入 `XNYS`，`market == "cn"` 接入 `XSHG`；
  - 对每个 Fold 的训练区间与测试区间分别比对 `calendar.sessions_in_range()`；
  - 若数据切片缺失或多出交易所交易日，严格阻断 (`missing_or_extra_oos_exchange_sessions`)。
- [x] **6.3.3 [P1 / Accounting Closure] 独立 Fold 初始建仓与期末清仓完整摩擦闭环**:
  - 明确选定口径：独立 Fold (Independent Fold) 完整周期核算，首日从现金建仓 (Turnover = 1.0)，末日按收盘漂移权重平仓回现金 (Turnover = 1.0)；
  - `_simulate_portfolio` 增加 `liquidate_at_end: bool = True` 支持；
  - 确保成本完全对称，无未闭合仓位。
- [x] **6.3.4 [P1 / Edge Case] 修复 `purged_margin_days=0` 切片为空列表缺陷**:
  - 正确判断 `purged_margin > 0`，避免 `lst[:-0] == []` 陷阱；
  - 增加专门单测覆盖。
- [x] **6.3.5 [PR #1303 & Receipt Seal] 整理 PR #1303，以新基线封存报告与回归验证**:
  - 优雅关闭不可合并的 PR #1303，统一以 `38bd960dd` 为基础演进；
  - 运行全量测试（13 项 Walk-Forward 测试 + 22 项 Track B 测试全绿），通过 `ruff check` 与 `git diff --check`；
  - 生成最终研究收据并更新 `us_tech_vol_reversal_walkforward_2026.md`；
  - 更新 `tasks/todo.md` 与 `tasks/lessons.md`。

### Phase 6.4: 个人投资记录与 Alpha Engine 解耦接口 (Personal Investment Lens Interface)
- [x] **6.4.1 [Spec & Contract] 实现 `src/research/personal_lens.py` 纯只读持仓透视核心契约与隐私隔离**:
  - 严格只读解析 Obsidian Frontmatter 元数据（`ticker`, `name`, `market`, `asset_type`, `strategy`, `conviction`, `status`）；
  - 绝对隔离个人财务数据：严禁读取、存储、返回或打印 `shares`、`total_cost`、`realized_pnl`、`accounts` 或交易历史记录；
  - 绝对保护用户文件：严禁以写入模式打开或修改用户 Markdown 笔记；
  - 跨层比对 Alpha Engine 治理底座：核验是否在 `us_selected_equities_v2`、`reference_instrument_registry_v1` 及是否存在 `market_evidence` 行情切片。
- [x] **6.4.2 [CLI] 在 `src/cli/main.py` 集成 `alpha personal audit` 命令行入口**:
  - 添加 `alpha personal audit [--dir <path>] [--format table|json]`；
  - 提供人类友好的终端格式化 Markdown 汇总表格以及标准结构化 JSON 输出。
- [x] **6.4.3 [Test] 编写完整契约与安全隔离测试 (`tests/test_personal_lens.py`)**:
  - 隐私隔离断言：给入包含真实成本与股数的 mock 笔记，断言输出对象完全不包含这些字段；
  - 只读安全断言：验证读取前后测试文件修改时间与哈希完全不变；
  - 状态识别断言：覆盖就绪标的、参考资产、现金等价物、跨市场标的及缺失行情标的。
- [x] **6.4.4 [Verify & Report] 真实扫描个人持仓笔记并向用户汇报**:
  - 真实扫描 `D:\Documents\zhihaol\200_Area\Investment\Pool` 中 23 个标的；
  - 生成数据就绪矩阵，输出清晰直观的量化赋能建议。

### Phase 6.5: 补充个人持仓缺失标的行情切片与参考治理 (Supplement Missing Holdings Evidence)
- [x] **6.5.1 [Governance] 在 `configs/pools/reference_instrument_registry_v1.yaml` 注册缺失标的治理身份**:
  - 注册 `PL` (Planet Labs PBC, space_data_equity, comparison_reference)；
  - 注册 `SOXL` (Direxion 3X Semiconductor Bull, leveraged_semiconductor_etf, comparison_reference)；
  - 注册 `SPCX` (Space Exploration Technologies Corp., space_equity, comparison_reference)；
  - 注册 `IQQ` (iShares Nasdaq 100 ETF, equity_etf, comparison_reference)。
- [x] **6.5.2 [Data Materialization] 抓取并物化行情切片与更新清单**:
  - 编写并执行脚本，复用 `YFinanceAdapter` 获取截至 2026-10-26 的高质量日线；
  - 计算标准 bars 与完整 chart_studies (boll20, macd_12_26_9, rsi14)；
  - 物化产出 `data/research/market_evidence/us/symbols/{PL, SOXL, SPCX, IQQ}.json`；
  - 更新 `data/research/market_evidence/us/catalog.json` 清单并绑定 SHA-256。
- [x] **6.5.3 [Test & Verify] 编写回归测试与端到端验证**:
  - 编写 `tests/test_supplemented_holdings_evidence.py`，验证数据切片契约与 `get_research_data_slice` 可切片性；
  - 运行 `alpha personal audit` 验证缺失标的就绪状态（4 标的全绿就绪，0 缺失切片）；
  - 全量回归测试通过，更新 `tasks/todo.md` 与 `tasks/lessons.md`。

### Phase 7.0: 研究工作流第二阶段演进 (Research Study Workspace Phase 2: Multi-Domain Integration)
- [x] **7.0.1 [Contract & Catalog] 扩充 `study_catalog` 与规范模版契约 (`src/research/study_workspace.py`)**:
  - 在 `study_catalog` 中将单一的波动率反转扩展为 4 大活跃研究模版：
    1. `us_tech_vol_reversal_v1` (美股科技股滚动窗口波动率反转研究 - 已有)
    2. `cross_sectional_xgb_v1` (多因子非线性截面排序与行业上限约束研究)
    3. `factor_exploration_v1` (横截面因子 Rank IC / IC-IR 与单调性探索)
    4. `ashare_rdi_v1` (A股 RDI 宏观与系统性风险事件前瞻时间窗响应研究)
  - 扩展 `initialize_study(path, template="us_tech_vol_reversal_v1")` 支持多模版生成；
  - 保持历史 31 项已结项实验 `runnable_here: false` 治理不变式。
- [x] **7.0.2 [Execution Dispatcher] 统一多领域执行引擎与严格 Fail-Closed 闭环**:
  - 核心铁律：所有模版必须 100% 复用 `get_research_data_slice()`，零重复数据清洗，零影子数据库；
  - 分发调度：
    - `walkforward_volatility_reversal` -> 接入 `run_walkforward_study()`
    - `cross_sectional_xgb` -> 接入横截面树模型排序仿真与分位数评价
    - `factor_exploration` -> 接入 `run_cn_cross_sectional_research_experiment()` / IC 统计
    - `ashare_rdi` -> 接入 `run_rdi_forward_event_readiness_experiment()` / #1272 风险事件
  - 统一结果收据：均生成 `study_hash`、`pit_certified: false`、`research_only: true`、`trade_ready: false`，遇到缺失数据均 fail-closed 退出码 10 并记录 `blocked_reasons`。
- [x] **7.0.3 [Show & Compare] 统一只读审查与跨折叠/多指标严格比对**:
  - 扩展 `inspect_study`，无缝自适应展示不同研究家族的特征指标（收益率/回撤、Rank IC/IR、RDI 事件前瞻窗口）；
  - 扩展 `compare_studies`，严格核验同一研究家族、同一数据指纹与代码指纹，输出右减左的纯描述性差异。
- [x] **7.0.4 [Test Suite & Governance Verification] 全面测试覆盖与端到端实证**:
  - 编写 `tests/test_study_workspace_phase2.py` 覆盖 4 大研究家族从 `list` -> `init` -> `run` -> `show` -> `compare` 的完整流程；
  - 运行真实端到端命令，验证退出码与收据原子性落盘；
  - 更新 `tasks/todo.md`、`tasks/lessons.md` 并向用户客观汇报。

### Phase 7.1: 投研工作区深化整改与架构收敛 (Causality Fix, Event Authentication & Lean Modularization)
- [x] **7.1.1 [P0 / Causality] 修复 XGBoost 样本外时序因果性、锚定日初始化与真实回撤计算**:
  - 严格消除同一交易日收盘特征与当天收益混用前视偏差：$T_{t-1}$ 收盘计算特征并产生排名，$T_t$ 会话评估持有收益 $(T_{t-1}, T_t]$；
  - 引入 In-Sample 最后一个有效交易日作为锚定日 $T_{anchor}$，首日测试信号在 $T_{anchor}$ 生成并完整覆盖 $(T_{anchor}, T_{test\_start}]$ 收益；
  - 基准 QQQ 首日收益严格从 $T_{anchor}$ 到 $T_{test\_start}$ 计算，坚决杜绝填 0.0；
  - 修复最大回撤初始基准为 1.0，根据真实逐日换手费用还原毛收益。
- [x] **7.1.2 [P0 / Event Provenance] 严密核验 RDI 事件来源档案，未通过完整认证强制阻断 (`blocked_event_pit_coverage`)**:
  - 依据仓库事实 `docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json`（`historical_pit_event_coverage_complete: false`），建立事件档案真实性核验机制；
  - 严禁对未在权威档案中认证通过的合成事件发放 `status: "ready"`，一律 fail-closed 返回 `blocked_event_pit_coverage` 与退出码 10。
- [x] **7.1.3 [P1 / Modular Architecture] 拆解解耦 `src/research/study_workspace.py` 为领域执行模块 (`src/research/studies/`)**:
  - 将 `study_workspace.py` 瘦身收敛为纯粹的工作区门面（发现、配置、分发、只读比对与持久化）；
  - 将 XGBoost 排序执行逻辑拆分为独立模块 `src/research/studies/xgb_study.py`；
  - 将因子 Rank IC 探索逻辑拆分为独立模块 `src/research/studies/factor_study.py`；
  - 将 RDI 风险事件前瞻响应逻辑拆分为独立模块 `src/research/studies/rdi_study.py`；
  - 消除大单文件代码异味，提高各领域的可测试性与可维护性。
- [x] **7.1.4 [P1 / Research Review] 增强终端展示人类友好格式化报告 (Table / Markdown)**:
  - 在 `alpha research study show` 中新增 `--format table|markdown|json`（默认渲染格式化终端摘要）；
  - 结构化呈现研究假设、时间窗口、标的池、关键业绩（Net Return, Excess, Sharpe, Max Drawdown, Rank IC, IC-IR）、阻断原因与 PIT 局限性，免除研究者直接肉眼解析庞大 JSON 的负担。
- [x] **7.1.5 [Test Suite & Full Regression] 补充时序因果与事件档案负面测试并全量回归**:
  - 编写单测严密验证：修改 $T_t$ 当天数据绝不影响 $T_t$ 的选股权重（防前视断言）；
  - 编写单测验证未认证 RDI 事件严格返回 10 与 `blocked_event_pit_coverage`；
  - 运行全量回归套件并通过 `uv run ruff check` 与 `git diff --check`。

### Phase 4.8: 双轨协同落地推进 (PR #1291 / #1288 止血与 PR #1296 落地)
- [x] **4.8.1 [Track A / P0] 实施 #1288 止血动作 (Stop The Bleed)**:
  - [x] 修改 `scripts/refresh_cn_27_v1_3_formal.py`，停止将 `operating_state`（含敏感 `current_weights`/`target_weights`）嵌入回测包 evidence，对齐 BYD v1.3 解耦模式（`operational_monitoring: { status: "separate_runtime_signal_ledger", runtime_state_embedded: false }`）。
  - [x] 调整 `scripts/run_formal_refresh_transaction.py`，解绑对 `evidence.get("operating_state")` 的陈旧维修断言。
  - [x] 完善 `tests/test_public_source_boundary.py`，增加 `test_cn_27_formal_refresh_decouples_operating_state` 负面断言。
  - [x] 验证 `tests/test_cn27_v1_3_refresh.py` 解耦后测试全绿。
  - [x] 提交并推送到主线 (`b2c414875`)；门禁 A4 保持严格 FAIL，不虚标通过。
- [x] **4.8.2 [Track B / P1] PR #1296 审阅与落地推进**:
  - [x] 检视 PR #1296 三份核心文档：章程、基线与 Roadmap。
  - [x] 将 PR #1296 从 Draft 状态转为 Ready for Review (`gh pr ready 1296`)。
  - [x] 成功合并 PR #1296 入 `main` (`8e681b8f9`)，正式确立 Track B 投研基础设施章程与路线图。

### Phase 4.9: 正式刷新恢复与 PR #1298 审查 (Run 40369078130 专项)
- [x] **4.9.1 [P0] 审查自动生成的 PR #1298 (`automation/formal-backtest-refresh`)**:
  - [x] 确认正式回测与市场数据刷新已成功跑通至 CN 截止日 `2026-10-26`（证明 Ruff 与 BYD 修复完全生效）。
  - [x] **解耦与动态绑定闭环**：在 `b2c414875` 中完成 `scripts/refresh_cn_27_v1_3_formal.py` 解耦脱敏；在 `c812ff51d` 中动态绑定 boundary 测试断言至 canonical catalog；合并 PR #1298 入 `main` (`b1a2451c4`)；全量边界与刷新测试全绿。

### Phase 4.6: 深度代码审查整改与实证矩阵深化 (2026-10-27)
- [x] **4.6.1 [P0] 修正 BYD 异常分类 (`scripts/refresh_byd_v1_3_formal.py`)**:
  - [x] 区分“前瞻数据尚未到达”与其他历史完整性错误（篡改、重复日期、前缀不匹配、契约哈希变更等）。
  - [x] 明确定义 `BYDProspectiveDataMissingError`，仅当该异常触发或明确属于前瞻观测不足时转为退出码 10 (`data_blocked`)；历史篡改/损坏/不一致维持致命退出 (code 1)。
  - [x] 增加负面测试 `test_byd_refresh_main_fails_fatal_on_tampered_history`：历史数据被篡改时绝不返回 10，断言 exit code 1 与 `execution_failed`。
- [x] **4.6.2 [P0] 修正跨源 volume 合并逻辑 (`scripts/data/refresh_selected_pool_prices.py`)**:
  - [x] 历史重叠区间 ($t \le T_{cutoff}$) 严格保持原经过核验的值（包括 prices 和 volume），绝不执行 `keep="last"` 静默覆盖。
  - [x] 仅将新供应商的数据单向追加在历史截止日之后 ($t > T_{cutoff}$)，支持已知 100x/0.01x 单位标准化，未验证的任意比例差异 fail-closed 拦截。
  - [x] 增加测试断言 `test_cutoff_fallback_preserves_historical_overlap_volume_and_bytes`：证明历史重叠区间的 volume 数值与字节保持 100% 不变。
- [x] **4.6.3 [P0] 真正重新打开 GitHub Issue #1288 并治理公开信号写入**:
  - [x] 执行 `gh issue reopen 1288`，线上 Issue #1288 状态已同步置为 OPEN。
  - [x] 更新安全审计架构文档 `current_operations_security_audit_1288.md`，明确复用现有 Strategy Operations、Decision Ledger、私有归档与 RLS 权威，不建立重复 Supabase 状态系统。
  - [x] 确立四大独立负面证明（Public Git, Pages, Actions Artifacts, Write Pipelines），更新 `test_public_source_boundary.py` 断言契约。
- [x] **4.6.4 [P1] 完善 RI-01 数据实证矩阵 (`docs/architecture/investment_research_data_product_inventory_2026-10-26.md`)**:
  - [x] 绑定 `data/research/model_data_bundle_v1/data-components.json` 真实实证数据：补充逐数据集真实记录数、字节大小、时间跨度、缺失比例与缺口详情（明确标注 CN 基本面 127/130 缺失 `301309`/`301666`/`600276`，US 基本面 86/87 缺失 `SBGSY`，Alpha158 不适用 `301666`，杜绝混淆目标池与覆盖度）。
  - [x] 明确 Source Manifest 路径与哈希、首个可得时间 ($t_{available}$) 与数据授权许可。
- [x] **4.6.5 [P1] 修订 RI-02 PIT 信息状态语义 ADR-0005 (`docs/architecture/adr-0005-point-in-time-information-state-semantics.md`)**:
  - [x] 纠正 ADR 层级：明确从属于 ADR-0003，仅扩展数据面语义，不替代产品架构边界，不建立双重权威。
  - [x] 建立三级时间戳证据等级（Grade 1 官方机读、Grade 2 归档快照、Grade 3 事后抓取），对不可证明入库时间的 Grade 3 数据强制执行保守交易日跨期与 fail-closed 阻断。
  - [x] 确立 PIT-NEG-01 ~ PIT-NEG-06 负面测试契约规范。

### Phase 4.7: 运行收尾与代码精简 (Run 40359577256 根因修复)
- [x] **4.7.1 [P0] 修复 Ruff F841 未使用变量 (`tests/test_refresh_selected_pool_prices.py`)**:
  - [x] 在 `test_cutoff_fallback_preserves_historical_overlap_volume_and_bytes` 中增加 `assert (source / "000001.csv").read_bytes() == original_bytes`，同时消除 lint 警告并证明被治理历史源文件字节完全未被就地修改。
  - [x] 本地执行 `uv run ruff check` 确保 0 errors。
- [x] **4.7.2 [P0] 移除 BYD 字符串模式匹配降级分支 (`scripts/refresh_byd_v1_3_formal.py`)**:
  - [x] 删除 `except BYDFormalRefreshError` 中的 `if "do not reach target cutoff" in str(exc):` 字符串分支。
  - [x] 严格保证只有类型化的 `BYDProspectiveDataMissingError` 降级为退出码 10 (`data_blocked`)；所有其他 `BYDFormalRefreshError` 严密保持退出码 1 (FATAL)。
  - [x] 在 `tests/test_refresh_byd_v1_3_formal.py` 增加负面测试：未显式类型化的通用异常即使包含相关文本，也绝不降级为 10。
- [x] **4.7.3 [P1] 本地回归与验证**:
  - [x] 运行受影响的测试用例并全绿 (45 项测试全通过)。
  - [x] 检查 `git diff --check` (0 警告)。
- [x] **4.7.4 [P1] 提交与推送**:
  - [x] 记录 lessons 到 `tasks/lessons.md`。
  - [x] 保持 git 分支整洁，顺利推送到 `origin main`。

### Phase 8.0: Racetrack 最小技术栈与资产净值引擎 (PR #1306 Phase 1 Minimal Stack)
- [x] **8.0.1 [Architecture & Spec] 最小数据底座与 P/Q 引擎技术规范设计 (Architect Subagent)**:
  - [x] 形式化 $P(t, s)$ 价格矩阵契约（时间轴 $T \in$ 交易所日历，资产轴 $S \in$ 治理股票池，总收益复权价）；
  - [x] 形式化 $Q(t, s)$ 持仓事件账本契约（稀疏 JSONL 事件流、SHA-256 哈希链防篡改、仅含目标百分比权重）；
  - [x] 形式化统一净值折算与调仓摩擦公式（逐日权重漂移、单边 8 bps 真实摩擦、NAV 归一化）；
  - [x] 撰写设计规范至 `docs/architecture/racetrack_minimal_stack_spec.md` 并写入 PR #1306。
- [x] **8.0.2 [Implementation: P/Q Engine] 核心引擎与数据切片解析实现 (Developer Subagent)**:
  - [x] 建立 `src/racetrack/` 核心模块包；
  - [x] 实现 `contracts.py`：P 矩阵契约、Q 事件账本数据类；
  - [x] 实现 `matrix.py`：构建 $P(t, s)$ 矩阵（严格基于治理候选池与真实交易所交易日历）；
  - [x] 实现 `ledger.py`：追加和验证 $Q$ 事件账本（哈希链防篡改、无账户隐私敏感信息）；
  - [x] 实现 `engine.py`：纯函数式净值折算（连续净值、最大回撤、单边 8 bps 摩擦、Sharpe 比率）；
  - [x] 实现 `pool_index.py`：美股 87 池等权月度再平衡指数（Pool Index）生成器。
- [x] **8.0.3 [Tests & Invariant Proofs] 严密契约测试与无未来函数断言**:
  - [x] 编写 `tests/test_racetrack_minimal_stack.py`；
  - [x] 覆盖哈希一致性、篡改拦截、漂移与摩擦数学闭环、池指数基准对比及零账户隐私泄露（10 项测试 100% 通过）。
- [x] **8.0.4 [Review & PR Update] 回归验证与更新 PR #1306 文档与提交**:
  - [x] 运行全量测试套件、静态代码分析与 diff 检查；
  - [x] 提交并推送到 `origin/docs/racetrack-vision-2026-10-27`。

### Phase 8.1: Racetrack Phase 1 缺口收敛与方法学闭环 (Methodological Closure & Gap Remediation)
- [x] **8.1.1 [P0 / Initial Friction] 明确初始现金投入与建仓摩擦模型**:
  - [x] 设定 $t_0^-$ 组合为 100% 现金 ($w_{cash}^{drift}=1.0, w_i^{drift}=0.0$)；
  - [x] 首日建仓换手严格计为 $\text{Turnover}_{t_0} = \sum w_i^{target}$，扣除初始摩擦 $\text{Friction}_{t_0}$，首日净值 $\text{NAV}(t_0) = 1.0 - \text{Friction}_{t_0}$；
  - [x] 彻底消除首日满仓免换手与免摩擦漏洞。
- [x] **8.1.2 [P0 / Ledger Constraints] 健全持仓账本约束与防意外覆盖**:
  - [x] `engine.py` 严格校验 `ledger_events` 会话单调递增，杜绝乱序与同日重复事件（拒绝静默覆盖）；
  - [x] `ledger.py` 中 `EventLedger.create()` 默认 `overwrite=False`，已存在文件抛出 `LedgerOverwriteError`；
  - [x] `EventLedger.append()` 校验 `effective_session > last_session`，严禁追加历史或重复交易日。
- [x] **8.1.3 [P0 / Pool Index Qualification] 规范股票池指数成分资格**:
  - [x] `pool_index.py` 坚决杜绝静默剔除缺价/未上市股票重算权重（严格遵守 `silent_exclusion_allowed: false`）；
  - [x] 所有声明成员固定 $1/N_{declared}$（US 87 为 $1/87$），未上市或缺失价格标的所占份额由现金持有 ($w_{cash} = N_{unlisted} / N_{declared}$)；
  - [x] 记录逐月成分资格审计信息。
- [x] **8.1.4 [P1 / PIT & Catalog Certification] 严格数据资格认证与 PIT 截止日阻断**:
  - [x] `matrix.py` 严厉拦截 `end_date > as_of_cutoff` 请求，抛出 `PITViolationError`，坚决杜绝静默截短；
  - [x] 校验 `catalog.json` 权威清单，核验所有候选标的与参考标的收录资质与角色，并在矩阵清单中记录 `catalog_sha256` 与资格声明。
- [x] **8.1.5 [Test Suite & Regression] 编写针对性测试与全量回归**:
  - [x] 扩充 `tests/test_racetrack_minimal_stack.py` 覆盖以上 4 类缺口的负面防御与数学闭环（15 项测试 100% 全绿）；
  - [x] 验证全量单测通过与 `ruff check` 零告警；
  - [x] 提交并推送到 `origin/docs/racetrack-vision-2026-10-27`，向用户客观汇报。

### Phase 8.2: Racetrack 赛道机制与记分体系 (PR #1306 Phase 2: Runner Registry & Season Scoring)
- [x] **8.2.1 [Architecture & Spec] 选手契约与赛道记分技术规范设计 (Architect Subagent)**:
  - [x] 形式化 `RunnerContract`（强制要求 Written Thesis、选股逻辑、调仓逻辑、标的池要求，无 Thesis 严禁参赛）；
  - [x] 形式化 `SeasonScoring` 算法（自然月赛季结算、1M/3M/6M/1Y 滚动窗口、月度截面排名、赛季积分累计）；
  - [x] 编写规范至 `docs/architecture/racetrack_runner_scoring_spec.md` 并写入 PR #1306 文档。
- [x] **8.2.2 [Implementation: Runner & Scoring] 选手注册表与赛道记分器实现 (Developer Subagent)**:
  - [x] 实现 `src/racetrack/runner.py`：`RunnerContract`, `RunnerRegistry`，挂载已有模型选手；
  - [x] 实现 `src/racetrack/scoring.py`：多窗口收益率统计、月度排名矩阵、赛季积分累加与记分板生成；
- [x] **8.2.3 [Tests & Invariant Proofs] 赛马场排位测试套件**:
  - [x] 编写 `tests/test_racetrack_runner_scoring.py`；
  - [x] 覆盖无 Thesis 拒赛、月度赛季自动结算、多窗口排名与积分单调累加。
- [x] **8.2.4 [Review & PR Update] 回归验证与更新 PR #1306 文档与提交**:
  - [x] 运行全量测试套件、静态代码分析与 diff 检查；
  - [x] 提交并推送到 `origin/docs/racetrack-vision-2026-10-27`。

### Phase 8.3: Racetrack 双市场基准覆盖与自维护发布流水线 (PR #1306 Phase 3: Dual Benchmark & Self-Maintenance Pipeline)
- [x] **8.3.1 [Architecture & Spec] 双市场基准与发布协议规范设计 (Architect Subagent)**:
  - [x] 形式化 A 股选股池（CN 130 Equities `cn_selected_equities_v3`）等权基准指数生成模型；
  - [x] 形式化 CSI 300（`000300` / `000300.SH`）宏观基准线与双超额矩阵；
  - [x] 形式化原子化发布流水线协议（`manifest.json`, `scoreboard_{session}.json`, `scoreboard_latest.json`，密码学指纹一致性与 Fail-Closed 幂等保护）；
  - [x] 撰写规范文档至 `docs/architecture/racetrack_pipeline_spec.md` 并对接 PR #1306。
- [x] **8.3.2 [Implementation: Pipeline & CLI] 发布流水线与命令行入口实现 (Developer Subagent)**:
  - [x] 修正 `src/racetrack/matrix.py` 对 CN CSI 300 符号的映射解析与日历对齐；
  - [x] 实现 `src/racetrack/pipeline.py`：`publish_racetrack_projection()`，整合 P/Q 引擎、池指数、宏观基准、已注册选手执行、赛季结算与原子化落盘；
  - [x] 在 `src/cli/main.py` 集成 `alpha racetrack publish [--market us|cn] [--as-of YYYY-MM-DD]` 与 `alpha racetrack show [--market us|cn]`；
  - [x] 确保零个人账户敏感字段（`shares`, `broker`, `account_id`, `pnl` 等）泄露，零外部后台守护进程依赖。
- [x] **8.3.3 [Tests & Invariant Proofs] 双市场与发布幂等测试套件**:
  - [x] 编写 `tests/test_racetrack_pipeline.py`；
  - [x] 验证 CN 130 选股池等权基准指数生成（1/130 权重、无漂移、现金承接未上市）；
  - [x] 验证 CSI 300 基准比对与双超额矩阵；
  - [x] 验证流水线原子发布、`manifest.json` SHA-256 校验与 Fail-Closed 脏写防御；
  - [x] 验证隐私守卫负面拦截。
- [x] **8.3.4 [Review & PR Update] 全量回归验证与提交推送**:
  - [x] 运行全量测试套件、静态扫描与 diff 检查；
  - [x] 提交并推送到 `origin/docs/racetrack-vision-2026-10-27`。

---

## 阶段验收与复盘 (Review Section)
- [x] **Phase 7.1 投研工作区深化整改与架构收敛闭环 (2026-10-27)**:
  - **P0 XGBoost 样本外时序因果性彻底修正**：在 [`src/research/studies/xgb_study.py`](src/research/studies/xgb_study.py) 彻底消除同一会话收盘特征与当天收益混用前视偏差；严格执行 $T_{t-1}$ 收盘计算特征并产生排名，$T_t$ 会话才结算持仓收益 $(T_{t-1}, T_t]$；引入 In-Sample 最后一个有效交易日作为锚定日 $T_{anchor}$ 初始化首日测试持仓；基准 QQQ 首日收益严格从 $T_{anchor}$ 到 $T_{test\_start}$ 真实评估，坚决杜绝填 0.0；修复最大回撤初始基准为 1.0，根据真实逐日调仓摩擦还原毛收益；
  - **P0 RDI 风险事件来源档案严格核验**：在 [`src/research/studies/rdi_study.py`](src/research/studies/rdi_study.py) 接入权威事件档案事实源 `csi300_input_readiness_2026-10-24.json`；由于目前 `historical_pit_event_coverage_complete: false`，任何未在权威档案中核验源哈希的预设/合成事件坚决 fail-closed 阻断，返回 `status: "blocked"`、`blocked_reasons: ["blocked_event_pit_coverage"]` 与退出码 10，绝不发放虚假通过收据；
  - **P1 工作区大单文件彻底拆解模块化**：新建 [`src/research/studies/`](src/research/studies/) 领域模块包，将 XGBoost 排序仿真（`xgb_study.py`）、因子 Rank IC 统计（`factor_study.py`）、RDI 前瞻响应（`rdi_study.py`）及审查格式化（`review_formatter.py`）完整解耦；[`src/research/study_workspace.py`](src/research/study_workspace.py) 瘦身至 375 行纯粹的轻量门面，彻底根治大单文件架构异味；
  - **P1 Research Review 终端优雅呈现**：在 [`src/cli/main.py`](src/cli/main.py) 为 `alpha research study show` 新增 `--format markdown|table|json` 支持；输出美观的 GitHub Flavored Markdown 摘要，清晰呈现研究假设、状态徽章、OOS 净收益、超额收益、Sharpe、回撤、Rank IC 与局限性，免除研究者直接肉眼解析庞大 JSON 的负担；
  - **全量测试与回归验证**：更新 [`tests/test_study_workspace_phase2.py`](tests/test_study_workspace_phase2.py)（12 项测试全绿），全套 21 项 study workspace 测试 18.53s 全绿通过；46 项数据切片与复用回归测试 67.42s 全绿通过；`uv run ruff check` 零告警，`git diff --check` 零违规。
- [x] **Phase 7.0 研究工作流第二阶段演进：多领域投研假设统一接入闭环 (2026-10-27)**:
  - **4 大活跃研究家族统一目录**：在 [`src/research/study_workspace.py`](src/research/study_workspace.py) 将工作区从单一的波动率反转扩展为 4 大活跃研究模版：
    1. `us_tech_vol_reversal_v1`（美股科技股滚动窗口波动率反转研究）
    2. `cross_sectional_xgb_v1`（美股科技股多因子非线性 XGBoost 截面排序研究）
    3. `factor_exploration_v1`（A 股候选池多因子 Rank IC、IC-IR 与单调性探索）
    4. `ashare_rdi_v1`（A 股 CSI 300 宏观与系统性政策风险事件前瞻响应研究）
    保持历史 31 项已结项实验 `runnable_here: false`，杜绝未支持实验混淆为新机会；
  - **单一数据底座与执行分发**：所有模版 100% 共享并复用 [`src/data/research_slice.py`](src/data/research_slice.py)（`get_research_data_slice`），零重复数据清洗、零影子数据库引入；统一调度 `run_walkforward_study`、`run_cross_sectional_xgb_study`、`run_factor_exploration_study` 与 `run_ashare_rdi_study`；
  - **密码学收据与绝对 Fail-Closed 闭环**：所有研究统一生成 SHA-256 `study_hash`、代码源码哈希 `code_source_sha256`、Git Commit SHA，原子落盘至 `artifacts/research_studies/<study_id>/<study_hash>.json`；缺失 RDI 事件、未来事件越界、未上市标的或日历不匹配均强制 `status: "blocked"`，CLI 退出码统一返回 10 并如实封存 `blocked_reasons`；
  - **多模版命令行交互与严格比对**：在 [`src/cli/main.py`](src/cli/main.py) 为 `alpha research study init` 引入 `--template` 参数；`inspect_study` 多态解析 4 大家族指标；`compare_studies` 严格比对同家族、同数据哈希与代码哈希下的纯描述性增量，严厉拦截跨家族胡乱比对；
  - **全量测试与回归验证**：交付全新测试套件 [`tests/test_study_workspace_phase2.py`](tests/test_study_workspace_phase2.py)（10 项测试全绿），全套 19 项 study workspace 测试 14.50s 全绿通过；46 项数据切片与复用回归测试 71.97s 全绿通过；`uv run ruff check` 零告警，`git diff --check` 零违规。
- [x] **Phase 6.5 补充个人持仓缺失标的行情切片与参考治理落地 (2026-10-27)**:
  - **参考资产治理注册**：在 [`configs/pools/reference_instrument_registry_v1.yaml`](configs/pools/reference_instrument_registry_v1.yaml) 正式注册 `PL`、`SOXL`、`SPCX`、`IQQ` 4 个标的，声明其 `comparison_reference` 角色与独立资产类型，杜绝未治理漫游；
  - **标准行情物化与指标计算**：通过 `YFinanceAdapter` 获取权威历史数据，计算生成标准日线、布林带 boll20、MACD (12,26,9) 与 RSI14 技术指标，物化封存为 [`data/research/market_evidence/us/symbols/{PL, SOXL, SPCX, IQQ}.json`](data/research/market_evidence/us/symbols/)；
  - **市场证据清单同步**：更新 [`data/research/market_evidence/us/catalog.json`](data/research/market_evidence/us/catalog.json)，美股覆盖标的由 92 扩充至 96 个，所有数据严格绑定 SHA-256；
  - **切片可提取性验证**：通过 `get_research_data_slice()` 验证 4 标的可无缝作为 `comparison_reference` 提取 PIT 切片；
  - **个人透视体检 0 缺失达成**：运行 `alpha personal audit` 验证，23 个个人标的中 21 个已就绪 (14 核心股 + 7 参考资产)，1 个现金储备，1 个跨市场 (EU)，**缺失切片数量成功降为 0**；
  - **契约测试全绿**：交付 [`tests/test_supplemented_holdings_evidence.py`](tests/test_supplemented_holdings_evidence.py)（5 项测试 100% 通过），全套 33 项 Track B 测试全绿通过。
- [x] **Phase 6.4 个人投资记录与 Alpha Engine 解耦接口落地闭环 (2026-10-27)**:
  - **单向只读与零隐私泄露 (Gate A4)**：在 [`src/research/personal_lens.py`](src/research/personal_lens.py) 实施纯函数式元数据提取器，严格过滤 YAML 前置元数据（`ticker`, `name`, `market`, `asset_type`, `strategy`, `conviction`, `status`），在解析器与数据类两级硬核丢弃所有个人财务敏感字段（`shares`, `total_cost`, `realized_pnl`, `accounts` 等），坚决不将用户真实资金与交易记录导入量化系统；
  - **用户文件只读保护**：绝不以写模式触碰用户 Obsidian 笔记，测试验证扫描前后笔记字节与修改时间 100% 保持不变；
  - **治理底座与行情切片比对**：全量比对 `us_selected_equities_v2`（候选池）、`reference_instrument_registry_v1`（参考资产）与 `data/research/market_evidence/us/catalog.json`（行情切片证据）；
  - **实测审计表现**：真实扫描用户 `D:\Documents\zhihaol\200_Area\Investment\Pool` 中 23 个标的，精准识别 17 个已就绪标的（14 个核心科技股 + 3 个参考 ETF）、4 个缺失切片标的（`IQQ`, `PL`, `SOXL`, `SPCX`）、1 个现金储备（`USD.CASH.IBKR`）与 1 个跨市场标的（`2DG`）；
  - **CLI 终端交互交付**：在 [`src/cli/main.py`](src/cli/main.py) 新增 `alpha personal audit [--dir <path>] [--format table|json]` 命令，输出人类友好的优雅 Markdown 汇总表格与结构化 JSON；
  - **全量测试与回归**：交付 [`tests/test_personal_lens.py`](tests/test_personal_lens.py)（6 项契约与负面测试全绿），41 项全套 Track B 与 Personal Lens 测试 60.14 秒全绿，`ruff check` 零告警，`git diff --check` 零违规。
- [x] **Phase 6.3 Walk-Forward Engine v0.3.1 交易所日历核验与独立 Fold 清仓闭环 (2026-10-27)**:
  - **源码指纹计算**：实现源码 SHA-256 计算覆盖 `pipeline.py`, `contracts.py`, `research_slice.py`，并在 Git 无法解析时抛出 `RuntimeError` 拒绝回退；
  - **交易所官方日历校验**：接入 `exchange_calendars` (`XNYS`/`XSHG`)，严格校验每个 Fold 测试日与交易日集合的一致性；
  - **独立 Fold 现金到现金闭环**：首日现金建仓 (Turnover = 1.0)，每日漂移调仓，末日平仓回现金 (Turnover = 1.0)，消除未平仓免费午餐；
  - **切片负零修复**：修复 `purged_margin_days=0` 下 `lst[:-0]` 为空列表缺陷；报告与收据完成封存更新。
- [x] **Phase 6.1 Walk-Forward Engine v0.2 方法学深化与计算引擎重构闭环 (2026-10-27)**:
  - **P0 统计与数学口径修复**：重构 `_compute_spearman_ic`，复用 `scipy.stats.spearmanr`，消除 `np.cov` 与 `np.std` 分母自由度不一致导致 IC > 1.0 的缺陷；编写单测验证完全正相关 (+1.0)、完全负相关 (-1.0)、并列排名及常数退化序列 (0.0) 严格通过。
  - **P0 Fail-Closed 折叠完整性门禁**：若预声明的任意一个 Fold `status != "ready"`，整体研究强制输出 `status: "blocked"` 并清零综合绩效指标，在 `blocked_reasons` 显式列出阻断折叠与原因，坚决杜绝静默剔除失败折叠而发布残缺收益。
  - **P0 真实 Purge 边际执行与在样本参数选择冻结 (Train-Select-Freeze-OOS)**:
    - 实际执行 `purged_margin_days=20`：训练集末尾 20 个交易日（180 个样本）严密从训练集中剥离；
    - 在样本内针对 `w_rev`, `w_vol`, `top_k` 执行网格搜索，根据在样本净夏普比率自动优选并**冻结参数**；
    - 样本外测试期严格采用对应折叠冻结的参数外推，实现从“分段固定回测”到“真正的滚动参数优化与检验 (WFO)”的跨越。
  - **P1 真实交易成本、滑点与连续净值敏感性**：
    - 引入单边 8 bps（3 bps 佣金 + 5 bps 滑点）交易摩擦，Fold 1/2/3 净收益分别为 +6.02%、+18.95%、+21.87%，全周期累积产生 8.77% 的交易摩擦损耗；
    - 提供三档摩擦敏感性检验：0 bps 毛收益 (+62.46%)、8 bps 标准机构摩擦 (+53.69%，超越 QQQ 10.55 个百分点)、15 bps 高摩擦压力测试 (+46.44%)；
    - 逐日无缝拼接全周期净值曲线，计算真实的连续整体最大回撤 (-21.02%) 与连续整体年化 Sharpe (1.1363)。
  - **P1 向量化性能优化与 PIT 资质声明规范**：
    - 仿真器底层重构为 Numpy 连续数组与整数索引集合运算，将测试执行耗时从 320 秒压降至 31 秒（提速 10 倍）；
    - 收据与文档彻底移除将切片描述为 "certified" 的措辞，澄清其仅满足观测截止日核验，并明确固定 8 标的池的幸存者偏差；
    - 更新并封存报告 [`docs/research/us_tech_vol_reversal_walkforward_2026.md`](docs/research/us_tech_vol_reversal_walkforward_2026.md)，最新研究散列为 `fe7824758bc1f5b9e98851bcaecabbffa79eae494e92a6d8e766fc15592bb6c7`；
    - 全量 29 项投研切片与 Walk-Forward 测试在 38.43 秒内 100% 通过。
- [x] **Phase 6.0 真实投资假设驱动的端到端 Walk-Forward 研究流水线闭环 (2026-10-27)**:
  - **量化假设与标的池验证**：基于 `us_selected_equities_v2`（87 标的）中 8 大核心科技龙头（`AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMZN`, `META`, `AVGO`, `TSLA`）与基准 `QQQ`，验证“低实现波动率叠加短期 5 日价格反转”截面选股假设。
  - **Track B 投研数据面闭环**：全流程 100% 通过 [`get_research_data_slice()`](src/data/research_slice.py) 提取内存切片，无任何本地 flat CSV 或新增 DuckDB/SQLite 影子存储；所有切片严格遵循观测截止日约束 (`as_of_cutoff`)，生成确定性 SHA-256 数据收据。
  - **无未来函数滚动步进设计**：
    - 严格 Expanding-window 3 折叠：Fold 1 (2025H1), Fold 2 (2025H2), Fold 3 (2026 Tail)；
    - 交易日前序决策执行边界：$t-1$ 收盘特征决定仓位，在 $t$ 日评估收益；
    - 样本外指标预热严密取自 In-Sample 尾部，严禁前向污染。
  - **实证超额收益与回撤表现**：
    - Fold 1: 收益 +6.33% vs QQQ +8.40%（超额 -2.07%，夏普 0.5380，最大回撤 -24.38%）；
    - Fold 2: 收益 +20.21% vs QQQ +12.58%（超额 +7.63%，夏普 1.7322，最大回撤 -7.58%）；
    - Fold 3: 收益 +40.44% vs QQQ +17.29%（超额 +23.15%，夏普 1.9020，最大回撤 -14.05%）；
    - 累计样本外复合收益：**+79.51% vs QQQ +43.14%**，**累积净超额收益 +36.37%**，样本外平均夏普 **1.3907**。投资假设在 2025–2026 样本外获得强实证支撑。
  - **契约测试与密码学成果封存**：
    - 交付 [`tests/test_walkforward_study.py`](tests/test_walkforward_study.py)（5 项测试 100% 通过），包含 Happy Path、确定性哈希一致性、未来函数阻断、未上市标的阻断及零辅助数据库治理断言；
    - 封存完整研究报告 [`docs/research/us_tech_vol_reversal_walkforward_2026.md`](docs/research/us_tech_vol_reversal_walkforward_2026.md)，密码学研究散列为 `4b94fc2a7181f77464827eb9083b976f1a86b402296f65d82153f02462b23ba8`；
    - 严格遵守 `research_only=true`, `trade_ready=false`, `trade_signal=false`。
- [x] **RI-03B 可复用投研数据切片读取器与 CLI 落地闭环 (2026-10-27)**:
  - **核心模块交付**：在 [`src/data/research_slice.py`](src/data/research_slice.py) 实现纯函数式 `get_research_data_slice()`，支持内存切片、PIT 拦截（`announced_at <= cutoff` 与 `end_date <= cutoff`）、生命周期上市日前拦截（`SYMBOL_NOT_YET_LISTED`）与股票池治理核验。
  - **命令行集成**：在 [`src/cli/main.py`](src/cli/main.py) 扩展 `alpha data slice` 命令，支持 `--market`、`--pool`、`--symbols`、`--start`、`--end`、`--cutoff`、`--price-mode`、`--output`，返回格式化收据 JSON；`status == "ready"` 时退出码 0，`status == "blocked"` 时退出码 10 (`data_blocked`)。
  - **测试全绿验证**：交付 [`tests/test_research_data_slice.py`](tests/test_research_data_slice.py)（8 项测试全通过，耗时 1.51s）：
    1. Sample 1 确定性验证：CN 4 标的 (`000001`, `000338`, `600519`, `688008`) 2,596 行数据，两次执行 `data_hash` 确定性完全一致；
    2. Sample 2 跨期分红 PIT 拦截：金盘科技 (`688676`) 面对未来公告 (`2026-09-23`) 与越界日期严密返回 `blocked` 与结构化原因；
    3. Sample 3 上市前越界拦截：标的 `301666` 在 `2026-04-16` 上市前查询严格返回 `SYMBOL_NOT_YET_LISTED`；
    4. 市场与选股池隔离：跨市场或未入池标的 fail-closed 拦截；
    5. 源文件不可变性：证明执行前后市场证据原始 JSON 字节 100% 保持不变；
    6. 治理不变式：断言收据严格包含 `research_only=true`、`trade_ready=false`、`academic_and_internal_research_only`；
    7. 隐私合规负面证明：验证切片与收据绝无 `operating_state`、`current_weights` 等实盘敏感词；
    8. CLI 执行与退出码：验证 CLI 命令就绪退出 0、阻断退出 10 以及收据文件落盘。
  - **静态检查**：`uv run ruff check` 0 errors，`git diff --check` 0 警告。
- [x] **RI-03A 可复用投研数据切片协议与参考样本规范交付 (2026-10-27)**:
  - **规范落地**：完成并封存 [`docs/architecture/ri-03a-reusable-research-data-slice-spec.md`](docs/architecture/ri-03a-reusable-research-data-slice-spec.md)，明确了投研微切片请求 (`DataSliceRequest`) 与不可变收据 (`DataSliceReceipt`) 的 JSON Schema。
  - **现状与缺口审计**：梳理现有 `alpha data`、Profile Gate、Market Evidence 与复权引擎，确立“缺乏参数化微切片读取与收据生成协议”为唯一真实缺口，杜绝重复引入新数据库与调度器。
  - **三大冻结样本确立**：
    1. Happy Path 样本：CN 4 标的 (`000001`, `000338`, `600519`, `688008`) 在 `2024-01-01` 至 `2026-09-04` 的 PIT 合规数据切片；
    2. Honest Blocked 样本：金盘科技 (`688676`) 2026-09-23 跨期分红公告 PIT 违规 fail-closed 拦截；
    3. 生命周期阻断样本：新标的 (`301666`) 上市前区间请求拦截。
  - **RI-03B 实施计划就绪**：规划在 `src/data/research_slice.py` 与 `alpha data slice` 实现纯函数式切片提取器，配套 7 项契约与负面测试。
- [x] **Phase 4.8 双轨协同落地复盘 (2026-10-27)**:
  - **Track A (#1288 止血与解耦)**：修改 `scripts/refresh_cn_27_v1_3_formal.py`，彻底移除了回测包中包含敏感权重明文的 `operating_state`，与 BYD v1.3 的 `operational_monitoring` 解耦模式对齐；修改 `scripts/run_formal_refresh_transaction.py` 删除了旧有维修断言；在 `tests/test_public_source_boundary.py` 新增负面测试并全绿；提交至 `main` (`b2c414875`)。Gate A4 严格维持 FAIL。
  - **Track B (PR #1296 基础设施规划转正与合并)**：检视投研基础设施章程、审计基线与实施路线图三份文件，将 PR #1296 从 Draft 转为 Ready for Review，并成功合并入 `main` (`8e681b8f9`)，正式确立 Track B 基础设施章程与 D1–D5 决策。
  - **真实生产运行突破**：每日自动化正式回测与市场数据刷新 (`formal-backtest-refresh.yml`) 在 Run 40369078130 中突破了数日来的故障阻塞，顺利跑通至 CN 截止日 2026-10-26，并自动提交了 PR #1298。
  - **Gate A4 铁律拦截**：由于 PR #1298 在 `b2c414875` 解耦之前构建，其 CN_27 lineage 仍携带旧式 `operating_state`，因此严禁盲目直接合并 PR #1298，需由主线最新 clean run 重新生成覆盖或进行脱敏。
- [x] **Phase 4.7 运行收尾与代码精简完成复盘 (2026-10-27)**:
  - **Ruff F841 彻底修复**：在 `tests/test_refresh_selected_pool_prices.py` 中引入对 `original_bytes` 的正向断言，证明拉取 fallback 数据时不仅内存中的重叠量价一致，磁盘上的历史基准源文件字节也 100% 保持不变，消除 CI `prepare` 阶段中断风险；`uv run ruff check` 0 errors。
  - **BYD 异常严格类型化**：彻底删除了 `scripts/refresh_byd_v1_3_formal.py` 中的子串匹配分支，仅放行明确的 `BYDProspectiveDataMissingError` 为退出码 10，任何通用或其他类型的异常一律退出码 1 (FATAL)；新增负面测试 `test_byd_refresh_main_fails_fatal_on_generic_error_even_with_cutoff_message` 验证通过。
  - **测试全绿**：40 项 BYD/行情刷新测试 + 5 项安全边界测试 100% 通过，`git diff --check` 无违规。
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
  - **PR #1291** (Security ADR / #1288) 合并入 `main` (`2940d4104`)：批准并固化当前运行数据与公开历史投影边界方案，锁定未来脱敏投影实现契约。
- [ ] **Phase 3: 公开投影修复已合并、完整隔离待验证 (2026-10-26)**:
  - **脱敏投影实现 (#1288)**：改造 `sync-formal-model-runs.mjs`，静态构建时自动剥离 `lineage.json` 中 `source_evidence.operating_state`（含敏感 `current_weights` 与 `target_weights`），重新计算脱敏后的 section sha256 与 `manifest.bundle_id`，并声明 `projection_contract: public_historical_projection_v1` 与权威 source identity 溯源绑定。
  - **发布验证器升级**：在 `pages_release_verification.py` 中对所有发布 section 实施递归敏感字段阻断（禁止 `operating_state`，lineage 额外禁止 `current_weights`/`target_weights`），并严密校验公开 projection 与 canonical bundle 的加密绑定关系。
  - **审查缺陷与未解决范围**：经核实，`tests/test_public_source_boundary.py` 仅覆盖了本地生成的 Pages 公开静态目录；而公共 GitHub 仓库仍然追踪包含敏感 `operating_state` 的原始决策账本与历史 `lineage.json` (Blob `13489a0d...`)。在公共 Git 仓库中的敏感信息剥离或私有化闭环前，**门禁 A4 绝不提前放行，维持 FAIL**。
- [ ] **Phase 4: 章程已合并、RC 待执行 (2026-10-26)**:
  - **PR #1276 合并入 `main` (`8fa9405f4`)**：完成产品章程与 Scorecard 基准线合并，锁定 Direction A v1 与 Track B 边界。
  - **RC 验收缺口**：Release Candidate 尚未验收。当前缺少统一集成 SHA 下的真实生产发布成功证明（Run 40321512230 出现新的失败），且缺少隐私合格的灾难恢复验证。门禁 A7 维持 NOT_TESTED / NO-GO。
- [x] **2026-10-26 专项攻坚完成复盘 (4 项专项任务完全交付)**:
  - **P0 #1288 安全验收重新打开与五面全景审计**：交付 `docs/architecture/current_operations_security_audit_1288.md`，覆盖公开 Git、历史 Git、Pages、Actions 制品和当前写入路径 5 大表面；Gate A4 严格维持 FAIL；更新 `tests/test_public_source_boundary.py`（4 项测试全绿）。
  - **P0 Run 40321512230 调查与双缺陷解耦**：交付 `docs/evidence/product_v1/incident_run_40321512230_2026-10-26.md` 与 `.json`，分离 INC-20261026-BYD (前瞻时序倒置/未捕获异常) 与 INC-20261026-CN27 (Tushare限频/Sina成交量误杀)；完成 BYD exit code 10 降级处理、前瞻 Cron 前移至 15:45 CST、selected pool 价格 overlap 排除成交量硬比较；75 项回归测试与前端构建全部通过。
  - **P1 纠正 Release Gate 状态**：修正 `docs/product/product_completion_scorecard_2026-10-25.md` 与 `tasks/todo.md`，将 Phase 3 定位为“公开投影修复已合并、完整隔离待验证”（A4 FAIL），Phase 4 定位为“章程已合并、RC 待执行”（A7 NOT_TESTED / NO-GO），消除了口径矛盾与不实验收。
  - **P1 启动 #1296 Track B 投研基础设施**：交付 RI-01 全量数据产品与血缘审计矩阵 `docs/architecture/investment_research_data_product_inventory_2026-10-26.md` 以及 RI-02 PIT 跨领域历史信息状态语义 ADR `docs/architecture/adr-0005-point-in-time-information-state-semantics.md`，建立五时间戳模型与 PIT-NEG-01 ~ PIT-NEG-05 负面测试。

---

## Racetrack Minimal Stack Spec 任务 (Phase 1 Spec)

- [x] **R1. 撰写核心系统规范文档 (`docs/architecture/racetrack_minimal_stack_spec.md`)**:
  - [x] **P(t, s) 市场价格矩阵规范**：
    - [x] 时间轴 $T$：基于 `exchange_calendars` (XNYS / XSHG) 的真实交易日历与对齐规则；
    - [x] 资产轴 $S$：严格绑定治理候选池 `us_selected_equities_v2.yaml` (87 标的) 与基准参考池 `QQQ` (总 88 标的)；
    - [x] 价格源：读取 `data/research/market_evidence/us/symbols/{symbol}.json`，明确为复权总收益价 (Adjusted Total Return)；
    - [x] 清单与哈希：输出包含 `matrix_sha256` 密码学指纹的行情清单 (Manifest)。
  - [x] **Q(t, s) 持仓事件账本规范**：
    - [x] 格式：稀疏 JSONL 事件流 (Sparse Event Stream)；
    - [x] Schema 契约：定义 `event_id`, `parent_hash`, `timestamp_utc`, `effective_session`, `runner_id`, `runner_version`, `target_weights`, `cash_weight`, `reason`, `event_hash`；
    - [x] 哈希链防篡改：逐级链接前序事件哈希，首事件 `parent_hash = "0" * 64`，清单记录 tip anchor；
    - [x] 绝对隐私隔离：严禁出现实盘个人账户敏感信息 (shares, total_cost, broker 等)。
  - [x] **资产价值与统一净值折算引擎数学规范 (V & NAV Engine)**：
    - [x] 起始基准：$V(t_0) = 1.0$；
    - [x] 逐日权重漂移公式：$w_{i, t}^{drift} = \frac{w_{i, t-1}(1 + r_{i, t})}{1 + r_{gross, t}}$；
    - [x] 单边换手率定义：$\text{Turnover}_t = \frac{1}{2} \sum |w_{i, t}^{target} - w_{i, t}^{drift}|$；
    - [x] 交易摩擦模型：$\text{Friction}_t = \text{Turnover}_t \times \text{friction\_rate}$ (默认单边 8 bps，支持 0 bps / 15 bps 敏感性)；
    - [x] 净收益率与连续净值：$r_{net, t} = r_{gross, t} - \text{Friction}_t$，$NAV(t) = NAV(t-1) \cdot (1 + r_{net, t})$；
    - [x] 关键评价指标：连续最大回撤 (MDD)、年化超额收益 (Excess Return vs QQQ)、年化夏普比率 (Sharpe)。
  - [x] **自建股票池指数 (Pool Index) 规范**：
    - [x] 美股 87 选股池等权基准：每个自然月首个交易日执行等权再平衡 ($w_i = 1 / 87$)，全月自然漂移；
    - [x] 同样通过上述统一引擎折算净值，作为赛道内部第一参考基准线。
- [x] **R2. 更新 PR #1306 说明文档 (`docs/product/racetrack_vision_2026-10-27.md`)**:
  - [x] 在末尾追加第 12 节，简明链接并概述该 Minimal Stack 实施规范。
- [x] **R3. 验证与审查**:
  - [x] 检查所有公式、Schema、字段与约束；
  - [x] 确认合规性 (`research_only=true`, `trade_ready=false`, 隐私隔离)；
  - [x] 记录 Review 并向主 Agent 发送完整架构设计总结。

### Review & Completion Summary (2026-10-28)
- 交付规范文档：`docs/architecture/racetrack_minimal_stack_spec.md` (完整包含 P 矩阵、Q 账本、V/NAV 引擎、自建等权指数四大模块，配套 8 项负面测试矩阵与 Mermaid 架构图)；
- 更新视觉文档：`docs/product/racetrack_vision_2026-10-27.md`（末尾追加 §12 实施规范链接与要点摘要）；
- 质量检查：`git diff --check` 0 警告，文档完全对齐 ADR-0003, ADR-0005 与 PR #1306。

---

## Phase 1 Minimal Stack 代码落地与测试 (Phase 1 Minimal Stack Implementation)

- [x] **M1. 契约与序列化模块 (`src/racetrack/contracts.py`, `src/racetrack/__init__.py`)**:
  - [x] 定义 `PriceMatrix`, `RebalanceEvent`, `EngineConfig`, `SimulationResult`, `NAVPoint` 等不可变契约；
  - [x] 实现 Canonical JSON 序列化与哈希计算；
  - [x] 严密隐私隔离守卫白名单/黑名单校验（`shares`, `total_cost`, `broker`, `account_id`, `pnl` 等出现立即抛出 `PrivacyViolationError` / `ValueError`）。
- [x] **M2. 市场价格矩阵构建器 (`src/racetrack/matrix.py`)**:
  - [x] 基于 `exchange_calendars` (US -> `XNYS`) 解析官方交易日历与区间会话；
  - [x] 读取候选池配置 `us_selected_equities_v2.yaml` (87 标的) 与基准参考 `QQQ`；
  - [x] 从 `data/research/market_evidence/us/symbols/{symbol}.json` 提取复权日线；
  - [x] 严禁 forward-fill，缺失会话置为 `np.nan`；
  - [x] 输出包含确定性 `matrix_sha256` 的 `PriceMatrix` 结构。
- [x] **M3. 稀疏持仓事件账本 (`src/racetrack/ledger.py`)**:
  - [x] 实现 `EventLedger` 类：创建、追加、链式哈希校验 (`verify()`)；
  - [x] 创世事件绑定 64 个 `0`，后续事件严格 SHA-256 递归绑定；
  - [x] 篡改检测抛出 `LedgerTamperedError`；
  - [x] `to_dense_panel(sessions)` 将稀疏事件流展开为每日密集目标权重面板。
- [x] **M4. 统一资产净值折算引擎 (`src/racetrack/engine.py`)**:
  - [x] 实现 `simulate_portfolio(matrix, ledger_events, config)`；
  - [x] 起始点归一化 $V(t_0) = 1.0$；
  - [x] 逐日自然权重漂移公式：$w_{i, t}^{drift} = \frac{w_{i, t-1}(1 + r_{i, t})}{1 + r_{gross, t}}$；
  - [x] 单边换手率：$\text{Turnover}_t = \frac{1}{2} \sum |w_{i, t}^{target} - w_{i, t}^{drift}|$；
  - [x] 线性交易摩擦：$\text{Friction}_t = \text{Turnover}_t \times \text{friction\_rate}$ (默认 8 bps)；
  - [x] 净收益率与连续净值累乘更新：$\text{NAV}(t) = \text{NAV}(t-1) \cdot (1 + r_{net, t})$；
  - [x] 计算累积收益率、CAGR、年化波动率、年化夏普 (无风险 2%)、最大回撤 (MDD)、年化超额 (vs QQQ)、累积换手率。
- [x] **M5. 自建选股池等权指数 (`src/racetrack/pool_index.py`)**:
  - [x] 识别每个自然月首个交易日，生成等权再平衡事件 ($1/87$)；
  - [x] 自然月内其余交易日自然漂移，单边换手率为 0；
  - [x] 调用统一净值引擎产生内部第一参考基准线 (Pool Index NAV)。
- [x] **M6. 完整测试套件 (`tests/test_racetrack_minimal_stack.py`)**:
  - [x] TEST-RT-01：交易日历对齐与缺失数据 NaN 填充；
  - [x] TEST-RT-02：价格矩阵 SHA-256 确定性与源文件不变性；
  - [x] TEST-RT-03：Q 账本哈希链完整性校验与中途篡改拦截；
  - [x] TEST-RT-04：隐私阻断负面测试；
  - [x] TEST-RT-05：权重漂移与单边换手守恒数学断言；
  - [x] TEST-RT-06：摩擦敏感性检验 (0 bps > 8 bps > 15 bps)；
  - [x] TEST-RT-07：美股 87 池月度等权指数生成与基准 QQQ 超额计算；
  - [x] TEST-RT-08：端到端真实数据全生命周期演练。
- [x] **M7. 运行验证与代码质量门禁**:
  - [x] `uv run pytest tests/test_racetrack_minimal_stack.py -v` 验证全部 10 项测试全绿通过；
  - [x] `uv run ruff check` 确保零告警。
- [x] **M8. 汇报与交付**:
  - [x] 记录结果 Review 并向主 Agent 回复交付报告。

### Review & Completion Summary (Phase 1 Minimal Stack - 2026-10-28)
- **交付包 `src/racetrack/`**:
  - `contracts.py`: 不可变契约数据类（`PriceMatrix`, `RebalanceEvent`, `EngineConfig`, `SimulationResult`, `NAVPoint`），规范化 Canonical JSON 序列化与哈希计算，严格的个人敏感账户隐私守卫（违规立即阻断抛出 `PrivacyViolationError`）。
  - `matrix.py`: 官方交易日历对齐（US -> `XNYS`）、US 87 + QQQ 标的加载、严禁 forward-fill 的 NaN 保护机制、确定性 `matrix_sha256` 生成。
  - `ledger.py`: `EventLedger` 稀疏 JSONL 账本，首事件绑定 64 个 `0`，逐级 SHA-256 递归绑定，篡改拦截抛出 `LedgerTamperedError`，支持密集目标权重面板展开。
  - `engine.py`: 统一资产净值折算引擎，精确实现起始点 1.0 归一化、自然权重漂移、单边换手率守恒计算、线性摩擦扣除、连续净值更新及完备指标统计（CAGR、夏普、MDD、超额等）。
  - `pool_index.py`: 美股 87 等权基准指数生成器，实现自然月首个交易日再平衡与月内自然漂移零换手。
  - `__init__.py`: 统一导出核心 API 与异常类型。
- **测试套件 `tests/test_racetrack_minimal_stack.py`**:
  - 10 项测试用例 100% 覆盖 TEST-RT-01 ~ TEST-RT-08 以及非法标的/权重超限负面用例。
  - 测试结果：`10 passed in 21.39s`。
  - 静态检查：`uv run ruff check` 0 errors / 0 warnings。

---

## Phase 2 赛道机制：选手准入与赛马记分系统架构设计 (Phase 2 Spec)

- [x] **P2.1 选手准入契约与注册表规范设计 (`RunnerContract` & `RunnerRegistry`)**:
  - [x] 确立 `RunnerContract` 实体强类型契约（`runner_id`, `runner_version`, `pool_id`, `benchmark_symbol`, `thesis`, `selection_logic`, `rebalance_logic`, `track_condition_associations`）；
  - [x] 强制前置投资假设门禁（`ThesisMissingError`，少于 30 字符或空白严格拦截）；
  - [x] 规范纯函数式 `run(matrix: PriceMatrix, ledger_path: Path) -> SimulationResult` 回放与账本落盘接口；
  - [x] 规范 `RunnerRegistry` 发现、资产池白名单审核（拦截未注册与基准标的）与多进程并发回放。
- [x] **P2.2 单月赛季与多周期时间窗口规范 (`Monthly Season & Rolling Windows`)**:
  - [x] 依据 §11.1 裁定单月赛季（Monthly Season）默认规则，以交易所日历（`XNYS`）月初首日开跑，月末最后交易日收盘统一结算；
  - [x] 滚动多周期评估窗：1M（月度）、3M（季度）、6M（半年）、1Y（年度）复合净收益率；
  - [x] 双基准超额收益数学模型：相对纳斯达克 100 大盘（QQQ）与美股 87 等权池指数（US87_EW）超额收益。
- [x] **P2.3 赛马记分与月度排名算法 (`Race Scoring & PointsRuleV1`)**:
  - [x] 月度截面降序排序模型（Monthly Cross-Sectional Rank）；
  - [x] 版本化赛季积分规则矩阵 `PointsRuleV1`（1st: 10, 2nd: 6, 3rd: 4, 4th: 2, 5th: 1, >5th: 0）；
  - [x] 稳定性度量（Persistence Indicator）：前 50% 胜率月份占比、最长连续得分月数、月度排名波动率；
  - [x] 机制杜绝单日暴涨后视偏差的数学论证。
- [x] **P2.4 Scoreboard 前台记分板数据投影契约 (`Scoreboard Projection Contract`)**:
  - [x] 统一归一化 NAV 曲线中心视图与双基准对齐；
  - [x] 严密结构化 JSON Schema 规范（`racetrack_scoreboard_v1.json`）；
  - [x] 天气归因指标映射与零计算纯消费前台契约。
- [x] **P2.5 配套测试矩阵与 Mermaid 架构图**:
  - [x] 绘制选手准入生命周期状态机与记分引擎流水线 Mermaid 流程图；
  - [x] 制定 10 项严密测试用例（TEST-RT-P2-01 ~ TEST-RT-P2-10）。
- [x] **P2.6 核心技术文档归档与 PR #1306 链接**:
  - [x] 输出完整规范文档 `docs/architecture/racetrack_runner_scoring_spec.md`；
  - [x] 在 `docs/product/racetrack_vision_2026-10-27.md` 末尾追加第 13 节。

### Review & Completion Summary (Phase 2 Spec - 2026-10-28)
- **核心交付文档**:
  - `docs/architecture/racetrack_runner_scoring_spec.md`: 涵盖 9 大章节，系统化定义了选手契约、注册表审核、单月赛季划分、滚动多周期评估、`PointsRuleV1` 赛马记分算法、前台记分板 JSON Schema 与 10 项负面/边界测试用例。
  - `docs/product/racetrack_vision_2026-10-27.md`: 追加第 13 节，建立对 Phase 2 实施规范的正式引用与核心系统摘要。

---

## Phase 2 代码落地：Runner 注册表与 Race Scoring 赛马记分系统实现

- [x] **R1. 扩充核心契约 (`src/racetrack/contracts.py`)**:
  - [x] 增加异常类 `ThesisMissingError(ValueError)`；
  - [x] 增加数据类 `MonthlyRankPoint` (包含 month, rank, total_runners, monthly_net_return, monthly_excess_vs_qqq, monthly_excess_vs_pool, points_earned)；
  - [x] 增加数据类 `ScoreboardEntry` (包含 runner_id, runner_version, thesis_summary, season_points, current_rank, return_1m, return_3m, return_6m, return_1y, excess_vs_qqq, excess_vs_pool, max_drawdown, sharpe_ratio, persistence_ratio, monthly_ranks)；
  - [x] 增加数据类 `Scoreboard` (包含 schema_version, as_of_session, season_id, pool_id, benchmark_symbol, entries)，提供 `to_dict()`, `to_json()`, `from_dict()`, `from_json()` 方法；
  - [x] 在 `src/racetrack/__init__.py` 中导出新增契约与异常。
- [x] **R2. 选手契约与注册表实现 (`src/racetrack/runner.py`)**:
  - [x] `RunnerContract` 基类：
    - [x] 字段：runner_id, runner_version, pool_id, benchmark_symbol, thesis, selection_logic, rebalance_logic, track_condition_associations, target_symbols；
    - [x] `__post_init__` 强制门禁：thesis 为 None、空白或长度 < 30 字符立即抛出 `ThesisMissingError`；
    - [x] `run(matrix, ledger_path, config)`：纯函数式回放与账本落盘，校验候选池与基准角色隔离；
  - [x] `RunnerRegistry` 注册表：
    - [x] `register(runner)`：杜绝重复 ID，审核 pool_id 与 matrix.pool_id / candidate_symbols 一致性；
    - [x] `get(runner_id)` 与 `list_runners()`；
    - [x] `evaluate_all(matrix, ledgers_dir, config)`：遍历运行所有注册选手并返回回测结果字典。
- [x] **R3. 赛马记分与月度排名引擎 (`src/racetrack/scoring.py`)**:
  - [x] `PointsRuleV1`：标准积分映射表 {1: 10, 2: 6, 3: 4, 4: 2, 5: 1, >5: 0}；
  - [x] `calculate_monthly_returns(simulation)`：真实自然月复合净收益率；
  - [x] `calculate_rolling_window_return(simulation, months)`：1M, 3M, 6M, 1Y 复合滚动收益；
  - [x] `evaluate_race_season(...)`：多选手月度截面排名、积分累加、双基准超额矩阵、持续度比率与记分板生成；
  - [x] 在 `src/racetrack/__init__.py` 中导出新增模块函数。
- [x] **R4. 编写完整单元测试套件 (`tests/test_racetrack_runner_scoring.py`)**:
  - [x] TEST-RT-P2-01：空/过短 Thesis 触发 `ThesisMissingError` 门禁；
  - [x] TEST-RT-P2-02：`RunnerRegistry` 注册、发现与重复注册拦截；
  - [x] TEST-RT-P2-03：真实自然月切分与月度复合收益率数学等价性；
  - [x] TEST-RT-P2-04：月度截面降序排名；
  - [x] TEST-RT-P2-05：`PointsRuleV1` 积分分配与累加；
  - [x] TEST-RT-P2-06：防单日暴涨后视偏差实测断言；
  - [x] TEST-RT-P2-07：多周期滚动收益率计算；
  - [x] TEST-RT-P2-08：双基准超额矩阵核算；
  - [x] TEST-RT-P2-09：Scoreboard 前台 JSON 结构完整性与只读反序列化；
  - [x] TEST-RT-P2-10：真实美股 87 数据全量选手赛跑与记分板生成端到端演练。
- [x] **R5. 执行验证与代码质量门禁**:
  - [x] `uv run pytest tests/test_racetrack_runner_scoring.py -v` 全部通过；
  - [x] `uv run ruff check` 确保零告警；
  - [x] 更新 `tasks/todo.md` 记录 Review 总结，使用 `send_message` 向主 Agent 回复交付报告。

### Review & Completion Summary (Phase 2 Runner Registry & Race Scoring - 2026-10-28)
- **交付代码包**:
  - `src/racetrack/contracts.py`: 新增 `ThesisMissingError(ValueError)`，定义 `MonthlyRankPoint`、`ScoreboardEntry` 与 `Scoreboard` 核心不可变数据类，提供强类型字典转换与 JSON 往返序列化能力。
  - `src/racetrack/runner.py`: 建立 `RunnerContract` 基类与 `RunnerRegistry` 注册表。通过 `validate_runner_thesis` 实行前置投资假设强验证（< 30 字符严苛拦截）；纯函数式 `run()` 联动稀疏 JSONL 账本落盘，执行选股池白名单与基准参考标的严格物理隔离。
  - `src/racetrack/scoring.py`: 建立赛马竞技计分核心逻辑。实现版本化积分矩阵 `PointsRuleV1`（1st: 10, 2nd: 6, 3rd: 4, 4th: 2, 5th: 1）；计算自然月复合收益率 $R_m = \frac{\text{NAV}_{end}}{\text{NAV}_{start}} - 1.0$；实现 1M/3M/6M/1Y 滚动窗口收益率计算；通过 `evaluate_race_season` 输出全量前台只读记分板，包含截面排位、累加总分、持久度比率（Top 50% 占比）与双基准超额收益矩阵。
  - `src/racetrack/__init__.py`: 导出全部新增公共契约、异常与核心算法函数。
- **单元与集成测试**:
  - `tests/test_racetrack_runner_scoring.py`: 10 项严密测试全覆盖 TEST-RT-P2-01 ~ TEST-RT-P2-10，包含单日极端暴涨惩戒数学实测断言与真实美股 87 数据端到端竞技记分板演练。
  - 测试结果：`10 passed in 3.49s`；与 Phase 1 Minimal Stack 联合回归：`25 passed in 22.65s`。
  - 静态检查：`uv run ruff check` 全面通过，零错误零警告。

### Review & Completion Summary (Phase 3 Dual Benchmark & Self-Maintaining Publish Pipeline - 2026-10-28)
- **交付核心代码与治理模块**:
  - `src/racetrack/matrix.py`:
    - 增强宏观基准符号解析 `resolve_reference_symbol()`，支持 CSI 300（`000300` / `000300.SH`）与美股 `QQQ`；
    - 对齐官方交易日历（A 股严格遵循 `XSHG`，美股严格遵循 `XNYS`），全面校验非交易日与节假日；
    - 强制执行 `end_date <= as_of_cutoff` PIT 门禁并核验 evidence catalog 注册资质。
  - `src/racetrack/contracts.py`:
    - `PriceMatrix.get_price()` 增强对标的别名（`000300` / `000300.SH`）的双向消解透明访问。
  - `src/racetrack/engine.py`:
    - 增强对停牌/未上市股票的真实市场仿真，持仓标的在停牌期间每日收益严格为 0.0，复牌日无缝结算累计价格收益。
  - `src/racetrack/pipeline.py`:
    - 实现 `publish_racetrack_projection()`，整合价格矩阵加载、池指数推导、宏观基准构建、已准入选手批量执行与赛季记分；
    - 确立纵深隐私检查防线，递归式拦截 `shares`、`total_cost`、`broker`、`account_id`、`pnl` 等账户敏感字段；
    - 确立 `.staging_{uuid}/` 事务隔离区与 Fail-Closed 机制，生成带 SHA-256 签名的不可变 `manifest.json`、历史归档 `scoreboard_{session}.json` 与前台投影 `scoreboard_latest.json`，原子化提拔（Atomic Promotion）至正式发布目录；
    - 实现 `render_racetrack_scoreboard()`，提供终端友好渲染。
  - `src/cli/main.py`:
    - 扩展 `alpha racetrack publish`（`--market us|cn`, `--as-of`, `--output-dir`, `--start-date`）；
    - 扩展 `alpha racetrack show`（`--market us|cn`, `--input-dir`, `--format markdown|table|json`）。
  - `src/racetrack/__init__.py`:
    - 导出全部新增核心契约与流水线函数（`publish_racetrack_projection`, `PipelineResult`, `render_racetrack_scoreboard`, `resolve_reference_symbol`）。
- **单元与集成测试套件 (`tests/test_racetrack_pipeline.py`)**:
  - 覆盖 TEST-RT-P3-01 至 TEST-RT-P3-10 全量 10 项严密契约与负面测试；
  - 覆盖 CN 130 权重守恒（1/130）与上市前现金槽保护、月内零换手价格漂移、CSI 300 标的映射与 XSHG 日历对齐、双市场双基准超额矩阵、端到端发布与清单哈希校验、Fail-Closed 事务脏写防御、位级幂等性、隐私守卫零泄露、CLI 命令行交互与多格式渲染、跨市场物理隔离与摩擦单调性。
- **质量门禁验证**:
  - Phase 3 独立测试套件：`uv run pytest tests/test_racetrack_pipeline.py -v` -> 10 passed in 32.05s；
  - Phase 1–3 联合回归：`uv run pytest tests/test_racetrack_minimal_stack.py tests/test_racetrack_runner_scoring.py tests/test_racetrack_pipeline.py -v` -> 35 passed in 53.19s；
  - 静态检查：`uv run ruff check` 全部通过，零告警；`uv run ruff format` 格式化规范全部通过。
