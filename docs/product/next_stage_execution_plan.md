# Alpha Engine — 下一阶段产品架构与执行计划

**当前裁决：产品 NO-GO；RDI 价格层已交付，完整 RDI 未验证。** 最新核对基线为 `main@65622788d9`，2026-11-01；2026-10-29 的原路线基线保留为历史。本文是**当前下一阶段执行顺序的唯一入口**；旧的 [2026-10-26 路线图](investment_research_infrastructure_roadmap_2026-10-26.md)仅作历史决策记录，[研究问题库](future_research_agenda_2026-10-28.md)仅作备选议题，[#1315](https://github.com/liuh886/alpha_engine/pull/1315)是 UI 具体缺陷清单，[#1307](https://github.com/liuh886/alpha_engine/pull/1307)是独立 BDCR 研究 RFC。下列每项只有通过**独立实现 PR + 证据验收**才算完成；路线合并不批准产品 GO。

## 2026-11-04 Owner 决策：P2 本地条件化策略验证（架构已定义，代码待实现）

Owner 已批准 P2 / **Conditional Strategy Validation** 作为投资研究能力的后续扩展，但明确限制为 **日线或更慢周期**、**本地 Agent/CLI 开发和执行新策略**；网页仍是 Today / Strategies / Research Lab / System 的**只读展示与证据审阅**，不得成为浏览器研究 IDE、策略提交或回测运行入口。不得因引用日线动量研究而引入分钟级行情、日内交易模拟或 Ross Cameron 分钟级策略复刻。

唯一范围与本地 Agent 交付合同见 [P2 local-only daily conditional validation architecture](conditional_strategy_validation_p2_2026-11-04.md)（附非可执行示例 `examples/conditional_daily_momentum_p2_design.json`）。本阶段优先 **P2-1 真实 US87 日线条件研究垂直切片**、随后 P2-2 统计与样本外评估；研究结果浏览器展示属于后续可选工作包，不作为首个垂直切片验收条件。继续复用现有 selected-pool、Study Workspace、experiment harness、data slice、Racetrack 和 Study Review 权威，无第二套数据/引擎、调度器或策略注册表。

**状态：此架构 PR 仅做设计与路线图链接；实现、数据资格、真实回测与科学结论均未验收。** P2 不替代本文件 A0–A7 产品收口队列，不自动释放 RDI、正式策略晋级或任何 `trade_ready` 能力。

## 2026-11-02 前端架构方向与独立交付

Owner 选择 **A / Decision-first** 作为 Alpha Engine 默认设计。
[PR #1357](https://github.com/liuh886/alpha_engine/pull/1357) 已提出
Today / Strategies / Research Lab / System 的代码骨架，以及
[架构实现与本地 Agent 接手清单](frontend_reference_first_architecture_handoff_2026-11-02.md)。
该 PR 仍处于设计与实现验收阶段，**不批准主干部署，不替代 A0–A7，
不开放研究私有数据，更不批准交易执行**。
原有产品上线程序继续推进，与这次 UI 框架改造并行。

## 0. 产品与功能上线路线图（2026-10-31 当前执行入口）

### 0.1 三个交付层级，分别验收

| 层级 | 上线含义 | 当前裁决 / 退出标准 |
| --- | --- | --- |
| 可部署工程版本 | 已有四策略只读 Console 的具体 SHA 可以构建、部署和读取 | 已有局部发布证据；不等于完整产品验收 |
| 正式产品发布 | 单操作者能持续读懂策略、核实证据、恢复故障并安全读取当前状态 | **NO-GO**；下表 A0–A6 证据闭环后，由 Owner 在 A7 明确 GO |
| RDI 功能 | 先交付带日期的研究证据视图，再考虑经过验证的研究评估 | 价格层与证据视图均已交付（#1338/#1340）；正式评估须事件资格、冻结评估及真实前瞻门禁通过；无未校准分数 |

RDI 未验证不阻断四策略产品独立验收；产品部署成功也不证明 RDI 有效。
产品发布范围仍是 Overview、策略/标的解释与 Operating Status，以及既有本地 CLI。
本地 Racetrack、未来 Runner 和 BDCR 各用自己的冻结合同，不变成第五个正式策略或新主导航。

### 0.2 产品发布门禁与待完成事项

状态表示现有证据，不用旧统计推断今天已积累多少合格交易日。
详细门禁由 [产品验收 scorecard](product_completion_scorecard_2026-10-25.md) 和既有 Issue 定义。

| Gate / 原任务 | 当前证据 | 下一可验收交付 | 执行者 / 外部依赖 |
| --- | --- | --- | --- |
| A0 身份与权威，#1278 | **PASS**；权威入口与四策略身份对齐已闭环 | 保持四策略、正式/研究边界及同一当前路线入口；以当前 SHA 复核，不恢复退役路径 | Agent |
| A1 持续运行，#1277 | **BLOCKED**；最新成功运行不是 20 日验收 | 复用现有 operating acceptance，逐 US/CN 市场重审实际 20 个合格交易日、所有失败/保留/not-due 分类与真实 due-cycle；缺收据明确列缺口 | Agent 审核已有收据；缺失的真实未来交易日必须等待，禁止补造 |
| A2 数据完整性 | **BLOCKED / Ops PASS**；四策略运行依赖已对账闭环（#1352） | 独立研究训练集维持 SCOPED_BLOCKED，无违规外溢；已完成 Alpaca/SEC EDGAR 预检与 56 项测试全绿 | Agent；必要原始来源或权限需 Owner/提供方 |
| A3 用户旅程，#1279 / #1315 | **BLOCKED / Baseline PASS**；四策略 8 条基础交互与 375px 移动端通过（#1350） | 302 项单元测试 + 117 项 Playwright 静态端到端全绿；受限会话因无专用测试账号保持 NOT_TESTED | Agent 负责可复现代码/公开旅程；真实受限会话需 Owner |
| A4 权限与披露，#1279 / #1288 | **FAIL**；活动公开账本、新原始传输路径已止血（#1353） | 82 项安全与私有账本测试全绿；因无专用测试账号真实会话保持 NOT_TESTED，历史披露列为残留风险，维持严格 FAIL | Agent 做只读审计与修复 PR；Owner 决定披露处置、提供专用会话并批准实际权限/数据治理 |
| A5 本地研究，#1282 | **PASS (bounded) / PENDING_OWNER**；有界 CN/QQQ 回放证据固化（#1351） | CN27 重放误差 $\le 10^{-6}$，QQQ 如实记录数据源阻断，Windows junction 修复通过 33 项单测 | Agent 复核；Owner 最终确认 |
| A6 发布与恢复，#1281 | **BLOCKED / Rehearsal PASS**；发布守卫与 CAS 恢复演练通过（#1354） | 静态控制台回退与私有账本 CAS 恢复双向演练验证，46 项发布门禁测试全绿，待 Owner 生产操作 | Agent 先完成可审阅演练包；涉及实际生产回滚及 Owner 本机操作需 Owner 明确执行/批准 |
| A7 发布决定 | **NOT_TESTED / NO-GO** | 汇总 A0–A6 的 PASS/BLOCKED/NOT_TESTED、剩余风险和回滚证据，Owner 给出带日期的 GO/NO-GO | Owner；不能由 Agent 或绿色 CI 自动代签 |

已确认无专用测试账号/会话。全体策略当前 live tier 为 public 的观察不能替代受保护行拒绝测试；
Agent 不自行修改线上 tier、entitlement 或删除生产行以制造通过样本。

### 0.3 RDI 功能里程碑

| 里程碑 | 当前状态 | 下一事项与通过标准 |
| --- | --- | --- |
| M1 价格层 | **已交付 #1338**：5,238 个完整 XSHG session 至 2026-10-30，版本化修复、原始响应归档、离线重放及未成熟尾部 | 既有手工节奏下按需更新来源/冻结版本并校验 overlap；不让 Status 读取触发取数、重放或重算 |
| 证据视图 | **已交付 #1340**：Status 价格截止 2026-10-30，审核日 2026-10-31，桌面/手机精确 SHA 线上验收通过 | 维持已审来源绑定与 missing/tamper 失败关闭；不触发取数/重算。仍 `not_validated`、0/10 事件家族、无 score；[线上收据](../evidence/product_v1/rdi_status_live_acceptance_1340.json) |
| M2 事件资格 | 十类资格表已发布，**0/10 合格** | 审计逐 session 完整性、真实 available-at、修订与 absence 证据；未知保持 unknown |
| M3 首个事件家族 | **待选择与冻结**；推荐限售解禁公告，备选业绩披露窗口 | Owner 选择家族后，Agent 冻结窄 universe/era/来源/时点/去重/覆盖合同并实现；单类合格不自动解锁完整十类 study |
| M4 冻结评估与前瞻起点 | **NOT_STARTED** | 预先提交 B/E/E+B、基准、阈值、purge/fold/区间与成败标准；冻结后才记录未来 session，不追认已观察的 7–10 月为前瞻 |
| M5 验证与研究评估上线 | **BLOCKED** | 在真实合格数据上检验增量效用、区间与校准，保留负结果；分别等待 7/14/28-session 标签及足够独立事件。通过既定前瞻门禁后再单独审查研究评估展示 |

不承诺“28 天后上线”：28 是交易日标签长度，不能替代足够样本、独立事件和评估通过。
无校准证据不发布 0–100 分数或概率；无 EvidenceBundle 门禁和 Owner 批准不加策略覆盖层。

### 0.4 实施队列与收口方式

当前任务收敛以 [§11 的单一执行队列](#11-2026-11-01-远端任务收敛)为准。
已完成的功能不再作为待开发项；有真实观察期、账号或 Owner 决定依赖的门禁
不挤入即时开发队列。每项沿用既有 Issue 和小 PR，记录精确 SHA、截止日、
PASS/BLOCKED/NOT_TESTED 与下一动作。不新增任务板、工作流或研究范围。

## 1. 产品判定：从建设功能切换到交付有用的研究判断

**唯一定位：一人使用的专业投资研究工作台（Investment Research Infrastructure）。** 工作台完成三件事：① 用历史时点可核实的数据**验证/证伪投资假设**；② 在相同样本、交易日、费用和基准下比较研究策略；③ 把变化、支持证据、反证、下一次复核步骤呈现给投资者。最终买卖与仓位决策由人完成。

用户完整旅程：**Today / Brief → 为什么关注（Evidence）→ 候选策略的相对表现（Racetrack）→ 人工判断 → 下一观察日复盘**。不是「新增模型 → 新页面 → 新数据库」，也不是自动生成买卖指令。**无新信号、证据不足、过期或受阻**都必须有诚实且有用的空状态。

最重要的产品问题：`/app` 中的「正式四策略观察」（可信运营事实）与「本地 Racetrack」（未经正式采信的研究比较）怎样相互辅助而**不混同其行动资格**。Brief 的前三条是**运营关注优先级**；Racetrack Top 10 是**指定市场/窗口内的研究收益排名**，两者不应该叫同一种“推荐榜”。

### 1.1 基于当前代码的交付状态（不等于完整产品已通过）

| 领域 | 已证实的实现 | 不得扩大解读 |
| --- | --- | --- |
| Formal Console | 四个正式策略的 Overview、Detail、Instrument、Status；#1317/#1318/#1320 纠正日期/权限过渡/历史窗口误导 | 局部 UI/CI 通过 ≠ A0–A7 产品上线验收 |
| 本地 CLI 研究 | 既有研究收据与比较合同；RDI #1338 价格层可重放 | 不恢复退役浏览器研究入口；历史 PIT 和 RDI predictive edge 未获认证 |
| Racetrack | #1306 P/Q/NAV、双基准、积分、发布；#1311 Lightweight Charts 主图/榜单/详情；#1314 US87 等权池实际 Runner、私有 Q、v2 时间窗口排名 | US87 Runner 与内部等权基准共用一个回放，不能充当**独立策略有效性**证据；没有六名合格选手 |
| 前端决策解释 | `DailyResearchBrief` 展示三条优先观察；`StrategyDetailPage` 展示已验证支持证据/全部门禁/反证/局限/下一步 | [#1305 的实际实现 TODO](decision_feed_evidence_review_todo.md)中两项 P0 已实现，完整四策略仍在 Fleet；最终部署证据、P1 身份关联和整体旅程仍单独验收 |
| 发布与数据权限 | #1326–#1331 私有接线、活动公开写入止血与 Formal 结果私有传输已建立，真实 run 41083709573 通过 #1332 与精确 Pages 校验；本地 Racetrack 不公开 | **A4 仍 FAIL**；旧密封/历史披露、退役运行行及真实权限负验证仍未关闭 |

### 1.2 原 P0 基线及后续处置（2026-10-29 历史观察；不摘录任何权重）

以下原始观察不能当作当前树状态。#1328 已撤下活动账本子树及 producer 公开镜像，
#1329/#1331 关闭新 Formal 原始结果跨 job 公开传输；#1336 记录当前 Git 16 次匿名 404、
静态空壳和新制品/日志限域负验证。#1333 已关闭 US 源窗口/起始 NAV 的该项缺陷，
不等于关闭 #1315 全部事项。当前剩余项与交付证据以 §0 为准。

- **公开数据平面**：`data/research/strategy_signal_ledgers/{qqqi_qqq_tqqq_v4_3,us_x1_3,cn_27_v1_3,byd_v1_3_recovery_event_low_vol_confirmation_v1}/latest.json` 在公开 Git 路径中存在，包含 `current_weights` / `target_weights`。
- **自动写入面**：`.github/workflows/{cn27-current-target,ranker-10d-current-target,qqq-v4-3-signal-alert,byd-daily-signal-alert}.yml` 仍执行 `git add` 该类账本并推至公共 `main`；`formal-backtest-refresh.yml` 也仍需独立审查公开投影、制品与出版边界。
- **既有审计**：[`current_operations_security_audit_1288.md`](../architecture/current_operations_security_audit_1288.md) 仍将 Git/Actions/写入列为泄漏，[`product_completion_scorecard_2026-10-25.md`](product_completion_scorecard_2026-10-25.md) 仍将 A4=FAIL、A7=NO-GO。Issue 关闭不能取代负面证据。
- **已知产品口径缺口**：[#1315](https://github.com/liuh886/alpha_engine/pull/1315) 中 US x1.3 图/汇总开仓净值与 68/69 observations 的源投影问题尚未关闭；剩余日期用语、驱动因素语义及 Status 信息密度仍待分 PR 修复。

## 2. 架构守则：一个事实权威，两个消费视图

```text
已有数据/事件权威（原始证据 + as-of/vintage + source identity）
              │
              ├── Formal accepted run / immutable Bundle v2
              │     └── Decision Ledger → protected Strategy Operations reader
              │                                └── Formal Brief / Strategy Detail
              │
              └── governed Research Data Slice
                    └── Study Workspace / existing evaluator → immutable study receipt
                          └── admitted Racetrack Runner → Q + NAV + ranked projection
                                                     └── local read-only Racetrack
```

1. **计算/权限分离**：Python 负责研究、净值、费用、积分、资格与版本；浏览器只读取同版本、hash-bound 的投影。显示窗口切片/归一化允许，**在浏览器重算策略排名、交易信号或现时持仓不允许**。
2. **正式策略和研究选手分离**：正式策略身份来自 `configs/strategies/registry.json` / Formal Bundle；研究 Runner 有独立 `runner_id/version`，不因名称相似即继承正式策略采信地位；未经严格适配不能裁剪 ETF/杠杆/池外标的来伪造“正式策略复现”。
3. **受保护的当前状态不可进 public Git**：保留现有 Decision Ledger **格式和唯一事实语义**，修正落盘、传递及公开发布边界；复用既有私有 archive / 服务端 RLS/entitlement 的**真实可写路径**。在验证受保护写入和投递接续前，不贸然删除工作流或禁用全部正式信号。无并行数据库/新表/兼容镜像。
4. **研究来源的 PIT 有等级，不虚构认证**：历史事后获得的 adjusted price/event ≠ 当时可知；无权威 event-vintage/payload 时标记 `pit_certified=false` 或 BLOCKED。研究失败、数据缺失和淘汰假设都保留证据。
5. **Local-first，不新增主导航**：`/app` 默认四策略，Racetrack 是现有模式切换；研究的 CLI 和本地投影维持原边界，未审查的敏感投影不得复制到 Pages。前端沿用 React/Vite/router 和已安装的 Lightweight Charts，不造第二套图表引擎。

## 3. 按依赖排序的行动清单（每行可单独成为小 PR）

| 顺序 | 工作包与明确范围 | 完成标准（DoD） | 依赖/禁区 |
| --- | --- | --- | --- |
| **P0 / G0** | **当前操作状态的公开写入止血与重接线**：追踪 Git 最新树/历史、四个每日 writer、Formal lineage、Actions artifacts 和 Pages；先建立**受权限保护**的既有 Ledger 写入与 Strategy Operations 发布/读取端到端路径，再撤下公开 Git 新写入；清理当前树的敏感操作字段，封存已公开历史为残余风险记录 | 四面独立匿名负面验证（公开 Git 当前树、Pages、Actions artifacts、新写入流水线）+ entitled/denied/revoked 读测试；US/CN 正式信号仍按原调度生成、发布、投递，失败 fail closed；`A4` 依据新证据裁定，不按关闭 issue 推定 PASS | **必须先于受保护当前数据的公开面扩张和正式产品发布**；既有 Status 内非敏感、未验证的描述性 RDI 证据重绑可独立小 PR 验收，不解除 A4；不重写密封历史、不创建第二真相库 |
| **P1 / U1** | **修正剩余解释语义**：US x1.3 opening wealth/source-window 已由 #1333 版本化投影完成；继续 #1315 的 date vocabulary 和 driver 语义，Status 去除重复和错误提示 | 真实来源数据下汇总、图表的起止日期/净值/收益/样本数可逐行核对；不存在把“待加载”说成“无权限”；桌面/平板/手机 + 完整测试回归 | 在 #1315 已完成 #1317/#1318/#1320/#1333 基础上继续；不能在前端硬塞 NAV=1、改写 sealed metric |
| **P1 / U2** | **完成 #1305 的 Decision Feed**：直接调整 `DailyResearchBrief.tsx`；首页只突出最多三项有意义的变化、风险、阻断，按时间和优先级说明 *why now*，保留原四策略完整 Fleet；无新变化给明确“无新动作” | 变化/无变化/过期/阻断/权限待定的读法清楚；每条带 cutoff、原因、下一动作，`/app → evidence` ≤2 点击；不增加新导航或信号计算 | 继续复用现有 `describeStrategyObservation` 和共享读器，不把研究收益榜和运营关注榜合并 |
| **P1 / U3** | **完成 Evidence Review**：`StrategyDetailPage.tsx` 用已有 `loadDecisionForRun` 分开列出支持证据、反证、解释局限、下一次允许验证；精确表明无绑定/过期/拒绝读取/等待审批 | 抽样一个支持、一个失败门禁、一个无有效证据情形；显示的结论、身份和日期与原 Bundle/Decision receipt 一致；不变成“买入/卖出建议” | 未有可审计映射时**不**自动接入研究 Runner，也不暴露本地未审查收据 |
| **P1 / R1** | **真实独立研究选手**：在同一 US87 轨道内选择**一个**不等于 US87 EW 的简单、事前冻结的基线策略（先查现有 Study Workspace/现成 Runner 能否复用），按现有 Q/NAV 引擎、公平窗口与成本实测；保留输给基准的情形 | 冻结 thesis/spec/候选池/再平衡规则/费用/训练与 OOS 边界；产生可重跑 Q + source/code SHA + 相同 sessions 的 NAV 与 QQQ、US87 对照；回放、局限和失败案例同版本可读；没有收益保证或自动升为正式策略 | US87 Phase A #1314 已完成。**不能**用原样不合规的 QQQR/US x1.3、随机伪信号或“回测胜者筛选”来凑选手 |
| **P2 / R2** | **CN 轨道的真实基线**：复用现有 CN/XSHG/CSI300 的 registry/scorer，接入 CN130 EW 池指数及 Q ledger，隔离标的、成本、停牌/上市前现金槽；再独立评审 BYD/CN27 改造的必要性 | CN130 与其内部基准完全对账；任意 US/CN 混跑 fail closed；CN 轨道至少可独立发布/阅读基准及其数据局限。正式派生 Runner 仅在版本化合同与 PIT/ETF/杠杆准入通过后登记 | 不是重新写 CN scorer；不能剪掉 515180 或超出股票池的持仓后沿用正式模型名 |
| **P2 / E1** | **建立最小研究成果复盘**：复用 Study 收据与赛季表现、固定的前瞻 shadow 观察窗口；按首次提出日期、证据 cutoff、复核日期记录当时的预测/否证条件和之后的观察结果 | 一份真实、可重放且不含私有账户信息的假设：从提出→冻结→OOS→前瞻观察→结论/否定；同时显示失败情况、多次尝试与窗口资格；不新建交易日记 DB | 先有 R1 和可靠证据；不能用一次回测替代 forward-walking 验收，也不能事后改阈值 |
| **后置 / R3** | **Bottom Detection (#1307)**：先解决 BDCR A–D owner 选择、corporate action/fundamental payload 与 as-of 证据，再通过现有执行器做一条研究-only state-machine；OOS、shadow 通过后才考虑是否成为 Runner | 时间因果、缺口/退市/停牌/冲突规则有负面测试；严格保留 `experiment_ready=false` 直到源与规则齐备 | **禁止**单因 RSI/形态感兴趣而提前上真实买点提醒 |
| **并行验收 / O1** | **Direction A A0–A7 产品/运营审查**：按实际可得的 US/CN eligible sessions、源数据完整性、权限、恢复/回滚、用户旅程累积证据 | 每个 gate 的 PASS/FAIL/BLOCKED/NOT_TESTED、日期、commit、Actions URL 与 Owner 裁定；真正 20-session 观察不足时继续 BLOCKED | 与研发持续并行；绿 CI、一次 Pages deploy 和新模型数量不等于 GO |

### 3.1 建议实现 PR 切片

1. **#A4-stop-bleed**：只处理 P0/G0，完成受保护数据写入和四面负面验收。不混入 Racetrack / 前端美化。
2. **#console-evidence-math**：源级 opening wealth / 观测窗口已由 #1333 完成；继续 #1315 的日期、driver 和 Status 解释歧义。UI 其他视觉事项单独按屏拆分。
3. **#decision-brief** + **#evidence-review**：一屏一 PR，复用现有 reader，完成 #1305 未完成的代码工作。
4. **#research-runner-1**：冻结简单独立策略、研究回放、成本、收据和前端只读消费，作为第二位真正有比较意义的 US Runner。
5. **#cn-pool-runner**：CN130 EW + 原 CN registry/scorer；之后才考虑正式策略派生与月度审查。
6. **#prospective-review**：先用 Study Receipts 和现有投影完成一次人工复盘，只有真实负担被证明时才考虑轻量新交互。

以上 `#...` 是**工作包代号，不是已存在的 GitHub Issue/PR**；各实现 PR 只在前置 gate 成立后创建。当前进行中的 #1315/#1307 不要重复建同一缺陷任务。

## 4. 新功能方向的架构取舍

| 候选功能 | 决策 | 理由 / 最小产品形态 |
| --- | --- | --- |
| 每日“值得关注”的 Decision Feed | **现在做** | 最短的用户价值路径：从四策略信息中找出变化、限制与下一步，复用既有 Brief |
| 可证伪的证据审阅与研究→正式身份映射 | **现在先做证据审阅；映射后置** | 用户需要知道可信程度；研究身份映射必须有审查和授权，不能按股票代码匹配 |
| 真正独立的 US Runner、随后 CN130 基准 | **优先发展** | 让已建赛马引擎真正比较策略，而非仅可视化等权池；新模型须受制于样本外/OOS |
| 本地研究收据的人工观察/复盘 | **R1 后小规模做** | 积累错误判断与前瞻观察，而不是建设另一套交易账户、订单和日记后台 |
| Regime/市场环境指标 | **作为解释层研究，后置** | 可以解释赢家为何变化，但未经因果验证不可自动 gate/暂停 Runner，不给“市场天气”额外评分 |
| SaaS、多用户、自动下单、全市场策略商店、第二 Research IDE | **不做** | 与单操作者当前价值和研究可信性不匹配，增加权限/维护复杂度 |
| 统一 US/CN 排名、跨币种合成收益 | **不做** | 不同交易日、基准、币种；如未来需要，只能设计独立私有账户视图，不混同研究赛事 |

### 4.1 明确拒绝的架构捷径

- 同一份研究数据由 Python 和浏览器各算一套收益/排名，或者同一个「买点」具有两套权威；
- 把未审查的本地 Q/账户持仓公开化，靠浏览器是否显示来判断是否泄密；
- 用伪 Runner、裁剪持仓、自动猜别名、无 PIT 证据的 backward-filled events 凑出漂亮的完整赛季；
- “防未来需求”创建新数据库、配置中心、workflow、模型注册中心、Racetrack 专用 IDE 或兼容旧入口；
- 继续将 PR 数量、回测胜率、页面数量、通过单测总数视作投资价值指标。

## 5. 每个实现 PR 的统一验收格式（精简，不另造流程）

每个实现 PR 正文必须有：**用户问题 / 改动文件与唯一数据权威 / happy-path 和 blocked/negative case / 精确 SHA 与数据截止日期 / 可复现命令与实际结果 / 前后 UI 或产物证据 / 明确的 research_only 与发布资格 / 未解决问题与回滚**。涉及运行状态的 PR 必须给出真实生产/本地投递回执；涉及前端的 PR 必须检查桌面、平板和手机；涉及市场验证的 PR 必须给 OOS、费用、同窗口基准及前瞻验证限制。

本计划的**最小终点**不是把所有未来功能做完，而是：①公开写入风险真正关闭；②每日能够读懂三条以内最重要的信息及其反证；③同市场至少一条独立研究 Runner 在相同条件下与股票池/市场基准比较；④能据冻结证据做第一次真实前瞻复盘。**未完成任何一个环节，都要如实标记**。

## 6. G0 checkpoint foundation (2026-10-30)

`alpha ops checkpoint-ledgers` now captures the **complete active-registry ledger subtrees**, using the existing ledger schema and registry identity. It preserves original bytes of latest/manifest, sealed records (including legacy fingerprint filenames), corrections, delivery receipts and ledger README. Nonactive model directories are listed explicitly as excluded and remain untouched; this is not a backup or migration of retired models.

The ZIP is protected state. Its CLI output is metadata only. Use a fresh path **outside the repository**; ignored files are not private because build/artifact upload paths can include them. Restoration requires the exact archive SHA-256, size and registry bytes, and a fresh directory. Never use a partially written directory after an I/O failure; restore does not activate or overwrite a live ledger root. Local filesystem permissions remain the operator's responsibility (POSIX modes do not establish Windows ACLs).

```powershell
uv run alpha ops checkpoint-ledgers --output <private-outside-repository>/checkpoint.zip
uv run alpha ops checkpoint-ledgers --restore <private-outside-repository>/checkpoint.zip --expected-sha256 <receipt-sha256> --expected-byte-size <receipt-size> --output <private-outside-repository>/fresh-restored-ledgers
```

This describes the #1322 lossless transport foundation; live integration and the subsequent public boundary are tracked in §6.1. It introduces no database, registry, scheduler or new workflow. Acceptance must preserve the following properties independently of whether a PR has merged:

- Preserve canonical decision/correction/receipt semantics; never treat missing private state as an empty first run.
- Preserve QQQ/US/CN workflow dispatch and BYD repository dispatch, without duplicate delivery.
- Bind Operations publication/cache identity to private state content, not only public main SHA.
- Remove remaining raw public artifact uploads: the outbox now retains only its metadata `result.json`, excluding its protected Operations projection. It also renders new public GitHub Issues as generic delivery-attempt receipts (including the title), while keeping detailed Telegram text and the original deduplication marker. Other workflows and existing disclosures remain open; no live notification was triggered to test this change.
- Verify authenticated entitled/denied/revoked reads and all four public-surface negatives. Existing public disclosures remain residual risk.

The CN27 formal builder already strips embedded runtime state; current and historical artifact inspection remains separate. Neither checkpoint tests nor a successful private archive readback close G0 or Gate A4. See [the audit](../architecture/current_operations_security_audit_1288.md).

### 6.1 私有生产接线（按 #1322 的 2026-10-30 评论裁决）

#1326 已将四个 producer、Formal prepare/plan/strategy/publish、Operations 和 Outbox 接入既有私有 archive 中的同一完整 checkpoint；#1327 修正 Formal plan 的锁定 Python 环境。Git 快进推送提供 CAS，陈旧写入拒绝；Formal 固定私有提交，Operations 缓存绑定私有内容；Outbox 在外部副作用前持久化含糊状态护栏。安装前验证私有种子包含本地/公开密封记录；恢复回滚二次失败保留备份。真实 Formal run `40999354397` 以及后续 QQQ `40999790973`、BYD `40999790914` 成功；此前 US、CN、Outbox 和 Operations 也已有成功收据。

公开边界后续切换移除四个 producer / Outbox 的 Git 镜像及四活动账本当前树，详细信号不再打印到 stdout，producer / Operations 上传范围限定为元数据。旧密封经济轨迹保持；未来 MTM lineage 仅带私有输入引用，不复制当前权重。Formal 跨 job 原始 artifact、旧原生 MTM 内容及历史暴露、真实匿名/权限负验证仍待完成，不能据此宣布 A4 PASS。

实现与恢复约束见 [私有账本运行手册](../operations/private_signal_ledger.md)。代码/测试、真实 SSH probe、四策略实际运行连续性分别记录，不互相替代。#1315 的源级收益一致性与 #1324 的 RDI 价格更新可以按各自评论并行，不扩大为 UI 重设计、事件补零或正式信号。

RDI 的 [2026-10-31 进度与十类事件资格审计](../research/ashare_rdi_progress_2026-10-31.md)
记录了可重放价格续接预检：候选已至 2026-10-30，但旧证据缺 2026-06-23、
2026-06-22 OHLC 有冲突，原 append-only 路径仍 BLOCKED。
随后 [版本化修复与续接重算](../research/ashare_rdi_price_reconstruction_2026-10-31.md)
通过归档原始响应回放，保留原源文件，交付至 2026-10-30 的价格层证据及未成熟尾部；
事件层仍 0/10，未刷新 UI、未冻结前瞻评估、未生成 RDI 分数。

## 8. Forward cutover and Formal private transfer (2026-10-30)

#1328 merged as `66243fa646873db3b10e59fdeacfa47c06ba071f`. Four active public
ledger subtrees and their mirror writers were removed after preserving all 267
files privately. Anonymous Raw/Contents checks on main and the exact merge SHA
returned 404 for all 16 active-latest requests. Post-cutover US/CN/Operations/
Outbox runs succeeded; their inspected public artifacts contain metadata only.
These proofs do not cover old Git history, all historical artifacts or real
entitled/denied/revoked reads; A4 remains FAIL.

Merged #1329 (`5c8a3151deac366a439288dad995a9848ad33e2a`) replaces the Formal cross-job raw strategy-result
upload with immutable members in the **same existing private archive**. Public
artifacts carry only exact run/attempt/code/plan/task/archive bindings. Restore
must finish for all required siblings before the unchanged atomic fan-in reads
them. Failed evidence is retained, not converted into a successful result.
Local concurrency and negative tests are implementation evidence; real eligible
strategy transfer remains NOT_TESTED until a production receipt exists. No new
registry, database, evaluator, workflow or scheduler is introduced.

Separate operating blocker: Formal run `41043423440` passed private prepare and
US provider work but CN publication failed closed: the 515180 Yahoo record was
an incremental update through 2026-10-30, while its existing fallback admission
requires `fetched_full_refresh`. Neither the action nor the admission gate may
be relabeled to pass. Investigate exact source/provider/basis continuity in a
separate scoped fix; no new Formal candidate was published by that run.

## 9. Authorized sequential delivery

The operator authorized this order on 2026-10-30. Each step needs its own
reviewed implementation and evidence; a later independent blocker does not
erase earlier verified results.

1. **515180 source contract — implemented #1330, merged `5a6670a3`.** Keep strict full-refresh Yahoo
   fallback admission. Only requested, already-authorized CN formal auxiliaries
   that actually select Yahoo obtain a complete requested-range source vintage;
   never merge a legacy seed into that full snapshot, drop prior observation
   dates, relabel an incremental fetch, or refresh the whole candidate pool.
   Normal run `41083709573` verified preferred Tencent source through 2026-10-30;
   the Yahoo-only conditional remains fixture-verified, not live-exercised.
2. **Real Formal private transport — PASS.** After source recovery, obtain
   an eligible normal run with exact private archive and atomic fan-in receipts.
   Stop on data/transport failure; do not invent a strategy task to pass a gate.
   #1331 (`2a80e4f5`) fixes ZIP container dates for sealed epoch-dated BYD inputs.
   Run `41083709573` passed both real private retentions, exact restoration,
   atomic fan-in and Bundle construction; candidate #1332 merged `30a3df54`.
   The same real run completed successfully, including candidate checks, merge
   and exact Pages verification. CN economic prefix
   is preserved within the existing numerical tolerance, not byte-identically;
   BYD's old report prefix is exact. Failed/cancelled runs remain retained.
3. **#1315 source consistency — PASS for the scoped source-window defect, #1333 merged and deployed.** Reconcile US x1.3 dates, opening NAV,
   observation counts and source identity; preserve source economics. Desktop,
   mobile, production build and deployed-SHA browser evidence passed at
   `22d4e07d6dea796084642b6d61be670913499a64`: 288 unit tests and 117 static
   browser tests passed. Live desktop/mobile both matched the source window
   2024-01-02–2026-10-23 (68 settled observations), opening NAV 1 and first
   settlement 2024-01-17, with no horizontal overflow. This does not complete
   every historical #1315 item or the full A3 acceptance gate.
4. **A4 — FAIL.** Complete independently possible public-surface negatives and
   entitled/denied/revoked real reads using the existing access system. Missing
   real-session evidence stays explicit; fixtures/CI never substitute for it.
   The operator confirmed no dedicated real test account/session is available;
   accountless observations are recorded in the
   [A4 receipt](../evidence/product_v1/accountless_access_observation_2026-10-31.json).
   All live strategy policies currently read public; retired CN x1.2 remains
   visible. Protected-row rejection and real-session tests stay NOT_TESTED.

## 10. 2026-10-31 发布闭环检查点

- #1339 收口产品 A0–A7 与 RDI 里程碑；#1340 将新价格证据接入现有 Status。
  Pages run `41192493672` 成功；`eb5c2b1866540890d89fb5d12a06a6e4dba8923c`
  桌面/手机均验证新来源链接、5,238 行、各周期成熟边界、0/10 及无横向溢出。
- [A1 最新取证检查点](../evidence/product_v1/operating_closure_checkpoint_2026-10-31.json)：
  精确私有版本恢复后，Formal `41160909644:1` 四策略机械检查通过，QQQ/BYD
  具本次 daily due 证明，US/CN 为保留目标；独立复核和人工干预计数仍待完成。
  405 份采集、58 个不同运行尝试只是归档目录库存；本次只重审最新 packet，
  不能据此声称全历史已审、20 日合格或人工干预为零。A1 继续 BLOCKED。
- #1335 的无关锁文件升级会触发旧 RDI 全锁哈希相等断言；#1341 单独处理
  采集/回放依赖来源记录的兼容性，保留所有来源与 CSV 精确校验，再验证真实升级。
  不因旧分支 CI 绿色而跳过当前 main 的依赖兼容检查。

产品仍 NO-GO；A4 真实账号和历史披露处置、A6 恢复演练、A7 Owner 决定均未自动关闭。

### A1 归档范围复核（后续于上面的最新 packet 检查）

[完整归档来源/覆盖收据](../evidence/product_v1/operating_archive_reaudit_2026-10-31.json)
固定私有 revision `a1efd513c06fe95eeb9a291cc6771399ce863025`：405 份采集的
Git blob 字节/身份及 ZIP 索引成员完整性均通过。按每个 run/attempt 的明确采集时间
选取 56 份最新 packet，两个尝试因采集时间/观察证据不足保持选择阻断，
不退回更早绿色结果。该收据仅公开哈希、选择与观察元数据，不公开私有目标。

US/CN 的最近 20 个应有交易日窗口内各有 12 个日期被观察、8 个日期缺记录；
其中匹配当前四策略身份的日期仅有 6 个。旧身份记录保留，不能据此追认为当前四策略
20 日连续运行。无独立复核声明、人工干预计数未知，合格数仍为 0。
下一步是补齐真实记录、独立审查各日和 due-cycle/恢复证据；不是补造观察或把
“还缺 8 日”直接换算成保证上线日期。

归档审查发现 collector 的 missing/expired-artifact 分支缺少采集时间戳。
修复为所有被保存的 readiness（包括失败）记录明确 UTC 采集时间，拒绝无时区输入；
它不使失败记录合格、不修改旧封存 packet，也不新增工作流。

### 2026-10-31 · 详情 Evidence Review 实现进展

按 #1305 P0，现有详情页补齐已验证正式收据的支持证据、全部 gate、反证、解释局限与下一步；待审阅、缺失、校验失败继续独立呈现。Overview 三重点已在 #1344 部署，并于 desktop/375px mobile 复核三条重点与完整四策略 Fleet，页面横向溢出 0px。证据详情的最终浏览器/部署验收在 implementation PR 记录。该实现不开放 P1 研究身份猜测关联，不关闭 A1/A4/A7 或 RDI 认证门禁。

## 11. 2026-11-01 远端任务收敛

### 11.1 核对范围与已交付事项

远端快照为 **2 个开放 PR、35 个开放 Issue**；其中 8 个 Issue 是历史信号通知，
不是开发任务。快照数量不代表下面收口动作后的实时数量。核对基线为
`594706836415fcc73d407c33bfae137de26e89c8`，不读取或摘录当前私有持仓。

- #1333 的源窗口/起始 NAV、#1340 的 RDI 证据视图、#1344 的三重点和
  #1346 的正式证据审阅已交付，不重复开发。#1346 Pages `41217424837` 成功；
  2026-11-01 实际 desktop/375px mobile 在精确 SHA 上验证五组证据、
  `pending_review`、2026-10-30 截止日及 0px 横向溢出。300 单测、117 静态浏览器通过。
- #1278 要求的入口、历史文档标记和四策略路由已存在；本次补入当前执行路线链接，
  两项路由测试通过，可按已完成收口。它不代签 A7 产品 GO。
- #1227 的旧完整失败 run `40173255288` 的 shard 3 仅有两个失败，均为旧
  CN x1.2 活动发布断言。当前相应测试已转为历史包精确性、退役发布拒绝和四策略
  registry/catalog 一致性，5/5 通过。本次当前 main 的既有完整 workflow
  [run `41287052604`](https://github.com/liuh886/alpha_engine/actions/runs/41287052604)
  **仍 FAIL**：shards 1/2 通过，0/3 共 6 项失败，现已定位到两个模块：
  `test_walk_forward_shared_matrix.py` 两个参数场景缺少 Qlib 初始化；
  `test_supplemented_holdings_evidence.py` 四项依赖 PL 附加证据/目录和 Owner 本机 pool。
  #1227 保持开放；先核对 shared-matrix 调用是否错误引入 provider 初始化，再将
  Owner 本机验收与可移植的最小受控 fixture 分开。禁止联网补造行情或仅删除断言。
  单文件绿色不等于全仓绿色；本次只复用既有 CI，未运行模型研究。
- #1282 的旧说明仍写 #1293 待合并，但 #1293 已合并为
  `874492a748e5bdd1614d8470107b08c0c1c5f916`。旧失败和旧截止日保留；
  这消除了过时的合并依赖，不代表已对当前环境完成新重放或取得 Owner A5 验收。

### 11.2 现在可落地的队列（已收口，全量合入 main）

| 顺序 / 既有归属 | 交付成果与对应 PR | 完成标准 / 停止边界 |
| --- | --- | --- |
| 1 · #1227 全仓健康 | **已修复并完整验证 #1348**：shared-matrix 重复初始化及测试本机依赖；见 §11.5 | 保留所有 shard/JUnit/精确 SHA；维持缺源与非共享初始化边界，不删除失败证据 |
| 2 · #1279 / 原 #1315 界面语义 | **已完成 #1350**：修复长小数截断、中立驱动图标替换、375px 移动端自适应与 Playwright E2E 断言 | 302 项单元测试 + 117 项 Playwright 静态端到端全绿通过；不重算判断或改源收据 |
| 3 · #1282 A5 证据更新 | **已完成 #1351**：CN27 精确重放（容差 $\le 10^{-6}$），QQQ 真实记录数据阻断，修复 Windows junction 路径解析 | 33 项单测全绿；新旧收据并存，缺源如实标定 BLOCKED，Owner 验收单列 |
| 4 · #1279 / #324 / #325 A2 依赖清单 | **已完成 #1352**：证实四策略日常运行依赖与独立研究训练宽表完全解耦，完成 Alpaca/SEC EDGAR 预检 | 56 项数据面契约测试全绿；不把训练阻塞外溢至四策略，保留窄策略参考角色边界 |
| 5 · #1281 A6 候选与恢复包 | **已完成 #1354**：验证发布验证器三大守卫机制，演练静态版本回滚与私有账本 CAS 恢复 | 46 项发布门禁测试全绿；记录静态、正式与当前运行身份的边界，生产操作待 Owner |

以上工作可在无专用测试账号时继续。依赖未满足时记录精确阻塞后，执行下一独立项；
不因权限阻塞扩展新产品，也不让通过的独立证据被全局标为失效。

无秘密值的远端配置预检另发现：`APCA_API_KEY_ID` 与
`APCA_API_SECRET_KEY` 名称已存在，不能继续把 #325 描述为“尚未配置凭据”。
**下一步可直接核对认证、SIP/OTC entitlement 与精确 US87 来源窗口**，成功后才按既有
`alpha158-canonical-vwap-ci.yml` 合同做来源物化；名称存在不证明服务可用或 Alpha158 合格。
本次未读出秘密值、未触发取数/训练。SEC 只见 `SEC_USER_AGENT`，未见声明的
`SEC_EGRESS_PROXY_URL` 配置名或独立 proxy identity 配置名；#324 的 trusted-egress 来源预检仍需单独处理，
不以此封锁 CN 或窄策略有效证据。

### 11.3 原 #1315 的逐项去重与保留

原提案保存在 [#1315](https://github.com/liuh886/alpha_engine/pull/1315)，
来源提交 `fb413cd03a830020115f7342389f1bb664400a07` 的
`docs/product/frontend_polish_spec_2026-10-28.md`；原文 SHA256
`2c27706b557f21dd8d19843ea01e48c777759edca3ccbeccb2555d8667130a46`。
其 2026-10-28 页面观察是历史证据，不自动证明当前页面仍有该缺陷。
剩余事项迁到本节后，关闭该 docs 提案为 superseded；不称为全部 polish 已完成。

| 原项 | 收敛后的状态和下一动作 |
| --- | --- |
| P0-1 日期词汇 | 待按当前四策略复核 data cutoff / decision applies / backtest window，不统一为误导的单一 as-of |
| P0-2 US 收益口径；P0-3 BYD 基准 | #1317 / #1333 已关闭该具体缺口；保留源窗口、opening NAV、settled/provisional 和声明基准回归 |
| P0-4 Fleet 窗口；P0-5 excess 空值 | #1320 已交付；维持实际窗口、过期与缺失原因，不伪造值 |
| P0-6 driver 含义 | 待按规则策略与 ranker 各自来源核对 neutral/unknown/support/veto；禁止从中性值推断无风险或因果 |
| P0-7 载入/拒绝 | Overview #1318 已完成；Status 部分与真实受限会话矩阵待核对；缺会话 NOT_TESTED |
| P1-1 代码首见展开；P1-2 排序 | 复核人类可读名称与一致的 fleet 顺序；Brief 按关注状态排序是明确例外，不能删掉优先级语义 |
| P1-3 Selected Evidence；P1-4 导航命名 | 先证明该组件/文案仍存在；退役入口不恢复。维持两个导航目的地 |
| P1-5 Racetrack 空状态 | 只复核现有 Overview 内的本地研究入口和 hosted 不可用原因；不恢复 ZIP/独立浏览器研究，不公开私有 Q |
| P1-6 Status 重复；P1-7 Stale 原因 | 当前页审计后按已见缺陷精简重复信息、让原因可读；保留独立来源/正式/运行截止日 |
| P2-1 表格；P2-2 数字 | 375px 的证据文案长小数已观察；先研究来源语义，再做显示层格式化，不任意替换源字符串或统一改经济值；完整表格待审 |
| P2-3 重复 chrome；P2-4 平板 | 按现存表面验证密度、滚动和布局，不发起重设计；三端验收继续复用已有测试 |

### 11.4 远端其他任务的处置

| 既有 Issue / PR | 状态和当前动作 |
| --- | --- |
| #1074 | 保留为收敛总纲，链接本路线与上述五项；不再有第二套独立执行排序 |
| #1278 | 已关闭 completed；当前权威与历史入口已验证，#1347 已补当前路线链接 |
| #828 | 已关闭 superseded；八月前端总纲由本路线/#1279 接续，不是宣称所有历史功能已完成 |
| #858 | 八月混合架构审计后置为历史待核对，由 #1074 统筹；不照旧计数恢复引擎、模型或扩因子 |
| #1113 | 已关闭的旧 incident：后续 `41083709573`、`41216055804` 成功及 #1332/#1343 已证明当前发布路径恢复；原失败和旧决策不重写，关闭 incident 不代表 A1 通过 |
| #1277 | 继续 BLOCKED；完整归档复查已交付。当前身份仅 6 个观察日期、0 独立合格；真实日期、due-cycle/恢复和干预审阅不能补造 |
| #1279 | 继续开放；上述界面工作与无账号检查可推进，实际授权/拒绝/过期/撤权和旧披露处置保留门禁 |
| #1281 / #1282 | 继续开放；按队列准备 A6 / 更新 A5 证据；Owner 验收与实际生产动作不代签 |
| #324 / #325 / #826 | 保留为来源/因子/训练的唯一归属；当前缺失先复核。独立策略不因无关训练输入受阻，不把历史 US x1.2 当成当前正式 US 身份 |
| #1272 | RDI 价格层与证据视图已交付；事件 0/10，首个 PIT 家族选择/冻结仍待 Owner。未得到选择前不实施 M3 取数、不回溯宣布前瞻起点 |
| #746 | BYD 真前瞻观察继续保留，重放/回填不冒充 untouched 证据；不改冻结机制 |
| #719 / #801 | 诊断证据需求保留；#801 的旧 CN x1.1 不是当前恢复目标，任何现行模型补证须先绑定 #719 的精确当前合同，不新建 CN 专用 UI |
| #226 / #228 / #229 / #225 | 累积失败记忆和冻结研究保留为后置任务；旧 small-pool/低换手运行已退役，不能按旧任务恢复运行。独立研究仍可另按冻结合同和命名空间继续，不重开已消费窗口 |
| #966 / #999 | 已有阶段证据保留；旧 US x1.2 选集认证后置，不能替换当前 US x1.3，不重跑选集搜索 |
| #1052 / #716 | 备选交互/架构/研究思想后置；没有当前四策略直接用户缺陷，不进入近期功能队列 |
| #763 / #277 | 仓库维护保留；可只读做 reachability/恢复包审计。删除 refs、历史重写、Support 与服务端 GC 另行治理，不为收敛数字删数据或改历史 |
| #1307 draft | 保持独立后置 RFC；没有当前发布必需交付，不合并为正式策略路线，不开始新信号/OOS/阈值调优 |
| 8 个历史信号 Issue | #1269、#1226、#1220、#1205、#1200、#1149、#1120、#1119：通知/研究审计记录，不计开发任务；本次不重发、不删内容、不据此认定已解决历史披露 |

**本次收敛的完成定义**：一个当前入口、一条可执行队列、每项真实阻塞有归属，
旧提案/旧 umbrella 不与当前任务竞争；不以减少 Issue 数字冒充发布完成。
产品仍 NO-GO；A4、真实运行验收、Owner A7 和 RDI 研究资格保持原门禁。

### 11.5 #1227 首批修复与完整健康验收（2026-11-01）

[#1348](https://github.com/liuh886/alpha_engine/pull/1348) 修复两模块六项失败：
共享矩阵子任务跳过重复 Qlib 初始化，普通父任务仍初始化；带正标签周期的
calendar 读取保留原合同。附加持仓测试使用临时合成资料与现有治理配置，
验证真实 reader/audit、缺源阻断、参考角色和字节不变，不读取 Owner 本机目录，
不宣称实际个人持仓覆盖已通过，不增加生产行情或跳过测试。

代码提交 `0916019c7e275065776b37507f7c04815c13d4d9` 的既有完整健康
[run `41288826697`](https://github.com/liuh886/alpha_engine/actions/runs/41288826697)
全部成功；独立重读四份 JUnit：**4,231 passed / 8 skipped / 0 failures / 0 errors**。
另有 60 项相邻测试、Ruff、普通 PR backend 与独立代码审阅通过。
本段是在完整结果产生后补记的文档；该运行绑定上述代码提交，不冒充测试后补记文字的 SHA。
原失败 run `41287052604` 保留；#1348 已合并为 `f68f1c1198e1af4b8fcdd60219dee878d5c64321`，#1227 已关闭 completed。

当前执行队列从 **第 2 项 #1279 的日期/driver/Status 实际页面复核**继续；
A1、A4、A5、A6、Owner A7 与 RDI 的各自门禁不因全仓测试绿色而关闭。

## 12. 接手 Agent 的执行细则（2026-11-01）

本节是 **§11 同一队列的可执行交接**，不是另一个 roadmap；父 Issue 仍是任务归属。
本交接 PR 只整理工作，不宣称下列未勾选项已完成，也不要求一个实现 PR 包办全部事项。
接手时先 fetch 当前远端；`f68f1c1198e1af4b8fcdd60219dee878d5c64321` 仅为交接核对基线。

### 12.1 接手前先确认

1. 阅读 [AGENTS.md](../../AGENTS.md)、[当前产品/本地 Agent 入口](strategy_console.md#local-agent-start-here)、
   §0 门禁、§11 全量归属和父 Issue 的最新评论；旧任务标题/旧审计不自动代表当前状态。
2. 确认 `git status --short`，保留用户 WIP；在独立 branch/worktree 做一项工作。
   不把其他 Agent 本机的 ignored ledger、临时 archive/cache 或登录会话当作干净 checkout 的前提。
3. 读取 [四策略 registry](../../configs/strategies/registry.json) 和
   [正式 catalog](../../data/research/formal_model_runs/catalog.json)；保存实际 SHA、模型/Bundle 身份与 cutoff。
   不把 registry 中的 `qqqi_qqq_tqqq_v4_3` 与 CLI 别名 `qqq_v4_3` 混淆。
4. 复用现有锁文件：仓库根 `uv sync --frozen --extra dev`；前端在 `qlib-dashboard` 执行 `npm ci`。
   Node 版本以 package.json engines 为准。缺依赖先报实际错误，不顺手升级整个工具链。
5. 一项实现一个小 PR，PR body 写输入身份、前后行为、验收结果、剩余阻塞及回滚方式。
   共享合同改动先查调用者；跨工作包不复制来源、权威、evaluator、scheduler 或状态数据库。

### 12.2 已完成：不要重新实现

- [x] #1278 权威文档收口；#828 与 #1315 旧提案已被替代，#1113 旧 incident 已恢复。
- [x] #1333 US 源窗口/起始 NAV；#1344 Overview 三重点且完整四策略保留。
- [x] #1346 正式 Evidence Review：支持、门禁、反证、局限、下一步；真实 desktop/mobile 已验证。
- [x] #1338/#1340 RDI 版本化价格层和 Status 证据视图；依然 `not_validated`、0/10。
- [x] #1348 全仓健康修复：4,231 passed / 8 skipped；精确代码 SHA 与完整 run 见 §11.5。
- [x] #1350 (H1) 控制台 UI 语义、日期格式与 E2E 断言修复；302 项单元测试 + 117 项 Playwright 静态端到端全绿，已合入主线。

- [x] #1351 (H2) 当前环境有界重放证据固化与 Windows junction 修复；CN27 重放误差 <= 1e-6，QQQ 真实记录数据阻断，已合入主线。
- [x] #1352 (H3/A2) 四策略数据依赖对账与凭据预检；解耦训练池与四策略运行依赖，56 项测试全绿，已合入主线。

- [x] #1353 (G2/A4) 安全与权限验收；四大暴露面止血验证，82 项测试全绿，明确残留风险并维持 A4=FAIL，已合入主线。
- [x] #1354 (H4/A6) 发布、恢复与回滚演练；发布守卫与 CAS 恢复验证，46 项测试全绿，已合入主线。

- [x] #1355 (Scorecard) 记分卡与任务清单终审收敛；更新 product_completion_scorecard 与 Master Plan，已合入主线。

历史测试数字是对应提交的证据，不是接手时自动获得的 PASS；只有修改范围、失败或未解风险
要求时才重跑/扩大检查。纯文档交接不需要启动全仓研究或重新取数。

### 12.3 H1 · 界面语义与无账号旅程（已完成，PR #1350）

- [x] **页面走查与真实缺陷修复（已合入 PR #1350）**：在实际部署 SHA 上逐四策略走
  Overview → Detail → linked Instrument → Status；覆盖 desktop 与 375px mobile。
  依次核对 data cutoff、decision applies、retained target date、backtest/settled/provisional window、
  声明基准与 excess、driver state/effect/reason、next due、loading/error/retained 状态。
  changed/unchanged/not-due/blocked 的 fixture 是可复现代码检查；缺实际样本仍 NOT_TESTED。
- [ ] 根据 §11.3 的原 18 项逐项记 PASS / observed defect / absent-retired / NOT_TESTED；
  不恢复不存在的 Selected Evidence/旧导航。先处理真实 P0；没有更高严重度缺陷时，
  处理已见的证据文案长小数，随后再考虑密度/平板等 P1/P2。
- [ ] **数字格式化必须先确认源语义**：证据 statement 当前是来源文本，不保证是结构化比率。
  不对任意文本做全局正则乘百分比/舍入替换，不修改密封收据来美化展示。
  优先复用已有结构化指标/格式器；若需要新字段，先独立提交源合同与投影校验的小 PR。
- 代码入口：[DailyResearchBrief](../../qlib-dashboard/src/components/DailyResearchBrief.tsx)、
  [StrategyFleet](../../qlib-dashboard/src/components/StrategyFleet.tsx)、
  [StrategyDetailPage](../../qlib-dashboard/src/pages/StrategyDetailPage.tsx)、
  [SystemHubPage](../../qlib-dashboard/src/pages/SystemHubPage.tsx)、
  [ResearchTrackingAssessment](../../qlib-dashboard/src/components/ResearchTrackingAssessment.tsx)。
  读取边界：[strategy-operations](../../qlib-dashboard/src/lib/strategy-operations.ts)、
  [model-run-decision](../../qlib-dashboard/src/lib/model-run-decision.ts)。
- 验收：先有原图/复现步骤、cutoff/Bundle 与期望含义；新增必要的定向正负用例，
  再运行现有生产 build、静态三端与实际部署验收。不得让 pending/access/error 变成“无变化”或假成功。
- 产物：一份不含当前私有配置/仓位的旅程矩阵与截图/trace 引用；一个范围明确的修复 PR，
  或带准确原因的“当前无该缺陷”审计结果。Owner 完整 UAT 和真实权限不是本包自动完成项。

### 12.4 H2 · 当前 US/CN 有界重放证据（已完成，PR #1351）

- [x] **当前环境重放与路径修复（已合入 PR #1351）**：阅读 [W3 说明](../evidence/product_v1/w3_local_replay_2026-10-25.md)、
  [旧收据](../evidence/product_v1/w3_local_replay_2026-10-25.json)、
  [QQQ CLI 对齐收据](../evidence/product_v1/qqq_cli_replay_alignment_1292.json)，
  重新验证它们的实际输入是否在当前环境可得。#1293 已合并，不再等待其实现。
- [ ] 在当前 frozen 环境执行既有 `alpha research replay qqq_v4_3` 和
  `alpha research replay cn_27_v1_3`；先看 `--help`。不默认加 `--refresh-data`、
  不新训练、不替换来源/模型/截止日。原始来源缺失时先记录 BLOCKED，而不是补造 PASS。
- [ ] 保存命令/退出码、lock/源/模型/evaluator/费用/日历哈希，重复核对确定性及既定容差；
  区分 frozen economic prefix、重算决策/追加经济和旧历史截止日。
  使用已有缺源/错身份负例；不得修改密封经济证据或把重放算作新 OOS。
- 代码：[CLI](../../src/cli/main.py)、[QQQ authoritative replay](../../src/research/qqq_authoritative_replay.py)、
  [CN_27 replay](../../src/research/cn27_v1_3_replay.py)、
  [rules replay gate](../../src/research/rules_formal_replay_gate.py)。
  相关测试：[formal replay](../../tests/test_formal_model_replay.py)、
  [rules replay](../../tests/test_rules_formal_replay_gate.py)。
- 产物：当前环境的新有界收据/解释和精确阻塞；旧收据与初始失败保留。Owner A5 接受单列，
  不因命令成功关闭完整数据资格或所有模型的训练复现要求。

### 12.5 H3 · 必需输入清单与来源预检（已完成，PR #1352）

- [x] **数据可信性与解耦核验（已合入 PR #1352）**：首先从四策略 frozen contracts 与正式 manifests 列出**实际必需**来源、PIT、复权、
  lifecycle、benchmark、cutoff/版本/调用路径；区分 selected-pool 训练要求和窄策略参考。
  复用现有 manifests/readiness，不建立另一套规则或以无关训练阻塞判四策略失效。
- [ ] #325：远端 Alpaca key/secret 的配置名称已存在；只读验证认证、SIP/OTC 权限、
  精确 US87 identity 和请求窗口，先拿到可审阅的小范围可用/阻断结果。
  不打印秘密值、HTTP authorization headers 或未经脱敏的响应。
- [ ] 来源角色/单位/复权资格通过后，再按现有 workflow 做明确 cutoff 的有界物化。
  `recent_us_research` 是独立近期资格范围，不等于 original 全历史通过；
  不用 validation-only 来源、close-as-VWAP 或临时改池填洞。
- [ ] #324：SEC trusted-egress 配置名在上次核查中未见，接手时重新确认；
  不使用任意代理或声明缺失事件等于“无事件”。CN 当前资格也按实际新收据核对，
  不把 2026-09-01 的 129/130 或 130/130 直接作为今天的认证。
- 代码：[canonical VWAP](../../src/data/canonical_vwap.py)、
  [Alpaca adapter](../../src/data/adapters/alpaca_adapter.py)、
  [event population](../../src/data/selected_pool_event_population.py)。
  复用 [VWAP workflow](../../.github/workflows/alpha158-canonical-vwap-ci.yml) 与
  [event workflow](../../.github/workflows/selected-pool-event-population-ci.yml)，
  VWAP 显式选 `market/source_scope/cutoff`；event 仅支持 `market/cutoff`。
  先读各自 inputs，禁止默认 both 全历史跑来代替预检。
- 产物：逐策略/逐来源矩阵和小范围预检收据；后续 materialization PR 只能认领该合同实际通过的覆盖。
  训练和 factor readiness 仍由 #324/#325/#826 各自 authority 认定。

### 12.6 H4 · RC 与非生产恢复演练准备（已完成，PR #1354）

- [x] **发布守卫与恢复演练（已合入 PR #1354）**：从已验证版本构造单一候选证据包，分别绑定静态产品、formal catalog/Bundle、
  私有 current-operations checkpoint 与 lock/source 身份；不能把三层不同版本揉成一个“最新”。
- [ ] 先在临时目录演练安装/恢复、精确源哈希和错误包/缺文件/错身份拒绝；
  复用既有 release gate/restore helper，不新增发布系统、兼容读链或调度。
  正向验收不得用 `--allow-verification-failure` 把候选校验失败伪装为成功。
- [ ] 输出可审阅的 Owner runbook：前置检查、预期结果、失败处置、回滚目标及恢复后验证。
  旧 artifact 若含历史公开披露，不能作为“隐私干净”的回滚目标重新发布。
  实际生产回滚、权限/披露治理以及 Owner 本机执行继续留待其明确执行/批准。
- 代码：[release gate](../../scripts/release_gate.py)、
  [private ledger/checkpoint](../../src/artifacts/private_signal_ledger.py)、
  [release candidate](../../src/release/candidate.py)。
  相关测试：[candidate gate](../../tests/test_release_candidate_gate.py)、
  [candidate generation](../../tests/test_release_candidate_generation.py)、
  [private ledger](../../tests/test_private_signal_ledger.py)。
- 产物：非生产试运行包、恢复/回滚步骤和 PASS/BLOCKED/NOT_TESTED。不得据此代签 Owner A6/A7。

### 12.7 持续证据 / 外部阻塞：可做部分工作，但不能伪造关闭

| 工作包 / 原 Issue | Agent 现在可以做 | 必须保留的外部依赖 / 退出证据 |
| --- | --- | --- |
| G1 · A1 / #1277 | 用现有 `alpha ops acceptance` 审计归档/最新 attempt、身份、eligible sessions、due/retained/recovery、声明完整性；保持 compact source-bound receipts | §11 的 6 个当前身份观察日期、0 独立合格是截止 2026-10-30 的审计，不是今天自动累计数。真实后续观察、真实干预计数和独立复核不可由 CI/回填替代；两个缺时间的旧失败继续保留，不退回更早绿包 |
| G2 · A4 / #1279 | 复核公开静态/Git/Actions/native lineage 披露清单、账户切换/缓存隔离的可复现负例；先读 access 合同及适用技能，真实检查保留 metadata | 用户确认无专用测试账号/会话；不得反复索取密码/token，不能改 live tier/entitlement 或造生产行来制造拒绝样本。实际授权/拒绝/过期/撤权、旧披露处置和 Owner 决定仍未闭合 |
| G3 · RDI / #1272 | 维护既有价格原始来源/冻结修复/重放与只读 Status；核对 M2 资格表，准备可审阅的首类 PIT 窄合同草案 | 首事件家族尚未选择（限售解禁公告为推荐、业绩披露窗口为备选）；不得自动选定或在确认前开始 M3 取数。0/10 / not_validated，真实 available-at/修订/absence/OOS/前瞻不足不能补造，无 score/第五策略 |
| G4 · Owner 发布 / A7 | 汇总 H1–H4 与 G1–G3 的版本化证据及准确风险，准备 GO/NO-GO 材料 | Owner 明确、带日期的发布裁决；Agent 或 CI 不代签。RDI 未验证不全局否决独立四策略证据，也不被产品部署成功顺带认证 |

私有证据恢复统一先读 [private ledger 手册](../operations/private_signal_ledger.md)：
通过项目既有权限定位精确 archive revision/commit、哈希及大小，恢复到**新的隔离目录**，
先校验身份再读取。若当前环境无读取权限或原包不可得，该依赖保持 BLOCKED 并继续独立项；
不假定机主的 ignored ledger/cache 已存在，不自动向用户重复索取账号，不复制私有 payload 到 PR。
公开交接只记录必要的身份、哈希、数量和状态，不输出实际目标/配置或秘密值。

G1 入口：[operating acceptance](../../src/artifacts/operating_acceptance.py)、
[完整归档收据](../evidence/product_v1/operating_archive_reaudit_2026-10-31.json)。
G2 入口：[access contract](../architecture/frontend_access_control.md)、
[无账号检查收据](../evidence/product_v1/accountless_access_observation_2026-10-31.json)。
G3 入口：[RDI architecture](../research/ashare_rdi_architecture.md)、
[价格修复与重放说明](../research/ashare_rdi_price_reconstruction_2026-10-31.md)。
不得编辑被当前 RDI review hash 绑定的源文档来添加进度；修改会使现有来源校验失败，需独立显式重绑。

### 12.8 PR 拆分、协作与验收记录（H1–H4 已收口完成）

| 原规划 PR | 交付成果与合并 PR | 完成状态与核验结果 |
| --- | --- | --- |
| H1 控制台语义与无账号旅程 | **已完成 #1350**：通常 dashboard 组件/formatter 与相关 tests 修复；长小数截断与移动端自适应闭环 | 302 项单测 + 117 项 Playwright 静态端到端全绿通过，已合入主线 |
| H2 当前环境有界重放包 | **已完成 #1351**：固化 CN27 重放（容差 $\le 10^{-6}$），QQQ 真实记录数据阻断，修复 Windows junction | 33 项单测全绿，新旧收据并存，已合入主线 |
| H3 必需输入清单与来源预检 | **已完成 #1352**：解耦四策略日常运行依赖与训练宽表，完成 Alpaca/SEC EDGAR 预检 | 56 项数据面契约测试全绿，已合入主线 |
| H4 RC 与恢复演练准备 | **已完成 #1354**：验证发布验证器三大守卫机制，演练静态版本回滚与私有账本 CAS 恢复 | 46 项发布门禁测试全绿，待 Owner 生产操作 |

历史顺序 H1 → H2 → H3 → H4 已全量落地合入主线。
PR #1357 前端工作区架构演化（H0~H5：A 方案决策优先、TradingView 轻量图表 POC、策略与研究详情重构、系统运维页聚焦及文档对齐）已全部在 PR 分支闭环并通过 123 项全量 E2E 验证。

当前后续关注点依然严格集中在三条主线：
1. 关闭 A4 / A3 权限边界与清理退役运行行；
2. 持续收集并客观复核 A1 真实交易日（等待自然交易日累积，不伪造通过）；
3. 形成最终绑定的 Release Candidate（A5 有界验收口径与 A6 Owner 签批）。

**命令使用现有接口；示例均非发布授权。** 按 `--help` 核对参数和实际 source prerequisite，
先定向验证；以下较宽验收只在相应实现变化/失败确实需要时执行。

```powershell
# 仓库根：有界重放（不默认刷新或训练）
uv run --frozen --extra dev alpha research replay --help
uv run --frozen --extra dev alpha research replay qqq_v4_3
uv run --frozen --extra dev alpha research replay cn_27_v1_3

# 运行观察仅阅读；input-root/through 用本次真实 packet 与截止日
uv run --frozen --extra dev alpha ops acceptance --help
# RC 必须明确 candidate；先核对当前工具，不默认选择或发布候选
uv run --frozen --extra dev python scripts/release_gate.py --help
```

前端在 `qlib-dashboard` 下执行 `npx tsc --noEmit`、定向 Vitest/ESLint，
需要宽验收时 `npm run build`、`npm run check:bundle-budget`，再运行
`npx playwright test --config playwright.static.config.ts`。
该 build 包含单测与资产同步，不与会修改相同 `public/data` 的其他测试同时运行。
实际部署在根目录设置 `$env:PYTHONPATH='.'` 后执行
`uv run --frozen --extra dev python scripts/verify_pages_release.py --base-url <实际PagesURL> --expected-commit <实际40位部署SHA>`
（替换占位参数，不能拿默认/旧 SHA 通过），再在前端设置 `$env:PAGE_URL='https://liuh886.github.io/alpha_engine/'`，执行
`npx playwright test --config playwright.live.config.ts`。
现有 live config 的 mobile 是 Pixel 7，若验收要求 375px，须另记录实际 375px 结果；
不得把设备 preset 名称当成已验证指定宽度。截图/日志只保留可公开证据区，不包含当前私有权重。

全仓健康复用 `.github/workflows/ci.yml` 的有界 manual/scheduled 分片；
不得把普通 PR backend 的 selected/core 测试等同完整健康。
需要时 `gh workflow run ci.yml --ref <已推送的候选branch>`，记录实际 run SHA 和四份 JUnit，
保留失败。不是每个文案 PR 都重新运行所有研究/训练/健康流程。

### 12.9 每项必须回写的交接格式

- [ ] 父 Issue、范围、当前 branch/base SHA、实际代码/测试 SHA；docs 后补必须明确区别。
- [ ] 输入 contract/registry/pool/source/Bundle/hash/cutoff、依赖可得性；无凭据值/私有权重/个人笔记。
- [ ] 复现与期望、最小改动、PASS/FAIL/BLOCKED/NOT_TESTED；fixture 与真实验收分别列。
- [ ] 相关命令、退出码、精确 CI run/artifact 与必要的安全截图/trace；不只写“tests pass”。
- [ ] 独立 review、原失败与源不可变性、回滚方式、未完成部分及接手的第一条动作。
- [ ] 更新本路线相应项和原 Issue/PR；只有实际完成的子项打勾，Owner/时间门禁不自动关闭。

后置的 #1307、factor-memory、旧模型认证、仓库 refs 维护等仍依 §11.4 归属，
不是接手 H1 的隐含前置条件。整个交接保持 `research_only=true`、`trade_ready=false`；
不恢复退役入口、不新增主导航、模型、分数、策略、执行器或常驻工作流。
