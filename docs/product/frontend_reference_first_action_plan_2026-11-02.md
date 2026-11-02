# Alpha Engine 前端重设计：落地行动清单与 PR 切分

**日期：2026-11-02**  
**状态：PROPOSED，尚未获 Owner 设计定案**  
**对应设计 RFC**：[frontend_reference_first_redesign_rfc_2026-11-02.md](frontend_reference_first_redesign_rfc_2026-11-02.md)

> 本清单可直接交给 Agent 按序执行，但“建议实施”不等于已经授权修改生产代码。第一步是完成真实视觉/交互取证与 Owner 对齐；不要在没有选择的情况下擅自重写导航。执行采用 feature-first、少量可验收 PR、定点测试优先，避免为修 UI 建造新数据层。

## 1. 起点：已有内容不能重做

- 首要开发目录：qlib-dashboard/src/；React + Vite + Tailwind + Router + Radix UI。
- **lightweight-charts 5.2.1 已在 package.json，禁止重复发“安装 TradingView”任务。**
- 保留：StrategyFleet、DailyResearchBrief、现有 Evidence Review、StrategySignalDrawer、RDI 只读源、Racetrack 本地投影和哈希校验。
- 保留现有产品真假数据边界：History/formal bundles、Strategy Operations、RDI research-only、Racetrack localhost-only。
- 不复活已退役研究 IDE、不加下单/新 API/新定时任务/新数据库。
- 既有 next_stage_execution_plan.md 继续作为当前正式发布工作排序唯一权威；**本 PR 为待 Owner 选择的前端设计计划，不偷换 A0–A7 发布判定**。定案后将获准的项目同步到该文件，并标注新的实现 PR。

## 2. 实施路线 / Dependency graph

~~~text
UX0 真实界面审计 + 参考产品拆解 + 三套设计原型 + Owner 选择
  ↓
UX1 Foundation：通用状态/日期/布局组件与页面级层次
  ├── UX2 Today：三条重点 + 四策略对比 + 下一步
  ├── UX3 TradingView POC：证券 OHLCV / markers / 表格替代
  └── UX4 Strategy Detail：Performance + Risk + Decisions + Evidence
       ↓
UX5 Research Lab：Racetrack + RDI 的清晰独立研究入口
       ↓
UX6 System：只保留运行健康/恢复，研究内容去重
       ↓
UX7 导航切换/公开 Pages 验收/Owner sign-off
~~~

依赖原则：UX2、UX3 可在 UX1 稳定后并行；UX5 可先验证静态 IA，无须等待赛马引擎新增 Runner；UX6 的 RDI 迁移以 UX5 具有可用入口为前提。任何 POC 没有通过真实交互验收都不允许一次性全站替换。

## 3. 分 PR 执行清单

### UX0 / P0 · 基线审计 + 可点击原型 + Owner 决策（设计，不改运行逻辑）

**Owner**：产品设计师 + Owner + 前端 Agent。  
**目标**：用户亲眼看到差异并判断产品想呈现什么；杜绝仅靠术语推导页面架构。

- [ ] 对部署版 GitHub Pages 实拍并保存 desktop 1440px、tablet 768px、mobile 375px 的 /app、/system、两个策略详情、证券详情；针对未登录/未获取授权的真实会话保留截图，不进入私有账户。
- [ ] 本地运行并截图 Racetrack US/CN（如缺合格本地数据，明确 unavailable，不造真实赛况）。
- [ ] 将 FreqUI 的图表/筛选/历史复盘、OpenTerminal 的键盘导航/模块布局、TradingAgents 的分析结论/证据组织拆成每个不超过一屏的参考交互卡；每张卡明确“借鉴流程”而非复制版权代码。
- [ ] Product Design Work 模式：同一数据/同一信息密度下输出 A Decision-first、B Research Terminal、C Racetrack-first **三套可视方案**；展示桌面与移动布局，默认采用 A 的导航语义，其余为工作视图备选。
- [ ] 走查任务脚本：看到最近变化→证据→策略基准→证券历史信号→研究不足→异常恢复。
- [ ] Owner 选择首页、导航方式、Research hosted/local 公共边界、第一批图表迁移范围；记录被否决方向。
- [ ] 形成 1 页设计决策记录（ADR）和 Design Tokens baseline（间距、字体层级、色彩角色、状态文案），附截图，不能以 CSS 重画替代用户评审。

**验收**：能够以截图/原型在 30 秒内讲明“首页展示什么、为何如此、点击后到哪里”；六项 Owner 决策有具体记录；未碰运行时代码。  
**不能声称**：未实际打开浏览器、未生成截图时说“已完成视觉审计”。

### UX1 / P0 · 页面骨架与复用组件收敛

**目标**：全站同一可复用的标题/证据日期/空状态/异常状态/导航层级，不改数据真相。  
**候选路径**：src/App.tsx、routes.ts、Sidebar.tsx、ResearchContextBar.tsx、index.css、components/ui/。

- [ ] 基于 UX0 的 Owner 选择制作新的站点框架，先可从 /app?layout=next 或明确的 feature flag 进入；旧 /app 和 /system 不受影响。
- [ ] 在 System/Research 页隐藏不相干的 Selected Evidence / strategy context；若显示“当前选中策略”，必须与 URL 和实际数据绑定。
- [ ] 统一各层页面 header、二级导航、breadcrumb 和“Research only”提示位置；不要重复顶部/标题/上下文条。
- [ ] 提炼 EvidenceTime（as-of/observed/target/formal/backtest/provisional）、ViewState（loading/unavailable/restricted/stale/retained）等**展示组件**，但禁止生成新的状态判断权威。
- [ ] 抽取 panel、drawer、tabs 的可访问样式变量；优先复用 Radix，不引入新 UI 生态。
- [ ] 对 375/768/1440px 复查侧边栏滚动、drawer 遮挡、表格溢出和焦点恢复。

**验收**：新/旧可切换，旧路由深链接无回归；系统状态不出现错误的策略上下文；一条成熟的样例用户路径（Today→Strategy Detail）可点击。  
**最小检查**：lint/typecheck、受影响的组件单测、两条静态 Playwright 旅程；正式切换时额外跑全流程。

### UX2 / P0 · Today — 真正有用的每日决策摘要

**目标**：回答“有什么变化、为什么、看哪里、下一次什么时候”。  
**候选路径**：StrategyOverviewPage.tsx、DailyResearchBrief.tsx、StrategyFleet.tsx、StrategySignalDrawer.tsx、ResearchContextBar.tsx。

- [ ] 首页第一屏：US/CN 数据状态和各自截止日、最多 3 个事项、查看证据 CTA、四策略紧凑摘要。不要用同一个“today”代表不同市场交易日。
- [ ] 四策略初始顺序有明确规则：重点按状态排序，完整 Fleet 按稳定身份排序，两者关系用文案解释。
- [ ] 对可用的同窗业绩展示策略/基准/最大回撤；不可比或被拒绝时显示原因，不把缺值渲染为 0%。
- [ ] 一键从事项进入对应策略 Evidence Review，保留策略/截日/来源身份。
- [ ] 重新定义“无变化”提示：仅在四策略观察状态均可核实，且适用交易节奏内才显示；保留 retained/not-due 的真实语义。
- [ ] 移动端保留单列关键信息，密表移到下级页。

**验收**：用户两次点击以内找到一个当前事项的证据与下一次允许动作；无变化、失败、受限、stale 都有人工可读信息；日期可对应原始证据。

### UX3 / P0 · TradingView Lightweight Charts 证券图 POC（功能突破点）

**目标**：直接获得成熟金融图表交互，而不是自己开发画 K 线的几何逻辑。  
**候选路径**：SecurityHistoryChart.tsx、SecurityDetailPage.tsx，新增可复用 src/components/charts/FinancialPriceChart.tsx 及 src/lib/chart-adapters/*（具体命名以代码风格确定）。

- [ ] 验证现有 lightweight-charts v5.2.1 用法、官方时间坐标/series marker/primitive API 和版权 attribution；做技术 Spike，不盲目升级。
- [ ] 建立**纯展示适配器**：验证过的 SecurityBar → time/OHLCV candles + volume；不能偷偷向第三方请求行情。
- [ ] 复用既有 securityMarkers() 对同日多策略事件归组；Series Marker 或自定义 primitive 展示 B/S 与详细 drawer，标记文案明确为“历史模型事件”。
- [ ] 移动端 pinching/tap、十字光标、图例、区间按钮、自定义日期、价格 scale、dark/light 模式。
- [ ] 键盘事件列表与表格替代；如果 Canvas 无法对单标记提供完整键盘交互，则旁边展示可聚焦、可点击的事件表。
- [ ] 处理长历史（性能）、断档、非交易日、错误/零成交量、复权/非复权、市场时区、重复日期、来源截日。
- [ ] 新旧图在同一证据数据集上做 side-by-side；确认事件数、事件日期、OHLC 逐点一致；未达标则保留旧图。
- [ ] 维护 Attribution NOTICE 与 TradingView 链接；新增组件需写明确“图表来自已有正式数据，不含实时行情”。

**验收**：金融图操作手感明显改善；不得更改证据时间、事件归属、价格值；desktop/mobile 交互成功；选取日期与下方明细表对齐。  
**关键反例**：不允许把用户策略信号当做实际成交点，也不许将免费 TradingView widget 替代正式价格源。

### UX4 / P1 · Strategy Detail 面向研究判断的重组

**候选路径**：StrategyDetailPage.tsx、PerformanceCharts.tsx、ResearchTrackingAssessment.tsx、PositionsTable.tsx、AttributionInterpretation.tsx。

- [ ] Strategy Overview / Performance / Risk / Decisions / Evidence 以固定二级导航呈现；右上保留来源/截止日期可访问入口。
- [ ] Performance 主面板优先策略与声明基准，Risk 次面板展示回撤与周期；一处时间窗口控制全部关联数字和图表。
- [ ] Evidence 先人类可读结论，再支持证据、反证、解释局限、下一研究步骤；来源哈希和 debug 原始字段收折叠层。
- [ ] 持仓、目标、历史模型事件按相同身份与权限显示；无权限下不得用历史公开持仓兜底。
- [ ] 检查是否需要把 Recharts NAV 换为 Lightweight；**只有用户体验、性能、时间轴同步有实证改善才迁移**，不为“全面 TradingView 化”改写既有曲线算法。
- [ ] 复核全/短窗口、opening wealth、稀疏结算、provisional MTM、经济超额收益的准确度。

**验收**：策略变化可复盘；图表和数字符合 chart_quality.md；用户明确知道何时不能得出交易结论。

### UX5 / P1 · Research Lab / Racetrack + RDI 融合到正确的信息领域

**候选路径**：StrategyOverviewPage.tsx（Research tab）、RacetrackWorkspace.tsx、RdiResearchStatus.tsx、RdiHistoricalComparison.tsx、RdiEvidenceSources.tsx；新的 research 概览页（如 Owner 批准）。

- [ ] 在 Research Lab 中单独介绍独立 Runner、正式策略、指数基准三者区别；避免“相同市场即相同可比性”。
- [ ] 按市场/窗口/Runner 保留 URL 状态；NAV、Top10、详情协同突出可解释性。
- [ ] Hosted Racetrack 不显示重复 Retry 或伪按钮；说明 local-only 证据边界并给明确运行指引，保留公开正式策略入口。
- [ ] RDI 以“研究问题+历史已知现象+未验证内容”开始；PIT 认证/证据来源保持可查但放在第二层。
- [ ] 明确 Risk price-only historical association **不等于** 7/14/28 日的校准预测；仍显示 not validated、历史 cutoffs、样本数量和 limitations。
- [ ] 对研究卡片增加可用性标签（published/local only/unvalidated/blocked），但不是硬编码、不是新验证算法。
- [ ] 不公开本地研究 Q、未审查原始收据、不恢复浏览器上执行研究的按钮。

**验收**：首次使用者能说出 Racetrack、RDI、正式策略各解决什么问题，及为什么结果不可等同交易信号；当地/托管两种环境有清晰合法的降级体验。

### UX6 / P1 · System 页面去重和运维任务化

**候选路径**：SystemHubPage.tsx、OperationsReadStatus.tsx、RdiResearchStatus.tsx。

- [ ] System 主页面只放运行数据/策略 reader/交付/恢复；将 RDI 研究正文迁到 Research Lab，但保留合法的研究健康入口链接。
- [ ] 优先异常清单：来源、受影响市场/策略、last good read、错误原因、恢复现有 workflow。
- [ ] 统一刷新文案，清晰区分“网页重新读取”、“执行既有 workflow”、“数据实际上更新”。
- [ ] 成功/失败/受限/过期/部分恢复/多策略独立运行均按真实来源输出。
- [ ] 对无授权用户隐藏不可见敏感详情，仍允许读合法公开系统概况。

**验收**：用户进入 /system 后第一屏能识别受影响的系统职责而非阅读长篇 RDI 研究；从一个异常定位修复入口不超过两步；没有重复策略 Brief。

### UX7 / P2 · 统一导航、视觉质量、发布验收和回退

**目标**：在真实交互验证后逐步切到 Owner 认可的 IA，且不阻断现有运行发布。

- [ ] 依据 UX0 的正式设计决策决定是否新增 /research 主路由、/strategies 列表页；未批准则维持原路由以内页 tab 组织。
- [ ] 更新 docs/product/strategy_console.md、AGENTS.md 相关权威边界（仅获批路由），再同步 docs/product/next_stage_execution_plan.md 的前端队列；勿另造同级路线。
- [ ] 使用 Browser/Playwright 记录 375/768/1440、light/dark、键盘、键盘焦点、实际 Pages 发布 SHA 和实际链接。
- [ ] 核对公开静态资源与 Supabase RLS/current-data 权限界限；运行前述重要负例。无真实测试账号，NOT_TESTED 如实留门禁。
- [ ] 端到端完成 Today→Strategy→Evidence→Instrument→Research→System 的路径且不存在失效链接。
- [ ] 生产发布、回退试运行和 Owner 签批遵守既有产品 A0–A7 流程；设计上线路径不等于产品 GO。

**验收**：可部署版本的真实用户旅程通过；发布记真实 SHA；Owner 明确签收。没签前可回退至旧布局。

## 4. 实施优先级与不可阻断项

| 优先级 | 内容 | 什么才算完成 |
| --- | --- | --- |
| **P0** | UX0 设计对齐、UX1 骨架、UX2 Today、UX3 TradingView K 线 POC | Owner 选中方案 + 可视化与操作证据；首要主任务完整 |
| **P1** | UX4 Strategy、UX5 Research、UX6 System | 完整研究→策略→证据理解路径；托管与本地语义清楚 |
| **P2** | UX7 导航收口、完善可访问性、真实发布验收 | 不打断既有发布流程；Owner 验收 |
| **P3 可选** | Cmd+K、Watchlist、可重排多窗、Perspective 大表 | 仅真实使用频繁且数据权限/可维护性成立时单独讨论 |

**独立并行**：已有 A1 运行观察、策略数据/身份权限与 RDI 事件验证不因 UX 改造停止；反过来 RDI 未验证也不阻止纯 UI/已认证四策略页面改善。

## 5. 最小 PR 交付标准（不要每小步全量测试）

每个实施 PR 的描述统一回答：

1. **用户功能变化**：用户以前做不到什么，现在能够做什么？附旧/新截图与一次完整操作演示。
2. **重用说明**：复用了上游哪个设计模式、使用了本仓库什么既有组件？为何新增依赖不可避免？许可证与 attribution 核对情况。
3. **数据不变量**：来源、时间、策略身份、权限、research-only 状态是否保持？
4. **验收范围**：目标组件 unit/交互、单条 desktop 和 375px mobile Playwright、必要的证据数值断言；涉及权限/发布时再跑相应扩展。
5. **部署与回退**：旧功能保留还是 feature flag；有无法验证的真实用户会话就写 NOT_TESTED，不能用 synthetic 顶替。
6. **任务状态**：PASS / FAIL / BLOCKED / NOT_TESTED，每项有 SHA 和证据链接。即使别处大量 tests 通过，也不能当作这个页面被真实使用者认可。

## 6. Owner 会议需要看的 6 张图

- 图 1：Today 首页：现有 vs 推荐（首屏 1 屏）
- 图 2：Strategy Detail：NAV 对基准 + 风险面板 + Evidence Review
- 图 3：证券详情：现有 Recharts vs TradingView Lightweight Charts 可交互 K 线
- 图 4：Research Lab：Racetrack 赛季 + Runner 详情
- 图 5：RDI：研究结论/解释/局限的渐进披露
- 图 6：System：技术状态/故障归因/恢复入口

每张图都需要：**一个任务陈述、明确交互路径、所需数据身份、desktop/mobile 状态、外部参考链接**。视觉原型由设计工具产出；没有截图不称完成。

## 7. 禁止造成“架构漂移”的触发条件

- UI 提案引入新数据事实存储、浏览器策略计算、下单连接：**立即拆离本 UX 计划**。
- 新第三方依赖比现成 Radix/Tailwind/Lightweight Charts 能力更弱：不引入。
- 为展示漂亮成绩而隐去 sample/成本/下跌/期间不足：拒绝。
- 默认 Research 页面托管时没有数据，仍将其当作正式可用产品：调整导航/入口或合法降级。
- “已经有两个菜单”成为阻止用户任务分组的唯一理由：返回 UX0 重新决策。
- 单个 PR 横跨图表数据口径 + AccessPolicy + 页面重设计：拆分，避免无法定位问题。
- 功能开发被大量非相关防御性测试堵塞：只保留必要 targeted tests，重要切换/发布时再扩回归。

## 8. 设计冻结后第一批可以立刻执行的 issue/PR 说明

**第一批**：UX1（layout/context 的可感知修复） + UX3（TradingView 图表可交互 POC）。理由：前者解除目前 /system 上下文错位；后者用户价值高而可隔离测试。UX2 Today 可随后或并行落地，但与新 IA 定案保持一致。

**不在第一批**：TradingAgents API 接入、自动交易、公开本地赛马私有资产、研究框架扩容、整站 Recharts 移除、重新建立市场行情服务。

**Owner 审核结论模板**：
- D1 默认 A/B/C：
- D2 导航（保持 2 入口 / 试验 3 任务+System / 直接换）：
- D3 Racetrack（继续仅本地 / 未来批准脱敏摘要）：
- D4 TradingView（证券优先 / 同时 NAV 试验）：
- D5 语言与设计风格：
- D6 原型验证方式与签收人：

记录以上决定后，才把本 TODO 的 PROPOSED 改为 APPROVED，后续 Agent 逐个 PR 实施。
