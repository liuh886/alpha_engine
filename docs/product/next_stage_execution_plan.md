# Alpha Engine — 下一阶段产品架构与执行计划

**状态：#1321 已合并，G0 分步实施中；A4 仍 FAIL。** 路线审查基线：`main@00dedccd76f3db4ea8091dc2321b89dfadf64089`，2026-10-29。本文是**当前下一阶段执行顺序的唯一入口**；旧的 [2026-10-26 路线图](investment_research_infrastructure_roadmap_2026-10-26.md)仅作历史决策记录，[研究问题库](future_research_agenda_2026-10-28.md)仅作备选议题，[#1315](https://github.com/liuh886/alpha_engine/pull/1315)是 UI 具体缺陷清单，[#1307](https://github.com/liuh886/alpha_engine/pull/1307)是独立 BDCR 研究 RFC。下列每项只有通过**独立实现 PR + 证据验收**才算完成；路线合并不批准产品 GO。

## 1. 产品判定：从建设功能切换到交付有用的研究判断

**唯一定位：一人使用的专业投资研究工作台（Investment Research Infrastructure）。** 工作台完成三件事：① 用历史时点可核实的数据**验证/证伪投资假设**；② 在相同样本、交易日、费用和基准下比较研究策略；③ 把变化、支持证据、反证、下一次复核步骤呈现给投资者。最终买卖与仓位决策由人完成。

用户完整旅程：**Today / Brief → 为什么关注（Evidence）→ 候选策略的相对表现（Racetrack）→ 人工判断 → 下一观察日复盘**。不是「新增模型 → 新页面 → 新数据库」，也不是自动生成买卖指令。**无新信号、证据不足、过期或受阻**都必须有诚实且有用的空状态。

最重要的产品问题：`/app` 中的「正式四策略观察」（可信运营事实）与「本地 Racetrack」（未经正式采信的研究比较）怎样相互辅助而**不混同其行动资格**。Brief 的前三条是**运营关注优先级**；Racetrack Top 10 是**指定市场/窗口内的研究收益排名**，两者不应该叫同一种“推荐榜”。

### 1.1 基于当前代码的交付状态（不等于完整产品已通过）

| 领域 | 已证实的实现 | 不得扩大解读 |
| --- | --- | --- |
| Formal Console | 四个正式策略的 Overview、Detail、Instrument、Status；#1317/#1318/#1320 纠正日期/权限过渡/历史窗口误导 | 局部 UI/CI 通过 ≠ A0–A7 产品上线验收 |
| Study Workspace | 四类研究入口：Walk-Forward、XGBoost、Factor、RDI；研究收据与比较接口已存在 | 历史 PIT 并未因此认证；RDI 的 predictive edge 没有成立 |
| Racetrack | #1306 P/Q/NAV、双基准、积分、发布；#1311 Lightweight Charts 主图/榜单/详情；#1314 US87 等权池实际 Runner、私有 Q、v2 时间窗口排名 | US87 Runner 与内部等权基准共用一个回放，不能充当**独立策略有效性**证据；没有六名合格选手 |
| 前端决策解释 | `DailyResearchBrief` 可排序状态；`StrategyDetailPage` 已展示失败门禁/反证/下一步 | [#1305 的实际实现 TODO](decision_feed_evidence_review_todo.md)仍未闭环；Brief 现在仍 `entries.map()` 列出全部四个而不是前三重点 |
| 发布与数据权限 | #1326/#1327 私有接线与正式运行收据已建立；本次切换停止活动账本的公开 Git/日志/producer 上传；本地 Racetrack 不向公共 Pages 发布 | `#1288` 虽 Closed，**A4 仍 FAIL**；Formal 跨 job 原始 artifact、旧密封/历史披露及实际权限负验证仍未关闭 |

### 1.2 现在的 P0 证据（2026-10-29 main；不摘录任何权重）

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
| **P0 / G0** | **当前操作状态的公开写入止血与重接线**：追踪 Git 最新树/历史、四个每日 writer、Formal lineage、Actions artifacts 和 Pages；先建立**受权限保护**的既有 Ledger 写入与 Strategy Operations 发布/读取端到端路径，再撤下公开 Git 新写入；清理当前树的敏感操作字段，封存已公开历史为残余风险记录 | 四面独立匿名负面验证（公开 Git 当前树、Pages、Actions artifacts、新写入流水线）+ entitled/denied/revoked 读测试；US/CN 正式信号仍按原调度生成、发布、投递，失败 fail closed；`A4` 依据新证据裁定，不按关闭 issue 推定 PASS | **必须先于新增对外可见研究数据、正式发布**；不重写密封历史、不创建第二真相库 |
| **P1 / U1** | **修正图表/收益的证据身份**：#1315 剩余 US x1.3 首行 opening wealth、模型/基准观测边界与汇总值差异，使用版本化 source projection；统一 date vocabulary 和 driver 语义；Status 去除重复和错误提示 | 真实来源数据下汇总、图表的起止日期/净值/收益/样本数可逐行核对；不存在把“待加载”说成“无权限”；桌面/平板/手机 + 完整测试回归 | 在 #1315 已完成 #1317/#1318/#1320 基础上继续；不能在前端硬塞 NAV=1、改写 sealed metric |
| **P1 / U2** | **完成 #1305 的 Decision Feed**：直接调整 `DailyResearchBrief.tsx`；首页只突出最多三项有意义的变化、风险、阻断，按时间和优先级说明 *why now*，保留原四策略完整 Fleet；无新变化给明确“无新动作” | 变化/无变化/过期/阻断/权限待定的读法清楚；每条带 cutoff、原因、下一动作，`/app → evidence` ≤2 点击；不增加新导航或信号计算 | 继续复用现有 `describeStrategyObservation` 和共享读器，不把研究收益榜和运营关注榜合并 |
| **P1 / U3** | **完成 Evidence Review**：`StrategyDetailPage.tsx` 用已有 `loadDecisionForRun` 分开列出支持证据、反证、解释局限、下一次允许验证；精确表明无绑定/过期/拒绝读取/等待审批 | 抽样一个支持、一个失败门禁、一个无有效证据情形；显示的结论、身份和日期与原 Bundle/Decision receipt 一致；不变成“买入/卖出建议” | 未有可审计映射时**不**自动接入研究 Runner，也不暴露本地未审查收据 |
| **P1 / R1** | **真实独立研究选手**：在同一 US87 轨道内选择**一个**不等于 US87 EW 的简单、事前冻结的基线策略（先查现有 Study Workspace/现成 Runner 能否复用），按现有 Q/NAV 引擎、公平窗口与成本实测；保留输给基准的情形 | 冻结 thesis/spec/候选池/再平衡规则/费用/训练与 OOS 边界；产生可重跑 Q + source/code SHA + 相同 sessions 的 NAV 与 QQQ、US87 对照；回放、局限和失败案例同版本可读；没有收益保证或自动升为正式策略 | US87 Phase A #1314 已完成。**不能**用原样不合规的 QQQR/US x1.3、随机伪信号或“回测胜者筛选”来凑选手 |
| **P2 / R2** | **CN 轨道的真实基线**：复用现有 CN/XSHG/CSI300 的 registry/scorer，接入 CN130 EW 池指数及 Q ledger，隔离标的、成本、停牌/上市前现金槽；再独立评审 BYD/CN27 改造的必要性 | CN130 与其内部基准完全对账；任意 US/CN 混跑 fail closed；CN 轨道至少可独立发布/阅读基准及其数据局限。正式派生 Runner 仅在版本化合同与 PIT/ETF/杠杆准入通过后登记 | 不是重新写 CN scorer；不能剪掉 515180 或超出股票池的持仓后沿用正式模型名 |
| **P2 / E1** | **建立最小研究成果复盘**：复用 Study 收据与赛季表现、固定的前瞻 shadow 观察窗口；按首次提出日期、证据 cutoff、复核日期记录当时的预测/否证条件和之后的观察结果 | 一份真实、可重放且不含私有账户信息的假设：从提出→冻结→OOS→前瞻观察→结论/否定；同时显示失败情况、多次尝试与窗口资格；不新建交易日记 DB | 先有 R1 和可靠证据；不能用一次回测替代 forward-walking 验收，也不能事后改阈值 |
| **后置 / R3** | **Bottom Detection (#1307)**：先解决 BDCR A–D owner 选择、corporate action/fundamental payload 与 as-of 证据，再通过现有执行器做一条研究-only state-machine；OOS、shadow 通过后才考虑是否成为 Runner | 时间因果、缺口/退市/停牌/冲突规则有负面测试；严格保留 `experiment_ready=false` 直到源与规则齐备 | **禁止**单因 RSI/形态感兴趣而提前上真实买点提醒 |
| **并行验收 / O1** | **Direction A A0–A7 产品/运营审查**：按实际可得的 US/CN eligible sessions、源数据完整性、权限、恢复/回滚、用户旅程累积证据 | 每个 gate 的 PASS/FAIL/BLOCKED/NOT_TESTED、日期、commit、Actions URL 与 Owner 裁定；真正 20-session 观察不足时继续 BLOCKED | 与研发持续并行；绿 CI、一次 Pages deploy 和新模型数量不等于 GO |

### 3.1 建议实现 PR 切片

1. **#A4-stop-bleed**：只处理 P0/G0，完成受保护数据写入和四面负面验收。不混入 Racetrack / 前端美化。
2. **#console-evidence-math**：#1315 剩余「源级 opening wealth / 观测窗口」与解释歧义。UI 其他视觉事项单独按屏拆分。
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

1. **515180 source contract — implementing.** Keep strict full-refresh Yahoo
   fallback admission. Only requested, already-authorized CN formal auxiliaries
   that actually select Yahoo obtain a complete requested-range source vintage;
   never merge a legacy seed into that full snapshot, drop prior observation
   dates, relabel an incremental fetch, or refresh the whole candidate pool.
2. **Real Formal private transport — NOT_TESTED.** After source recovery, obtain
   an eligible normal run with exact private archive and atomic fan-in receipts.
   Stop on data/transport failure; do not invent a strategy task to pass a gate.
3. **#1315 source consistency — pending.** Reconcile US x1.3 dates, opening NAV,
   observation counts and source identity; preserve source economics. Desktop,
   mobile, production build and deployed-SHA browser evidence remain required.
4. **A4 — FAIL.** Complete independently possible public-surface negatives and
   entitled/denied/revoked real reads using the existing access system. Missing
   real-session evidence stays explicit; fixtures/CI never substitute for it.
