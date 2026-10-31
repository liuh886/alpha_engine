# Alpha Engine — 下一阶段产品架构与执行计划

**当前裁决：产品 NO-GO；RDI 价格层已交付，完整 RDI 未验证。** 最新核对基线为 `main@ba48883926c2749c01d148767efcf47a7db86825`，2026-10-31；2026-10-29 的原路线基线保留为历史。本文是**当前下一阶段执行顺序的唯一入口**；旧的 [2026-10-26 路线图](investment_research_infrastructure_roadmap_2026-10-26.md)仅作历史决策记录，[研究问题库](future_research_agenda_2026-10-28.md)仅作备选议题，[#1315](https://github.com/liuh886/alpha_engine/pull/1315)是 UI 具体缺陷清单，[#1307](https://github.com/liuh886/alpha_engine/pull/1307)是独立 BDCR 研究 RFC。下列每项只有通过**独立实现 PR + 证据验收**才算完成；路线合并不批准产品 GO。

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
| A0 身份与权威，#1278 | 实现与身份对齐已通过；旧路线文字需跟进 | 保持四策略、正式/研究边界及同一当前路线入口；以当前 SHA 复核，不恢复退役路径 | Agent |
| A1 持续运行，#1277 | **BLOCKED**；最新成功运行不是 20 日验收 | 复用现有 operating acceptance，逐 US/CN 市场重审实际 20 个合格交易日、所有失败/保留/not-due 分类与真实 due-cycle；缺收据明确列缺口 | Agent 审核已有收据；缺失的真实未来交易日必须等待，禁止补造 |
| A2 数据完整性 | **BLOCKED**；正式 cutoffs、RDI 价格及窄回放各有局部证明 | 为四策略实际依赖列源级 PIT/复权/生命周期/版本证据；将独立研究阻塞与策略必需输入分开，缺项定向修复 | Agent；必要原始来源或权限需 Owner/提供方 |
| A3 用户旅程，#1279 / #1315 | 部分线上/模拟验收通过，完整边界矩阵未关闭 | 完成四策略桌面/手机的变化、未变化/not-due、延迟/阻断、拒绝旅程；修复日期/driver 语义和证据审阅缺口，保留真实证据 | Agent 负责可复现代码/公开旅程；真实受限会话需 Owner |
| A4 权限与披露，#1279 / #1288 | **FAIL**；活动公开账本、新原始传输路径已止血，旧披露和真实权限验收未关闭 | 处置旧 Git/Actions/native lineage 披露、退役 CN x1.2 运行行；准备受保护测试资源，完成匿名/无权/过期/撤权/授权及缓存负验证 | Agent 做只读审计与修复 PR；Owner 决定披露处置、提供专用会话并批准实际权限/数据治理 |
| A5 本地研究，#1282 | 有界 CN/QQQ 回放通过，最终验收范围仍需确认 | 用已接受 US/CN 参考研究和精确依赖/数据哈希复核重放与限制；不要求新模型盈利，也不把无关训练阻塞泛化 | Agent 复核；Owner 最终确认 |
| A6 发布与恢复，#1281 | 具体 SHA 发布校验通过；完整恢复演练未验收 | 形成 RC 证据包，在既有工具下验证恢复/回滚、数据与运行状态身份；不改密封经济历史，不新建发布系统 | Agent 先完成可审阅演练包；涉及实际生产回滚及 Owner 本机操作需 Owner 明确执行/批准 |
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

1. **已交付批次**：#1339 路线、#1340 RDI 证据视图、#1341/#1335 依赖兼容、#1344 Overview 三重点及 #1345 A1 完整归档复查已落地。A1 实际缺口和后续产品缺陷继续按证据推进；后续状态见 §10。
2. **产品闭环批次**：重审 A1 已有真实收据；按 A3/#1315 的已观察缺陷逐项落地日期与 driver 语义、Decision Feed 最多三重点、正式证据支持/反证/下一步。每个小 PR 只关闭已验证子项，完整 fleet 保留。
3. **权限/恢复批次**：完成可无账号执行的 A4 清点和 A6 演练准备；将真实账号、生产治理、实际观察日及 Owner 操作准确交接。补齐证据后才提交 A7。
4. **RDI 研究批次**：取得 M3 选择后独立推进窄事件证书与 M4；不能以赶产品发布为由降低研究门禁。
5. **维护与后置功能**：#1335 依赖修复已合并并完成真实重放；#1315 其余 P1/P2 按用户价值完成；独立 Runner、研究→正式身份映射和 #1307 RFC 只有各自范围冻结/来源与权限成立后实施。后置研究不是正式产品 GO 的隐含前置条件。

每项使用已有 Issue/PR 和证据路径记账：实现 SHA、实际 cutoff、正负结果、未完成原因、下一动作。
能由 Agent 完成的代码、检查和诊断继续推进；需要真实时间或 Owner 输入的项目保持明确状态，
不重复创建路线、假账号或永久监控工作流，不把“全部未来功能做完”当作唯一发布终点。

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
