# Investment Research Infrastructure — 下一阶段 TODO 与本地 Agent 实施路线

**历史快照（2026-10-26～27，PR #1296 时点）；不是当前待办。** 当前下一阶段的唯一执行计划是 [Next-stage execution plan](next_stage_execution_plan.md)（基线 `main@00dedccd`，2026-10-29）。下述已过时的“未实现”描述仅反映当时状态，不可据此重复创建 data slice、Study Workspace 或 Racetrack。

**唯一目的：** 将 Alpha Engine 从“四个既有策略的工程组合”，演进为**单一研究者能够复用可信数据、历史信息状态和实验收据的投资研究基础设施**。本文件保留 **#1296 时点的研究路线讨论和决策背景**；[产品定位](investment_research_infrastructure_charter_2026-10-26.md)定义目标，[历史基线](../architecture/investment_research_infrastructure_baseline_2026-10-26.md)保留 2026-10-26 当时的事实；`main/tasks/todo.md` 是现行 v1 运维任务入口，不在此复制其已结项清单。

> **PR #1296 仍为规划 PR：本文列的是后续独立任务的 Definition of Done，不等同于实现完成、Owner 批准上线或 v1 Release PASS。** 不修改正式模型、仓位、策略注册表、密封历史、用户权限或生产数据；`research_only=true` / `trade_ready=false`。

## 最新代码进度同步（2026-10-27）

- **已提交到 `main@2544a564348c192dce8c2939a4007510a0a557a0`：A-P0-01 的 Ruff F841 局部修复**。原 `tests/test_refresh_selected_pool_prices.py:562` 变量 `original_bytes` 已进入真实源文件字节不变断言。**下一个验收**：Ruff/相关测试及该 SHA 后的真实 `formal-backtest-refresh` prepare/provider/strategy/fan-in 回执；未有生产回执前 **A1/A6 仍 BLOCKED**。
- **同提交完成 A-P0-02 的代码与负面测试**：`scripts/refresh_byd_v1_3_formal.py` 删除按 `"do not reach target cutoff"` 字符串降级，`BYDProspectiveDataMissingError` 仍 exit 10，其他 `BYDFormalRefreshError` 仍 exit 1；`tests/test_refresh_byd_v1_3_formal.py` 增加通用异常携带相同字样仍致命的用例。**下一步不重复改代码**；仅根据 CI/真实运行失败证据修正。
- **未关闭事项：** #1288 公开 Git/Actions/写入边界仍为 P0，A4 **FAIL**；RI-01R/RI-02R 待核实，RI-03A/B 仍未实现。上面两个小修复的 main 提交 **不等于 v1 RC GO**。

## 1. 已证实的起点（不可把“文档存在”写成“平台完成”）

| 领域 | 截至基准提交的事实 | 后续要求 |
| --- | --- | --- |
| v1 产品范围 | 2026-10-26 已合并 #1276；本地 `alpha data` / `alpha research` + 只读四策略 Strategy Console | 现行产品照常维护，不恢复旧 Research IDE |
| #1288 / 安全 A4 | Issue **Open**；Pages `public_historical_projection_v1` 有脱敏实现，公开 Git 中仍追踪当前目标账本/原始 lineage，Actions artifacts 和新写入链路仍需治理；A4 **FAIL** | 首先停止新增泄漏，再修完整边界；不可因为 Pages 测试通过宣布安全合格 |
| 正式运行 A1/A6 | 最近的 Run [40359577256](https://github.com/liuh886/alpha_engine/actions/runs/40359577256) 在 prepare 阶段被 Ruff `F841` 拦下：`tests/test_refresh_selected_pool_prices.py:562` 的 `original_bytes` 未使用；尚无此次改动的端到端刷新证明 | 定点修 lint 并取合并后真实运行回执；连续 20 eligible sessions 仍待独立验收 |
| BYD/跨源行情 | 异常分类已引入 `BYDProspectiveDataMissingError`，但仍有基于字符串 `do not reach target cutoff` 的降级分支；跨源 volume 保留历史 overlap、仅追加 extension，已有基础回归 | 去掉字符串降级；完善真实数据单位证据和边界测试，不能泛化为所有数据质量合格 |
| RI-01 / B0 | [实证清单初稿（main）](https://github.com/liuh886/alpha_engine/blob/main/docs/architecture/investment_research_data_product_inventory_2026-10-26.md) 已覆盖 US87/CN130、公司行为、基本面、Alpha158、RDI；**5 ready / 3 partial 组件、2 blocked profiles** 是特定数据产品/训练配置状态 | 校验证据来源、源权限、first-known 与消费路径，不能把 100% 横截面覆盖写成历史 PIT 合格 |
| RI-02 / B1 | [ADR-0005 Draft（main）](https://github.com/liuh886/alpha_engine/blob/main/docs/architecture/adr-0005-point-in-time-information-state-semantics.md) 已定义五个信息时间及证据等级；它从属于 ADR-0003 | 逐现有契约映射，澄清“迟一个交易日”**不能代替**真实历史可得证据，转成可运行负面测试 |
| RI-03/04/05 | 尚无经批准的统一 data slice、双研究消费者复用证明或使用成本基线 | 按下列窄任务执行；未验证不得标 DONE |

**现存权威优先级：** `AGENTS.md`、`configs/strategies/registry.json`、`docs/architecture/repository_data_convergence.md`、`configs/data_contracts/model_data_bundle_v1.yaml`、`fundamental_event_store_v1` / `corporate_action_store_v1`、现有研究 runner/receipts。B0/B1 文档是待审查的映射，不新设第二套事实权威。

## 2. 执行队列（允许 Track A 与 B0/B1 并行）

### A — 保持现有工作站可运行、可信（由原 Issue 管理，不由 #1296 实施）

- [ ] **A-P0-01 / 恢复真实正式刷新预检** — **立即**。仅移除或实际使用 `tests/test_refresh_selected_pool_prices.py:562` 的 `original_bytes` 变量；Ruff、受影响 Python tests、`git diff --check` 通过后，在合并 SHA 上运行既有 formal refresh。**验收：** 提供实际 GitHub Actions URL、preflight 通过、provider/strategy/fan-in 的明确 PASS/BLOCKED 记录；不得用本地 pytest 替代真实运行。**相关：** [#1256](https://github.com/liuh886/alpha_engine/issues/1256)、Run 40359577256。
- [ ] **A-P0-02 / BYD fail-closed 边界**。仅捕获 `BYDProspectiveDataMissingError` 为 `data_blocked` (exit 10)，删除 `except BYDFormalRefreshError` 内依据异常文案的降级兼容分支。历史前缀、篡改、manifest/hash、重复日期、契约损坏必须 exit 1。**验收：** 真缺观测退出 10；构造含相同文字但不同异常类型的完整性错误仍退出 1；集成运行证据保留。
- [ ] **A-P0-03 / #1288 公开源止血与受保护存储**。先追踪所有 `git add/commit` 当期策略数据、formal lineage、Pages 输入、Actions artifacts/日志/公开链接；停止新增敏感目标、权重、drivers 进入 **public Git**。复用现有 Strategy Decision Ledger、private archive、Strategy Operations 和 RLS；迁移的是**存放/发布边界**，不是重新设计第二套 ledger/数据库。**验收：** 公共 Git 当前树、Pages 静态文件、Artifacts、写入流水线四类独立匿名负面证明，实际 entitled/expired/revoked 验证，保留 canonical source hash 与独立 public projection 身份，记录公开 Git 历史无法自动撤回的残余风险。**A4 继续 FAIL 直到全部通过。** [#1288](https://github.com/liuh886/alpha_engine/issues/1288)。
- [ ] **A-P1-04 / 真实运行及发布门禁**。依据现有 #1277 收据累计 US/CN 各 20 eligible 交易时段并独立复核；不因 BYD shadow 提前 cron 就认定时序有保证。按实际 main SHA 重新完成 A2（必需输入/PIT）、A3（changed/unchanged/not-due/blocked/denied 及移动端）、A5（限定范围 replay）、A6（合格发布与 privacy-safe rollback），最后 Owner 决定 A7。**验收：** 可复核的 A0–A7 表及各 gate 准确日期/运行 ID；仍为 NO-GO 时如实保留。

**并行规则：** A-P0-03 不阻塞 **只读 B0/B1**；凡会将 raw/current 数据拷入公开 PR、公开示例或产物的 B2/B3 改动，必须先审查 #1288 隔离边界。

### B — 研究基础设施最小可用闭环（#1296 的新工作）

- [ ] **RI-01R / B0 数据资产清单验收（先补证据，不重建仓库）**
  - 以 `data/research/model_data_bundle_v1/data-components.json` + 各原始 manifest 为权威，逐组件注明 **target/actual、first/last date、cutoff、source hash、missing/inapplicable 与 status**；5/3/2 状态不要合并成一个“覆盖率”。
  - 补两个实际消费者的 reader/CLI 调用链（①CN 横截面研究；②RDI 7/14/28 readiness），注明数据来源、加工环节、PIT/授权约束和错误时的现行行为。
  - 逐数据家族标明 `first_public_at`、`first_machine_known_at` 的 **已证明/未知** 状态；版权/再分发限制要有许可依据，不能因为接口公开就认定可以分发。
  - **交付：** 更新现有 RI-01 清单及一个脱敏的实际查询/不可用例子（不用新数据库）。**DoD：** 每行路径和 SHA 可打开、数值可由 manifest 复算；实际缺失与研究用途阻塞不会被展示为 Ready。
  - **责任边界：** 复用 #324/#325 现有源完整性任务、#1272 RDI 不足证据；不另立采集队列。

- [ ] **RI-02R / B1 PIT 语义收口（ADR-0005 继续 Draft 直到审核）**
  - 对齐实际 `reported_at` / `available_at` / `retrieved_at` / `revision_sequence`、公司行为 announce/ex/effective 与已封存的 raw/adjusted/anchor；清楚区分**公开可知**与**机器曾经实际可得**。
  - **关键修正：** Grade 3 历史后取数据即使延后一个交易日，也不能由此推导“当时一定可获得”；只有可核对的历史公告/vintage/archive 才可作为严格 as-of 依据。其余标 `unknown`/`blocked` 或“仅可做带假设的非认证研究”，不可冒充严格 PIT。
  - 在 ADR 中附可执行的时间线/现有 reader 映射和六类失败：未来财报、事后更正、供应商滞后、上市前/退市后、调整基准混淆、无证据的 RDI 历史事件。
  - **交付：** 修订现有 ADR-0005 与负面测试设计。**DoD：** 同一事实在 T0/T1 下的可用/不可用与修订选择可以被独立复核；不强行制定超出现有家族能力的统一数据表。

- [ ] **RI-03A / B2 先找现成接口，决定最小数据切片**
  - 审查现有 `alpha data list/status/prepare`、`scripts/data/check_model_data_profile.py`、Model Data Bundle readers、Qlib Dataset、PIT event store 和 manifest。列出已有功能与**唯一真实缺口**；如果已经足够，**只补入口文档与契约测试**。
  - 选一个可证明历史可得的 **CN 小样本（行情 + 一种已有公司事件）**，冻结 `market`、`pool_id`、决策 `as_of`、查询区间、`price_mode`、需要的字段、原始 manifest hashes 和实际可见日期；若不可证明则冻结一个诚实的 `BLOCKED` 样本，不伪造能用的数据。
  - **交付：** 一份最小查询协议和可跑通现有入口的实现计划，注明是否需要新增一条参数化本地 reader；不做浏览器 Research Studio、第二个 catalog、scheduler 或新 provider。
  - **DoD：** 一个明确的 happy/blocked 场景和最小变更 Diff；source bytes、冻结正式研究证据不变。**依赖：** RI-01R、RI-02R 的关键规则可审核；会公开的样本先过 A-P0-03 审计。

- [ ] **RI-03B / B2 实现第一条可复用 research data slice（批准 RI-03A 后再开实现 PR）**
  - 在现有 reader/CLI 层复用唯一权威，输入为声明的 sample/cutoff/fields，返回 **dataset ref 或文件切片、readiness/coverage、明确 BLOCKED 原因、source/version/transform hashes、rights 标记**。原始大数据不重复拷贝；receipt 是原始文件引用 + 精确条件，不是第二个数据源。
  - **负面测试必备：** 事后修订、历史不可证 first-known、错误股票池/新上市标的、US/CN 混用、raw/adjusted 不一致、hash 漂移、私有当前仓位泄漏、缺失财报错误填 0。各自阻塞且不污染有效数据。
  - **DoD：** 在固定输入 SHA 下相同请求重复两次，数据、receipt 和 blocked reason 确定性相等；可由单一 `uv run --frozen ...` 或现有 `alpha` 命令验证，不要求第三个命令入口、第二张表或新永久 workflow。

- [ ] **RI-04 / B3 复用效果实验（RI-03B 后）**
  - 消费者一：既有 **CN 横截面研究**，用现有 Qlib/训练或回测执行器；不调整当前四策略模型，不以盈利为验收。
  - 消费者二：**RDI 的历史事件 readiness**，检查 #1272 的 source/calendar/7、14、28 horizon；证据缺少则产出 `blocked`，不能编造 2026 年 7–10 月历史事件回测。
  - **DoD：** 两个不同研究问题共享同一 Data Slice/Receipt/PIT 门禁和身份语义，保留各自模型逻辑；至少一个成功读取实例、一个可解释的阻塞实例，证据 SHA 可重放；不得将 RDI 升级为正式信号。

- [ ] **RI-05 / B4-B5 研究者效率度量与减负（RI-04 后）**
  - 固定一个新投资研究问题，记录**人工步骤数、为数据写的临时脚本数、重复下载/副本、从提出假设到得到可解释结果的时间、可重复率、失败可解释性**。
  - 仅改进测量后最痛的一个现有 `alpha data`/`alpha research` 接口；删除被新闭环取代的冗余路径，不保留“兼容旧逻辑”。
  - **DoD：** before/after 对比与相同冻结样本/模型/基准、负面测试、没有新增永久工作流或未经必要性论证的 UI。

## 3. 建议提交与审阅顺序（不要把本 Draft 当成全部实施授权）

| 执行组 | 允许开始 | 交付位置 | 验收者 / 下一关 |
| --- | --- | --- | --- |
| A-P0-01/02 | 立即，既有安全边界内 | 独立最小 bugfix PR，关联 #1256 | Ruff + 单测 + 合并后真实 refresh receipt |
| A-P0-03 | 立即，与 B0/B1 并行 | #1288 独立安全实现 PR | Owner 授权边界 + 4 面负面证据 + A4 审查 |
| RI-01R / RI-02R | **立即可读审，尚未架构批准** | 更新 main 上既有 RI-01/ADR-0005 文件的独立 docs PR | Source/PIT 逐项映射通过后，Owner 决定 B2 |
| RI-03A | RI-01R/RI-02R 关键缺口清晰后 | 一个小型 design/test PR（如无接口缺口仅 tests/docs） | Owner 确认样本、source rights、唯一实现路径 |
| RI-03B → RI-04 → RI-05 | 上一阶段真实 DoD 通过后逐项实施 | 每项独立小 PR；复用 #826/#1272 | 可重放的 data/evaluation receipts、复用增益与负面证明 |

**停止条件：** 发现第二个权威、把未认证历史称为 PIT-ready、使用 future/restated value、重写 sealed hashes、将 current allocations 写入 public source、隐瞒失败测试、以新模型代替缺失数据时，立即阻塞对应工作包；不允许隐式 fallback。

**成功度量不是 PR 数量：** B2 至少一个以真实冻结证据支撑的 `as-of` 研究数据查询，B3 两个不同消费者复用同一准备与 receipt 机制；B4 才能比较实际减少的重复步骤/字节。v1 A0–A7 与 Track B 验收完全独立。

## 4. 本 PR 要讨论和确认的产品决策

- [ ] **D1 定位：** 长期围绕 **Investment Research Infrastructure**，现行 Direction A v1 单研究员/四策略 Console 不变。**建议：同意**。
- [ ] **D2 第一位的产品能力：** 先做好已有数据的“可发现、可核实、能按历史时点读取”，而不是新 UI/新数据仓库。**建议：同意**。
- [ ] **D3 新数据来源准入：** 先量化现有缺口与许可，再决定是否采集更多事件、宏观/另类数据。**建议：同意**。
- [ ] **D4 首批消费者：** CN 横截面研究与 RDI **readiness**，后者允许 BLOCKED；不将其当作已验证的预测模型。**建议：同意**。
- [ ] **D5 执行方式：** RI-01/02 的**文档初稿已在 main**，不重复创建同名空工作包。先验收 RI-01R/02R，再批准一个最小 RI-03A/B 垂直切片；Track A 独立维持安全和正式运行。**建议：同意**。

本 Draft 可独立合并规划但不等于 D1–D5 已获 Owner 签署；后续以独立 implementation PR 和严格 evidence gate 为准。
