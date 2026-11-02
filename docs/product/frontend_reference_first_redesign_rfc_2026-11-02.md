# Alpha Engine 前端重设计：Reference-first 产品体验与交互架构 RFC

**提出日期：2026-11-02**  
**状态：D1 APPROVED（2026-11-02）；本 PR 已开始代码架构落地，其他设计细节和验收未完成。**  
**范围：Alpha Engine Strategy Console + local Racetrack 的信息架构、交互模型、组件复用、TradingView 图表迁移评估。**  
**权限边界：不得因本 RFC 修改研究事实、受保护信号公开范围、交易执行权限或既有数据权威。**

> 原则：不重新发明轮子；先研究成熟开源产品的任务流和组件，再用现有 React 栈建立适合单人研究者的体验。功能有效性优先，避免以防御性抽象和大规模回归替代产品进步。

## 0. 决策摘要

1. 不复制某个 Trading Agent 的完整代码或交易架构。对标分两层：**可借鉴的 UX 模式**与**可合法直接使用的组件**。
2. 主产品仍是个人、研究优先、只读的 Investment Research Workspace；不把研究结果伪装为实际订单/账户持仓/实时价格。
3. 产品按 **Today → Strategy → Evidence → Next** 组织日常工作流；独立研究归 Research Lab，系统运行与恢复归 System。导航变更先过设计验收再实施，不恢复已退役的浏览器研究 IDE。
4. TradingView **Lightweight Charts 5.2.1 已安装**（qlib-dashboard/package.json），不能开一个“再引入 TradingView”的重复任务。优先在证券详情实现通用 FinancialChart adapter 的 POC；策略 NAV / 回撤按适配性逐个迁移，保留合适的 Recharts 图表。
5. 先给 Owner 三套参考布局和一个可点击的视觉原型进行选择，再做实施 PR。本文描述默认推荐方向，但不以文档合并代表设计已获准。
6. 复用现有 Vite/React19/Router/Tailwind/Radix/Zustand/Lucide、TanStack Virtual 和已部署 reader；不引入新的服务、交易引擎或数据层。

## 1. 源码核对：现在究竟是什么

以 2026-11-02 检查 main 的以下文件为审计输入（PR 创建前的活跃实现）：

- qlib-dashboard/src/App.tsx、routes.ts、components/Sidebar.tsx、ResearchContextBar.tsx
- pages/StrategyOverviewPage.tsx、StrategyDetailPage.tsx、SecurityDetailPage.tsx、SystemHubPage.tsx
- components/DailyResearchBrief.tsx、StrategyFleet.tsx、PerformanceCharts.tsx、SecurityHistoryChart.tsx
- components/RdiResearchStatus.tsx、RdiHistoricalComparison.tsx、RdiEvidenceSources.tsx
- components/racetrack/RacetrackWorkspace.tsx
- qlib-dashboard/package.json；docs/product/strategy_console.md、chart_quality.md、next_stage_execution_plan.md

### 已存在，必须优先复用

| 资产 | 现状 | 重设计处理 |
| --- | --- | --- |
| React Router HashRouter | /app、/system、/strategies/:strategyId、/securities/:market/:symbol | 保留深链接与 hash 路由；新 IA 增加入口必须有旧路由兼容 |
| DailyResearchBrief | 已有按变化/关注/保持排序的三条重点 | 保留计算和 reader，重做信息层级与语义，不重复状态判断 |
| StrategyFleet + StrategySignalDrawer | 市场/状态/时段筛选、正式策略对比、当前信号详情 | 保留，优化卡片、表格密度和移动端 |
| Strategy Detail + Evidence Review | 策略绩效、基准、风险、支持/反证/限制/下一步 | 保留证据合同，以任务型子导航重新组织 |
| SecurityHistoryChart | Recharts 自绘蜡烛和历史信号标记 | TradingView Lightweight Charts 的第一优先 POC |
| PerformanceCharts | Recharts 多面板业绩、基准、窗口/回撤 | 先保持精确指标与窗口口径，视 POC 决定是否部分迁移 |
| RacetrackWorkspace | localhost-only 赛马曲线/Top10/Runner 对话框 | 强化产品可发现性和 local-only 状态表达；不公开私有研究 |
| RDIResearchStatus | /system 下研究内容与证据来源混合 | 信息架构迁移至研究领域，但原验证状态/数据截止不变 |
| Radix Dialog/Tabs、shadcn 风格 ui | 已有基础可访问组件 | 原位复用，统一设计 tokens 与交互状态 |
| lightweight-charts 5.2.1 | **已经是项目直接依赖** | 复用，不重复安装；确认实际复用入口与语义约束 |

### 当前结构性体验缺口（源码支持，真实视觉待截图复核）

- /system 既承载运行状态，又承载 RDI 历史研究；主任务不清。
- Overview 把正式监控与 localhost-only Racetrack 放在同级模式，但未充分解释身份与可用性差异。
- Sidebar 的 Selected evidence 与全局 ResearchContextBar 在非策略页仍出现，造成关联错觉。
- 证据日期/哈希/来源/阻断是专业刚需，但不能替代“发现了什么、为何重要、下一步”的阅读顺序。
- 多项历史 PR 是小范围 polish 或修复；缺少一次跨 Today/Strategy/Research/System 的**共同产品概念和设计系统**。
- 以上为信息架构与源码审计，不把无法在本对话实际浏览器截图验证的视觉猜测宣称为已复现 UI 缺陷。

## 2. 外部项目对标：看什么，不看什么

所有链接为 2026-11-02 调研所用上游链接。借鉴理念不等于允许直接复制组件；实施前锁定依赖版本和 LICENSE。

| 参考 | 证实的形态 | 值得学习 | 不照搬 |
| --- | --- | --- | --- |
| [Freqtrade / FreqUI](https://github.com/freqtrade/frequi)；[官方 UX 文档](https://docs.freqtrade.io/en/latest/freq-ui/) | 完整的交易 bot 监控/图表/回测 Web UI；前端 Vue/PrimeVue，GPL-3.0 | 监控→图表→历史/日志的上下文切换、可配置图表、回测筛选、列表-详情联动 | 不引入 bot 开关、下单与账户 API；**GPL 代码不可不经兼容性审查直接搬入本产品** |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 研究 Agent / CLI / HTML 报告为核心，不是成熟完整交易桌面网页 | 分析员—研究经理—风险辩论—结论的分层解释，结论/分歧/证据的阅读节奏 | 不以高 star 数误判 UI 完整，不复制 LLM 推理架构或让 Agent 直接发布信号 |
| [OpenTerminal](https://github.com/ErTasselli/OpenTerminal)（仓库主体与 Fork 需具体审查） | 可定制金融终端，命令搜索、图表、看板，React 系 | 组件化 workspace、Cmd+K、股票跳转、观察清单、键盘交互 | 不照搬实时 ticker、交易盘口、密集动态面板；许可证/数据源合规单独审计 |
| [QuantDesk frontend-trading-dashboard](https://github.com/maddoxk/frontend-trading-dashboard) | React/Vite/TS + Lightweight Charts 的模拟数据前端 | GitHub Pages + 图表、watchlist / pane 布局、响应式组件代码组织 | 全部价格是模拟的，不得作为金融正确性/研究证据参考 |
| [Hummingbot Dashboard](https://github.com/hummingbot/dashboard) | Streamlit 多机器人部署/回测 UI，官方文档标记不再积极维护 | “策略创建→回测→部署→监控”的任务阶段概念 | 不复制 Streamlit 架构、不引入部署/实盘操作，不作为首选新前端基础 |
| [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) | Apache-2.0 开源金融图表，已有依赖 | K 线、时间轴缩放、十字光标、价格线、标记、自定义 primitive | 不把它当作附带市场数据、指标计算、完整绘图工具条的 TradingView 网页 |
| [TanStack Table](https://tanstack.com/table/latest) + [shadcn data table](https://ui.shadcn.com/docs/components/base/data-table) | headless 表格交互 | 排序、筛选、列选择、表格虚拟化与可访问性 | 四策略列表不需要沉重 DataGrid；只有密表确有必要才增加依赖 |
| [Perspective](https://github.com/perspective-dev/perspective) | Apache-2.0 高性能数据透视/可视化 | 大规模研究实验表的可扩展路径 | 非 MVP，不为“未来可能的大数据”提前引入 WASM |

**评分**：不是按 star 排，而是分别评估用户任务贴合度、交互质量、React 适配、开源许可证、数据语义、维护成本。FreqUI 优先学交互逻辑；TradingView 优先复用代码；OpenTerminal 优先学布局；TradingAgents 优先学研究解释。

## 3. 产品用户与 Job-to-be-done

**核心用户**：单一研究者/操作者，观察美股/A股正式策略，复盘风险、验证研究假设，最终由人自行交易决策。

优先问题：

- 每天打开站点 10 秒内识别：数据截止到何时、四策略哪项有变化、哪项阻断、下一步何时评估。
- 进入任一策略：看与**声明基准、相同实际窗口**的绩效；看回撤、仓位/目标差异、变化来源、反证与失败条件。
- 选择证券：金融级 K 线图（OHLCV、成交量、事件标记、区间选择），点事件就解释历史模型行为。
- 进入研究：清楚区分正式策略、独立 Runner、未验证 RDI；查询研究问题、证据、资格、对照结果，而不是看到研究门禁就以为“系统故障”。
- 出现异常：状态页定位受影响的工作流、最近一条有效记录、真实截止日和恢复操作；不执行交易。
- 浏览器托管模式不可访问 localhost-only 内容时，应明确说明，并提供本地打开操作指引；不能伪造数据。

**明确不做**：自动/手动交易下单、重建交易终端、匿名展示私有 Q/持仓、自动预测/AI 买卖建议、重建已退役的浏览器 research IDE、新数据计算权威。

## 4. 推荐信息架构（IA；Owner 待确认）

首选布局（与旧路由保持兼容，是否开放新一级菜单另做决定）：

~~~text
Alpha Engine / Investment Research Workspace
├─ Today             [默认入口；原 /app 的决策摘要]
│  ├─ Market & source cutoff (按 US/CN 各自实际时间)
│  ├─ Today matters (最多 3 个变化/关注/阻断)
│  ├─ Four formal strategies (紧凑对比卡 + 小型业绩趋势)
│  └─ Next reviews / evidence freshness
├─ Strategies        [可在 Today 下以 tab 先上线]
│  ├─ Formal fleet / filter / compare
│  ├─ Strategy detail: Overview | Performance | Risk | Decisions | Evidence
│  └─ Instrument detail: price/OHLCV | historical events | evidence
├─ Research Lab      [独立研究, 未认证不可被称作当前信号]
│  ├─ Racetrack: US/CN | season/window | NAV | Top10 | Runner details
│  ├─ Risk research: RDI price-only observations, availability, source details
│  └─ Research status: published/local-only/unvalidated/blocked
└─ System            [次要入口；无研究结果本体]
   ├─ Published source snapshots and cutoffs
   ├─ Strategy decision/delivery reader health
   └─ Diagnostics / recovery / workflow links
~~~

**过渡方案**：第一批可保持 /app 和 /system 两个导航，通过内页 Today/Strategies/Research 标签、有效深链接试验；只有两轮 UAT 证明价值后才批准新增 /research 或 /strategies 主路由。拒绝以“历史两菜单”为绝对约束，也拒绝没做用户验证就扩菜单。

**Research hosted/local 边界**：托管页的 Research 允许说明研究对象和可公开的经过审核的摘要；现有 localhost-only Racetrack 数据不应自动发布到 GitHub Pages。是否允许发布经过脱敏的 Runner 结果，必须另行取得 Owner 决定和数据审查。

## 5. 关键页面内容合同与交互蓝图

### 5.1 Today / 工作台

读取顺序：**一句状态摘要 → 变化列表 → 四策略横向比较 → 下一步 → 来源/权限状态**。

- 顶部只展示与任务相关的日期：US/CN 最后完成交易日、当前正式决策时间、历史证据截止日；三者绝不合并成一个“最新”。
- 最多三条重点，每条有策略身份、变化类别、日期、一句话解释、查看证据的链接。
- 四策略卡片显示：策略名、正式资格、当前状态、给定窗口的真实收益/基准/最大回撤（数据缺失则 N/A + 原因）、下一观察时间。不要出现账户 P&L，除非权威账户来源存在并授权。
- 点击策略卡片打开同一 Strategy Detail；点击原因展开 Evidence Review；相同实体从 Today/Strategies/状态跳转保持参数。
- 状态刷新仅重读，不触发运行任务；明确上次已验证数据与重读失败态。
- 只在“确实有数据且同窗口”时画小图；无数据不给虚构 sparkline。

### 5.2 Strategy Detail / 研究证据链

固定头部：策略身份、适用市场、策略版本、as-of 与公开/受限状态。

子区：Overview（结论、变更、下一步） → Performance（NAV 对基准） → Risk（drawdown + exposure） → Decisions（历史变更/目标） → Evidence（支持、反证、局限、协议/哈希）。

- 图表与数字切换 1M/3M/6M/1Y/All 时必须共用准确日期窗口；标签明确“实际可用 26 日”，不冒充完整一年。
- 策略 NAV 和真实声明基准同坐标比较；缺原始前值不得自行造零起点；历史/prospective/provisional 用显式区分。
- “支持”只意味着符合某验证门禁，不表示买入建议；“neutral”不表示无风险。
- Evidence 从可读人话摘要开始，原始 Gate/receipt/hash 在二层按需展开。
- 当前持仓/目标权重保持严格由授权的 Strategy Operations reader 提供，不从公开历史回测推算。

### 5.3 Instrument Detail / TradingView POC 的主战场

- **主图**：Lightweight Charts Candlestick + 可选均线或模型观测 overlay（仅真实存在并审定的系列）；**副图**：成交量；可选已验证的指标面板。
- 右上时间段：1M/3M/6M/1Y/All + 自定义日期；保证样本窗口与数据 cutoff；缩放/十字光标/触摸交互跟随金融图表习惯。
- 历史 BUY/SELL/INCREASE/REDUCE 作为**模型历史事件**标签，不是账户成交标记；一日期多事件聚合，点击打开解释 drawer，含策略、事件时间、证据来源与适用边界。
- Hover 与键盘导航、触屏点按都能获取 OHLCV / 当期事件；永远有文本表格作为图表不可访问时的替代。
- 无缺口插值、无非交易日补 K 线、无造假前复权、无虚构价格源；市价、调整价、币种和市场时区需来自可信 schema。
- 如果 Lightweight Charts 的 marker 插件/primitive 无法达到键盘可访问性，保留事件列表可访问入口，POC 不强行上线。
- 第一 PR 只做证券图表适配，不同时重写绩效图和 RDI。

### 5.4 Research Lab / 赛马场与 RDI

- 核心语义分组：**正式策略**与**独立实验 Runner**绝不可同名、同色、同资格。
- Racetrack 中 NAV、基准、Top10、窗口切换、Runner 详情，沿用已有原始研究投影；清楚解释窗口是否完整、共同起点、成本和累计积分的定义。
- RDI 展示顺序：研究问题 → 已证实的价格层描述性观察 → 尚未验证内容 → 来源覆盖/可复现入口。不可发布无资格风险概率、Composite Score 或实际警报。
- 首页用状态分类表达：已发表证据 / 仅本地可用 / 未认证 / 来源阻断；Research unavailable 不等于 System unavailable。
- **Hosted**：赛马场卡片解释仅 localhost 可读，并给 local runbook；**Local**：按原始 manifest/hash 读取，禁止浏览器生成研究输出。
- 技术细节（事件家族认证、PIT、模型 ID、source hash）应可查，但默认折叠而非抢占阅读首屏。

### 5.5 System / 操作维护

- 定义“正常/异常”的对象必须明确到来源、运营 reader、投递工作流和时间；不能一个总绿灯掩盖单策略阻断。
- 应有影响范围、上次有效日期、错误原因、现有恢复动作；若无法从来源获知，显示 Unknown，不猜测。
- 从 System 移走 RDI 历史研究展示主体，仅保留“研究源数据是否可用”的链接/状态。
- 不把页面级 Refresh 描述成执行任务；外部 workflow 链接明确需授权。

## 6. 交互设计系统：复用优先

| 模式 | 期望交互 | 当前资产 / 复用策略 |
| --- | --- | --- |
| 分层导航 | Today/Strategy/Research/System 清晰分类，带路由恢复 | React Router + 现有 Sidebar/MobileTabBar；先 IA POC |
| 全局跳转 | 可选 Cmd/Ctrl+K 搜索策略/已知标的（仅白名单 evidence index） | 初期低优先；先检索成熟命令面板组件，勿新造搜索后端 |
| 图表 | crosshair、zoom、pan、ohlcv、event drilldown | **已安装 lightweight-charts 5.2.1**，写薄适配器和事件列表 |
| 表格 | 排序/筛选/列可见、保留窗口 | 小表继续现有表格；大数据候选 TanStack Table；已用 TanStack Virtual |
| Drawer/dialog | 查看原因/事件后返回上下文，ESC/焦点恢复 | Radix Dialog、现有 SignalDrawer/RunnerDetail |
| 时间控制 | 一处切换同步影响主图、数字、回撤、基准 | 复用性能窗选择/日期 snap 语义；共享 display state 非新计算引擎 |
| 状态组件 | Valid/Retained/Stale/Unavailable/Restricted/Research only | 收敛文案和显示层样式，不能把语义状态折叠成颜色 |
| 证据详情 | 摘要 → 反证/局限 → 原始数据/来源 | 复用 Evidence Review/现有 details；渐进披露 |
| 主题与移动端 | 护眼深浅色、断点、触摸目标、图表替代文本 | 现有 Tailwind/CSS 变量 + Radix + Lucide |

**切忌**：大块“金融深色玻璃拟态”装饰、虚假的闪烁行情、过多状态徽章、五颜六色赢家排行榜、未经资格审核的量化评分、全部组件重写。

## 7. TradingView 产品与许可决策

| 产品 | 授权 | Alpha Engine 的结论 |
| --- | --- | --- |
| **Lightweight Charts** | Apache-2.0；必须遵守 NOTICE 与 TradingView attribution/link 要求 | **首选，已安装**；由 app 自行提供静态/经授权读出的数据；无内建行情和完整指标库 |
| **Advanced Charts** | 专有许可/申请，官方不提供给一般个人 hobby/test；API 不兼容 Lightweight | 目前不选；除非明确商业资格和授权后再评估 |
| **Trading Platform Library** | 专有、面向经纪商的交易集成 | 不选，超出 research-only 范围 |
| **TradingView embeddable widget** | 第三方托管数据/既定控件 | 可做外部行情参考链接，但不能承载正式证据；价格源、授权、广告/显示边界另审 |

官方对比：https://www.tradingview.com/free-charting-libraries/  
官方产品说明：https://tradingview.github.io/lightweight-charts/docs/product-comparison  
NOTICE：https://github.com/tradingview/lightweight-charts/blob/master/NOTICE

选型补充：FreqUI 是 GPL-3.0，**借鉴交互思路与屏幕布局模式**不同于直接复制源代码或图形素材。第三方设计模仿不意味着自动获得商标/素材的使用权。依赖增加之前核对 LICENSE、维护情况、bundle budget 和漏洞情况。

## 8. UI 改造必须服从证据与安全合同

1. 不修改 formal strategies、Decision Ledger、source-of-truth 的归属；不暗中扩访问权限。
2. 策略历史公开证据 ≠ 当前授权信号 ≠ 本地研究投影；本次不改变 GitHub Pages 的公开资产集合。
3. 截止日期、回测/模拟/前瞻、结算/估值暂定、原始/复权价、基准身份必须沿用来源口径。
4. 所有金融数值采用唯一 formatting contract；不从图表曲线反推出不存在的指标。
5. UI 使用 story/fixture 的模拟数据必须打上 SYNTHETIC；演示不等于测试了真实生产环境。
6. 每个实施 PR 优先运行受影响组件的单测/静态 E2E 和浏览器检查；依赖升级、路由切换/发布 RC 时做扩展回归，不要求每次修一处排版都跑全套。
7. 使用 feature flag 或 opt-in route 做首次新布局验证，不立即拆除线上稳定入口。

## 9. 三种视觉候选（进入 Work 设计原型前需要制作）

**A · Decision-first 工作台（推荐）**：首屏 Today 重大变化和四策略简明对比；点击进入证据与 TradingView 图表。适合每日研究决策，信息密度中等。

**B · Research Terminal**：主图居中，左侧策略/证券列表，右侧研究解释和证据。适合深度盘后复盘，不宜成为初次打开默认模式。

**C · Racetrack-first**：核心 NAV + 赛季榜、Runner 详情、市场状态对照。最强调策略研究故事，但托管 localhost-only 和 runner 未成熟阶段容易形成空入口。

**建议：A 为默认，B 为 Strategy/Instrument 的深度视图，C 仅在有经验证的本地结果时启用。** 三种方案的截图、桌面/移动交互和用户任务 walkthrough 应在 Product Design 的 Work 模式原型中并列供 Owner 选择；本 RFC 不冒充已交付视觉稿。

## 10. Owner 待裁决（不阻塞文档 PR）

- D1 — 是否接受 A 作为默认首页，并将 B/C 作为工作模式，而非三个独立产品？
- D2 — 是否批准未来以 Today / Strategies / Research Lab 为主要导航，System 为次级入口？可先内页标签验证，不立即改变主路由。
- D3 — 研究成果的公开策略：继续 local-only，还是未来允许审核脱敏的公开 Racetrack 赛况？**默认 local-only**。
- D4 — 图表 POC 以证券详情为第一站，然后决定是否扩展到策略 NAV？**默认是**。
- D5 — 中英双语：面向本人使用可先英文、术语注释中文；面向对外传播再单独确定国际化。默认保持当前站点英文。
- D6 — 是否在独立 Work 产品设计会话制作三版可点击页面 prototype 和 UX 测试脚本？推荐执行，但不将其视为现有源码已改。

## 11. 验收指标（可量化，不造数）

可测试的用户任务：

1. 用户从首页至**任一当前变化**的支持/反证/局限/下次动作，不多于 2 次点击。
2. 用户能明确区分**四条正式策略**、实验 Runner 和未经验证 RDI，不误解为实盘信号。
3. 无账号/受限、无历史数据、过期、缺基准、RDI 未认证、localhost-only、读源失败均有可行动的友好状态。
4. 证券页面区间切换，OHLCV/信号事件与同一 manifest 绑定；缩放/点击标记/触屏和键盘替代路径均可用。
5. 策略绩效“数值-基准-日期窗-回撤”一致，无回填、插值、错位或假零值。
6. 375px、平板、1440px 桌面可完成同一核心路径；无不可访问 drawer/横向页面溢出。
7. 核心页面、路由、屏幕与卡片的“一个任务，一个主操作”能通过实际截图和使用者试用。
8. 新组件实现可观察到维护成本降低或用户任务显著改善；否则回退/不引入依赖。

**完成定义**：Owner 选择设计方向；原型按核心任务 UAT；落实到拆分的实现 PR；GitHub Pages 的实际呈现与状态按部署 SHA 再验收。本文 PR 仅是设计提案。
