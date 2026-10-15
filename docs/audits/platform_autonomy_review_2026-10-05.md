# 平台自运行与少干预评估 — 2026-10-05

边界：`research_only=true`、`trade_ready=false`。本轮复用活跃策略注册表、冻结契约、决策账本和现有健康投影。

## 判断与证据

平台已具备调度、数据刷新、到期评估、证据发布、状态投影和通知恢复入口；尚未完成连续 20 个合格交易时段的少干预验收。不能用工作流数量或通知成功代替闭环完成度。

本地基线：`65add4e9e`。读取远端 main 得到 `40635ef02c912579248ebb3b105916ded6831d86`；本轮未同步或更改远端，远端运行结论与本地检查分别记录。

| 环节 | 观测 | 对少干预目标的含义 |
| --- | --- | --- |
| 活跃策略 | 注册表包含 5 个策略 | 复用现有运行路径，维持独立契约 |
| 当前价格及正式证据 | 本地投影：US 2026-10-02、CN 2026-09-30 | 中国国庆休市期间不应报工作日缺口 |
| 调仓与观察 | US ranker 距到期 5 个交易时段；CN ranker 距到期 2 个交易时段 | 未到期不重训；历史信号的因子日期继续如实披露 |
| 整体运行健康 | 本地 `alpha ops build` 为 delayed | ranker 因子观察较旧、CN27 通知 pending；不能伪装成全部新鲜 |
| 训练就绪 | 8 个配置中 4 ready、4 blocked | 阻塞未来训练的配置不能自动阻塞现有未绑定策略 |
| 后端完整检查 | 10 月 4 日两个测试分片合计 3 个失败 | 已本地复现并修复；尚无修复后远端运行结果 |
| 发布成本 | 最近成功正式刷新约 20 分钟，其中 publish 14 分 45 秒 | 发布为优先分析的耗时阶段，不能据此跳过校验 |

远端依据：[后端完整检查失败](https://github.com/liuh886/alpha_engine/actions/runs/37188892750)、[最近成功正式刷新](https://github.com/liuh886/alpha_engine/actions/runs/37116300247)、[最近成功排序策略运行](https://github.com/liuh886/alpha_engine/actions/runs/37116300246)。任务时间包括环境准备和验证，不是纯计算基准。最近通知和状态发布成功只能证明对应步骤运行成功。

## 本轮落实

1. 修复非法观察日期被误判为新鲜：日期解析失败时标记 stale，缺口未知，不进行数据补齐。
2. 健康汇总复用已有交易所时钟，将当前已完成交易日纳入期望截止日；相互一致的旧证据也会显示 delayed。节假日不计为缺失交易日，正式证据一致性仍单独保留。
3. 修复劳动节交易日数量断言；移除 CN27 永久阻塞的测试假设。增加对照检查，证明训练组件阻塞变化不改变未绑定的运行策略健康。
4. 更新运行手册，将日常观察与训练/全历史回放分开，明确旧 US23 本地定时模板不是活跃平台自运行入口。

未增加调度器、工作流、注册表、数据库或运行配置；未修改模型、参数、候选池或提交的数据证据。投影与治理报告保存在可丢弃的 `artifacts/autonomy-review/`。

本地验证：117 项相关测试通过，覆盖状态展示、健康、交易所时钟、策略投影、正式刷新/发布及通知恢复；两个修改模块的 mypy 和 Ruff 通过，两项 CI 治理检查均为 0 violations，工作流仍为 45 个。真实 `alpha ops build` 成功生成 5 个策略及健康投影，保留 delayed 状态。本轮结果不代表已部署、全仓测试通过或已完成 20 时段生产验收。

## 后续顺序与验收

| 优先级 | 需要闭合的问题 | 验收依据 |
| --- | --- | --- |
| P0 | 将本轮修复纳入实际运行后观察日常闭环 | 连续 20 个合格交易时段记录截止日、阶段耗时、人工介入和发布/投递回执；合法阻塞不算刷新成功 |
| P1 | US 调仓目标仍为 pending execution；CN27 本地账本通知仍为 pending | 从既有执行观察与投递回执确认状态，不能凭 outbox 成功或未来价格自动推断已执行 |
| P1 | US87 Alpha158、基本面及公司行动组件未纳入当前共享包 | 通过现有来源流程生成 manifest-bound 组件，再让声明对应配置的训练门禁判定 |
| P2 | 正式发布阶段占最近成功运行的大部分耗时 | 从现有步骤日志区分拉取、物化、测试和前端构建成本；精确身份复用有效输入及校验回执，保留原子审核发布 |
| P2 | 本地定时模板仍会启用旧 US23 与周研究任务 | 检查实际安装者及调用者后收敛旧路径，避免无意增加重复研究负担 |

当前被阻塞的配置与具体原因来自 `data/research/model_data_bundle_v1/training-profiles.json`：

- `qqqi_qqq_tqqq_rotation_v1`：缺 reference bundle 组件。
- `us_selected_alpha158_v1`：缺 US Alpha158 panel 组件。
- `us_selected_price_plus_fundamentals_v1`：缺 US87 基本面及公司行动组件。
- `us_small_pool_price_plus_fundamentals_v1`：缺窄池价格及基本面组件；不能替代 US87。

共享包的汇总截止日不是所有组件的截止日：保留组件各自日期及适用性，不把旧的事件或因子证据描述成刚刷新。

## 后续实施：已验证来源接入

本地已快进同步到 `40635ef02`，保留前述修复。CN27 的既有回执
`deliveries/2026-09-30/37120326490.json` 为 `not_required`；不需要补发通知。
US ranker 的 pending execution 保留：当前账本只有目标决策，不能从行情或
正式回测自动推导成真实执行观察。平台仍不处理券商执行。

读取真实运行与下载验证后，确认两个可复用来源：

- [US87 事件运行](https://github.com/liuh886/alpha_engine/actions/runs/36869443810)：
  截止 2026-09-30，来源包校验通过且 publication eligible；基本面 86/87、
  SBGSY identity missing，公司行动覆盖 87/87（含明确 no-event 状态）。
  按冻结配置的基本面最低覆盖 0.8 和公司行动覆盖 1.0，通过相应训练配置；
  这不等于基本面全覆盖，也不保证模型训练或评价成功。
- [ETF 参考运行](https://github.com/liuh886/alpha_engine/actions/runs/37140721387)：
  QQQ/QQQI/TQQQ 截止 2026-10-02，Tiingo 专业来源和独立对账均通过。

两者以 exact run/artifact ID、压缩包 digest、manifest hash 和各自实际截止日
加入现有来源注册表。正式刷新增加三个已有种类的组件，不新增工作流。
ETF 来源验证增加 bundle/pool identity 和实际文件 hash 校验；ETF 原生 manifest
的 `common_history_end` 现在参与截止日门禁，避免缺失旧字段绕过 post-cutoff 检查。

通过原有下载验证和 bundle builder 生成本地候选包：
`artifacts/autonomy-next/model-data-candidate/`，bundle ID
`dd5eba8ae1509d5a4f4d24b2a7465f9d2a8ed418a7d429f1032ab753dde7637d`。
8 个配置中 6 ready、2 blocked。仅安装压缩包验证后的紧凑 manifests，
不将 59 MB 的 US 基本面原始事件复制进消费者。已有 CN 来源和价格证据保持原样。
候选产物未覆盖 canonical evidence，合并代码后的实际证据仍经原有原子正式发布流程生成。

两个新来源目前绑定 Actions 保留期（US 2026-12-30、ETF 2027-01-01），
尚无 durable release mirror；不能声称跨保留期已完成自运行。
过期后必须通过既有治理取得可验证的精确来源，不能发现并静默使用 latest。

剩余阻塞：[US Alpha158 真实失败](https://github.com/liuh886/alpha_engine/actions/runs/37017651652)
的 preflight 显示 `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY` 未配置，
SIP 与 OTC 测试标的全部无法取数。需在现有 GitHub Actions Secrets 配置合法来源密钥，
再运行既有 US87 canonical VWAP 流程；不能用 close×volume 或窄池替代。
US23 手动诊断配置继续缺少独立的窄池组件，不自动重启该旧研究路径。

发布步骤实测拆分：Market Evidence 物化约 90 秒，候选验证 218 秒，
等待候选检查/合并/Pages 458 秒。后者是证据发布门禁，不应删掉以缩短时间。
本轮没有足够证据支持缓存或跳过这两类校验，保留原路径。

后续实施验证：174 项相关测试通过；全仓 Ruff、4 个修改模块的 mypy、两项
CI 治理检查及 diff 检查通过。来源包通过真实下载、压缩包 digest、绑定 manifests、
US 事件成员和 ETF 成员校验，候选共享包通过原有完整索引校验。
代码变化尚需 PR 检查与审核合并；未完成 20 时段生产验收。


## 合并部署及后续运行检查 — 2026-10-06

PR #1173 已通过全部检查并合并，main 为
`cdcd347f68072b907889e37f4c32b740c55ca4ac`。
[Pages 37338628444](https://github.com/liuh886/alpha_engine/actions/runs/37338628444)、
[Strategy Operations 37338628091](https://github.com/liuh886/alpha_engine/actions/runs/37338628091)
和 ranker 37338628038 均成功。正式刷新 37338628445 的两市场供应商阶段成功，
仍需其完整审核发布回执，不能将本地候选 6/8 当作已发布结果。
用户要求的两个 Alpaca Secrets 已加入既有 convergence backlog，尚未配置。

额外检查发现：BYD 运行 37314634201 在相同 2026-09-30 观察上重建全局因子目录
identity，导致与已封存决策冲突。来源 manifest、归一化观察和实际决策一致，
仅全局目录身份及最终 fingerprint 改变。修复在经账本校验读取后，对同日、精确
同源的观察复用原封存信号，保留原因子和实现身份，不重建因子、不覆盖封存记录。
同日来源改变则要求治理更正；新日期仍正常评估。显示文本从原信号渲染。

35 项相关测试通过，包括隔离临时来源/账本、跳过重复评估、精确重复封存的
字节不变、来源变化拒绝、新日期评估以及账本损坏拒绝。Ruff 和修改脚本 mypy
通过；生产来源只读 CLI 验证返回原 fingerprint `12dd7284182a1346f588`。
该优化不新增工作流、状态库或调度器，仍为 research-only。


正式发布闭环：刷新 37338628445 成功，审核 PR #1175 合并为
`bfd8c75d251a0a0fac7a525709cd845e94f43e5a`；Pages 37340710580 成功，
包含真实线上策略浏览器验收。发布的模型数据 bundle 为
`c006542892518087da9d6d474f2ededdab20f1ea37651e719b1cd78eefc91eff`，
6/8 训练配置 ready，实际 US 2026-10-02、CN 2026-09-30。
其计划的五个策略均为 no-op，execution matrix 为空，未重新训练或回放。
最初版本的额外线上校验也通过 45 个正式区块。
后续刷新 37407613714 亦成功；BYD 37409291653 仍为相同观察的封存冲突，
本次修复针对该独立运行故障。后续优先验证精确缓存命中与冷/热刷新耗时，
补齐合法 Alpaca 来源，并通过既有源保留治理消除 Actions 过期依赖。

下一次刷新 37407613714 的 CN 供应商阶段命中精确 effective-cutoff 缓存，
跳过增量扩展并完成原校验，整个供应商 job 为 79 秒；首次重建 job 为 331 秒。
这是两次实际运行观察，不是受控性能基准。US 新截止日仍正常增量更新。
缓存复用路径已有实证，优先继续观察，无需新增缓存层。


## 深入运行检查及依赖隔离 — 2026-10-06

修复后的生产 BYD 37452359038 成功，保持原指纹 `12dd7284182a1346f588`，
同一观察未重算；运行状态发布 37452482992、37462552142 均成功。
最新模型数据证据截止 2026-10-05，仍为 6/8 配置 ready；Alpaca 两个 Secrets
尚未配置。来源保留期待办继续有效，不未经来源许可将供应商数据公开上传。
截至本次检查，BYD 旧代码失败记录保留；另一独立 sleeve 运行
37367365504 的 contract-tests 成功、live-update 被取消，不作为当前主循环失败。

ranker 到期命令此前无条件导入美中两个推理模块。现在沿用现有两个 adapter ID，
仅 build 或治理更正时加载所选市场的原推理函数，到期检查不依赖任何推理模块。
不新增注册表、调度器、缓存层或工作流，不改变冻结训练/评估边界。

以同一生产证据、固定请求 2026-10-05、独立解释器比较：美股到期命令
1.324 → 1.064 秒，A 股 1.180 → 0.942 秒；两边输出 JSON 完全一致。
导入模块数均从 1030 → 824，两个推理模块由均加载变为均不加载。
这些是本机单次测量，不能推断整个 Actions 作业缩短同样比例。

44 项相关测试通过（36 项运行/账本/能力测试与 8 项推理/冻结边界测试）；
新增冷启动拒绝推理依赖、仅所选市场加载、入参保持和未知 adapter 拒绝检查。
Ruff、脚本 mypy、两项 CI 治理检查通过，工作流仍为 45。

生产状态仍明确区分旧决策的真实截止日与未到期的 10 会话周期；US ranker
仍显示目标待确认执行，未凭时间经过就标作已执行。应通过现有治理证据确认
下一开盘观察。20 个有效会话验收仍未完成。

## 模型能力与前端判断准确性 — 2026-10-07

后续正式刷新 37490310117 和最新运行状态发布 37491273412 成功。
现有模型不是无约束的在线自学习系统：US x1.3 是 US87、13 因子、10 会话
前瞻目标的冻结研究基线；CN x1.2 是 CN130、17 因子和 breadth 风险缩放的
冻结研究基线。两者的静态精选池均显式保留 survivorship_bias=true。
因此没有证据支持仅增加因子、调参或扩大池就能提高泛化表现。

优先能力缺口：US87 canonical VWAP/Alpha158 仍需合法 Alpaca 来源；
CN x1.2 的 2026H1 回撤恶化门禁仍失败，用户研究基线采纳不将其改为通过；
US x1.3 的六个月前瞻门禁仍未完成。下一次风险改进必须预注册并保持独立
证据边界，不能用同一已观察结果反复挑选参数。现有 model_operations.py
尚无生产多市场来源 adapter，markets=[] 是明确缺失，不能称为漂移正常。
后续监测应消费当前权威策略 manifests，不另建 champion 注册表或调度循环。

前端沿用现有 Data / Compare 路由。Data 页在异步验证完成前显示检查中，
校验失败可重新读取并校验；切换证据包立即隐藏旧包结果。数据 ready 仅表示
声明的数据门禁通过，不表示收益、模型晋升或执行就绪；hash 验证单独命名。
Compare 页直接消费现有 v2 权威运行目录和完整 comparability_key，读取其市场、
股票池、区间、基准、频率、预测周期、调仓及成本合同，展示各包实际截止日和证据完整性，
并逐一保留解释限制。缺失的相同身份不再判为一致，不突出最佳指标。
这提升比较的可靠性，不构成模型收益提升声明，不改变任何冻结模型或证据。

比较页按选中记录只加载 performance / diagnostics 两个区块，复用已有
SHA/字节数校验，独立区块失败不掩盖其他有效证据。选择身份使用 exact run key，
不把同版本不同运行折叠为一个模型；只有指标单位、估计方法、年化、样本数及
证据范围也一致时才突出数值。旧模型索引不再是该页的正式证据来源。

验证：全站 48 个测试文件、180 项测试通过，生产构建、TypeScript 和全站
ESLint 通过；新增静态浏览器验收在桌面、平板、手机各通过一次，检查 Data
缺失状态、旧索引独立的正式 v2 比较、真实 CN 回撤失败说明、页面横向溢出和脚本异常。

远端 PR 前端审计发现 source-map-js 1.2.1 命中
[GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)。
仅将该间接依赖锁至修复补丁 1.2.2（锁文件 3 行替换），不改变直接依赖范围；
既有 moderate-or-higher 门禁保持，本地 npm audit 返回 0 vulnerabilities。

## 权威运行监测与旧前端路径收敛 — 2026-10-07

前轮 PR #1178 合并为 `85304c071caf6d4426eb2800a91f60d508d1fb0d`；
[Pages 37499976999](https://github.com/liuh886/alpha_engine/actions/runs/37499976999)
发布和两项线上全策略验收成功，额外桌面/手机比较页及线上 Data 验证通过。

继续检查发现，Model Operations 路由只消费未接通生产来源的旧通用投影，
无法展示现有五个正式模型的运行状态。漂移计算器需要基线/当前预测和成熟
标签窗口；当前决策账本及持仓解释不能替代完整跨截面窗口。未改动冻结模型、
漂移阈值或训练流程，未据此计算 PSI / Rank IC 衰减等缺乏来源的统计量。

现有页面改为直接消费正式 v2 运行目录、既有 system-health 和经 SHA/字节数
验证的 diagnostics。健康记录必须同时匹配 model、bundle、run、market、cutoff
且唯一；匹配失败显示 unknown，正式历史说明仍可阅读。显示供应商、正式证据、
因子和信号评估的实际日期及各自状态，健康投影生成时间单独展示。
统计漂移始终明确 unavailable，与运行新鲜度分开。刷新只重新读取已有证据，
不训练、不扩池、不发单，也不构造模拟绩效或重建 champion 注册表。

各模型说明独立加载，一项失败或延迟不挡住其他有效状态；切换正式目录或刷新
立即隐藏旧结果。当前持仓、计划和信号驱动继续在已有策略访问门禁后查看。
调用检索确认旧 TypeScript operations reader 仅余测试引用，删除该未使用
前端路径及对应旧测试，保留 Python 历史诊断能力、冻结合同和所有研究证据。

验证：185 项测试（47 文件）、TypeScript、全站 ESLint、构建和预算检查通过；
桌面/平板/手机新增监测页验收均通过，实际五个正式模型及 CN 失败说明可见，
未请求旧 data/model-operations 投影，无脚本异常或页面横向溢出。
JavaScript gzip 从前轮 472.26 KB 到 470.43 KB（上限 480 KB），不是运行耗时基准。
两个 Alpaca Secret 名称检查仍为空；其来源阻塞待办未关闭。

## 完整优化工程执行边界 — 2026-10-08

用户要求开展完整优化工程；本轮沿用现有权威注册表、冻结合同、证据存储、
CLI 和工作流，保持 research_only=true、trade_ready=false。接受范围是既有
五策略的来源、到期评估、封存、正式发布、运行监测与前端，以及依赖回归。
不以扩因子、调冻结参数、启动训练或新增调度器代替运行闭环。

执行与验收分为以下相互可验证的增量：

1. 来源接通：两个标准 Alpaca Secret 名称已核实。US 以明确完成截止日
   2026-10-07 执行现有 SIP/OTC 预检；仅在其通过后构建精确 US87。
   配置存在不代表认证、权限、覆盖率或训练就绪已经通过。
2. 增量复用：修复 CN VWAP 请求区间首尾为节假日、上市日晚于请求起点
   时的精确缓存复用。保留原 raw/qfq 存储，metadata 绑定两份文件 SHA256，
   没有哈希的旧缓存或被修改的文件不复用；原配对、价格、VWAP、生命周期、
   覆盖率等检查照常执行。18 项来源/适配器测试和脚本类型检查通过。
3. 前端事实：上下文栏优先显示所选正式 run 的名称、市场及真实截止日，
   不借用旧总览包的日期或校验徽章。缺失截止日显示未声明。
   新增 3 项上下文测试，188 项前端测试、TypeScript 和 ESLint 通过。
4. 运行与依赖：全量后端回归正在执行；检查既有生产刷新、缓存、到期、
   发布和交付记录。2026-10-08 GitHub 显示 197 项开放依赖告警，
   其中 22 critical、100 high；不能沿用历史“安全清零”说法。
   优先验证兼容补丁，Qlib/MLflow 等主要版本变化需独立兼容证据。

现有 Alpaca 工作流增加轻量凭据检查及紧凑 credential-preflight.json，
在安装 live job 重依赖前拒绝缺失名称，只保留名称与研究边界；12 项
工作流合同测试通过。因用户随后补齐标准 Secret 名称，不保留临时名称映射。
CI 治理检查通过，工作流仍为 45；未新增缓存目录、状态库或永久流程。

后续必须记录真实提供商预检、CI、合并与部署结果，以及运行时长与具体阻塞。
20 个合格运行会话、成熟预测标签与统计漂移、来源长期保留和独立 CN 风险
评估仍有各自验收条件，本工程不能把这些未完成的时间/来源门禁标成通过。

实际来源运行 [37732288574](https://github.com/liuh886/alpha_engine/actions/runs/37732288574)
的 credential-preflight 为 passed、missing_credentials=[]。AAPL/MSFT/NVDA
各 192 条 SIP 日线，最后日期 2026-10-07、reported_vwap；ABBNY/SBGSY
OTC 各返回 HTTP 403、attempts=1。完整 US87 构建按原门禁未启动。
[Alpaca 官方 FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) 明确 OTC
需要目前仅面向 broker partners 的特殊订阅；不把普通 SIP 订阅或密钥配置
等同于 OTC 授权。失败 artifact 保留，两只股票未从固定池删除或替换。

补充验收：31 项来源、适配器和工作流测试通过；新增 CN 构建集成测试验证
真实原始/复权配对经过原语义检查、精确请求不再次抓取、源和元数据字节不变。
既有 Actions 缓存键改用 sha256-v1 格式，避免不可覆盖的旧无哈希缓存导致
每次运行重新抓取；目录、池身份、截止日和保存路径保持原合同。
完整静态浏览器验收 40 passed、2 个既有设备跳过；产物 JS gzip 470.41 KB，
480 KB 门禁通过；npm audit 为零。Doctor 环境检查通过。生产来源只读
US 2026-10-07 / CN 2026-09-30 到期命令均 due=false，未触发推理或训练。

首批优化 [PR #1185](https://github.com/liuh886/alpha_engine/pull/1185) 已合并为
`0dc863c1b932984f01da4017711f4455f3223b4a`，全套相关 CI 通过。
本轮全量后端基线 3888 passed、8 既有跳过，耗时 19 分 21 秒；新增及后续
修复另以受影响测试验证，不能把基线计数称为更新依赖后的全量回归。

安全增量仅更新既有锁文件七个包：GitPython 3.1.62、Mako 1.4.2、PyJWT
2.15.0、PyMongo 4.18.2、Tornado 6.5.9、urllib3 2.8.0、Werkzeug 3.1.9。
uv.lock 其余 package block 字节保留，Qlib/MLflow/NumPy/pandas/LightGBM
及直接依赖约束保持原值，`uv lock --check` 通过。

七包隔离环境兼容性检查通过，覆盖 JWT 编解码、变形 PEM 公钥拒绝作为
HMAC 密钥（[GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9)）、
HTTP URL、Git 读取、Mako 模板、BSON 编码、Tornado JSON 与 Werkzeug WSGI。
冻结开发环境实际安装七个修复版本后，Doctor/Qlib C++ 扩展检查通过，103 项
来源、工作流、ranker、模型数据、健康与运行状态合同测试通过。
这七包关联 34 项当前开放告警，合并后需核对实际关闭与剩余记录；
主要版本变更及无补丁问题尚未关闭，未声明全平台依赖安全清零。

安全 PR #1186 已合并为 `a87c27e64b75580f3c87ea4fafdce5de0e210c7a`，
相关 CI 通过。首批 Pages 37733480780 成功，包含提交身份校验及线上正式
策略验收。最新告警基线因新增报告变为 198；按实际 vulnerable_version_range
逐项核对，七个新锁定版本避开对应全部 34 项，零仍受影响、零未分类，
实际主分支扫描关闭另行核对。

源缓存最终准入补充：raw/qfq 抓取后先保留 pending 元数据及文件，原语义
检查通过才标为 passed。仅哈希、请求身份和语义收据均有效才复用；失败输入
不会阻止下一次正常源刷新，也不会靠清除失败记录变为成功。既有 Actions 键
加入 validated 格式身份，防止不可覆盖的旧键造成重复抓取。
32 项来源、适配器和工作流测试通过；新增失败→重新抓取→验证后复用的
完整边界测试，坏源文件与失败诊断在失败运行中照常保留。

### 2026-10-08：数据请求与 MCP 依赖安全增量

继 #1186 的七包修复后，实际主分支扫描已关闭 34 项，仍有 164 项开放。
本次仅更新既有 uv.lock 六个 package block：mcp 1.28.1、
python-multipart 0.0.31、requests 2.33.0、idna 3.15、python-dotenv 1.2.2、
pydantic-settings 2.14.2。共 18 行替换，其他包、直接依赖约束、冻结模型
合同及来源证据保持原值；uv lock --check 与 frozen dev 安装通过。

当前 GitHub API 告警逐项核对覆盖 13 项（5 high、5 medium、3 low），
修复版本均在各自 vulnerable_version_range 之外。合并后另核对实际关闭数。
MCP 上游修复包括 WebSocket Host/Origin 校验及实验任务隔离；上游依据为
[SDK 公告](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-vj7q-gjh5-988w)
和[任务隔离公告](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-hvrp-rf83-w775)。
本增量没有启用新的网络传输、任务模式或服务。

冻结环境下 135 项现有 MCP、来源适配器、刷新、ranker 与运行发布合同测试
通过（60.34 秒）。另用真实 SDK 注册现有 21 个工具，验证 Host/Origin 白名单
接受及异源拒绝、URL 参数、国际域名、dotenv 插值、Settings 和表单解析。
该检查没有执行回测工具、发送请求或订单；临时验收收据位于 ignored artifacts。
Doctor 检查 Qlib 0.9.7 / C++ 扩展及既有模型依赖健康。

实际运行 37737437715 的 canonical 身份、运行状态物化、OIDC 发布及成功
幂等收据均通过，信号投递 37737437733 成功。安全升级仍不关闭 Alpaca OTC
权限、前瞻观察期及逐合同数据门禁；MLflow/protobuf/setuptools 的迁移和其余
开发依赖告警继续保留，不声明整个依赖树安全清零。

### 2026-10-08：Qlib / MLflow 记录链路安全迁移

#1190 合并后实际关闭 13 项；扫描剩余 151 项。当前开放的 MLflow 和其旧
OAuthlib 依赖共 74 项（21 critical、38 high、13 medium、2 low）。候选锁文件
将 MLflow 1.27.0 迁至 3.16.1；Qlib 0.9.7、原有其余包版本及直接依赖约束
保持原值，移除仅旧 MLflow 所需的五个包，新增其新版本必需的依赖。
没有另建实验管理器、登记册、追踪服务或工作流，也没有启用自动训练/追踪。
完整开发锁检查和安装通过；不是以仅 import 成功作为迁移验收。

现有 Qlib SQLite 回环测试增加嵌套 DataFrame 文件、本地证据目录、同一运行
恢复、失败状态与失败文件保留。真实 MLflow 1.27.0 隔离环境生成旧库后，
SQLite backup 保留 bd07f7e963c5 原结构，再由 3.16.1 原生命令迁移。
Qlib 读取旧运行 ID、参数、指标及 artifact URI 一致，文件 SHA-256 一致，
恢复后仍只有同一运行；备份及旧文件保留。当前本地库的备份副本也已迁移
验证。隔离修复后的完整后端测试 3894 passed、8 项既有跳过、72 warnings，
耗时 968.66 秒；本地记录库测试前后 SHA-256 一致。合并后扫描关闭数另行核对。

本次只消除记录器依赖与旧库迁移堵点。US 下一开盘执行证据、Alpaca OTC
权限、前瞻观察期和未通过的数据/效力门禁继续保留；protobuf/setuptools
固定约束和 notebook 依赖仍需各自兼容验收。

迁移验收另发现原测试隔离只覆盖 paths.MLRUNS_DIR，未覆盖 qlib_init 在
collection/import 时保存的目录引用。现有 autouse fixture 同时限定
MLFLOW_TRACKING_URI 和该模块的 MLRUNS_DIR，增加默认记录库位置回归断言。
首轮全量测试中止后重新执行；不把中止的结果记为全量通过。
本地库备份已保留，核验仍为零 run / 原 Default 实验；未改变正式证据。
既有 ops build 实际 1.526 秒生成五策略视图，未加载 Qlib / MLflow / LightGBM
或行情适配器；相同输入再次物化为 no-op。US 当前正式 trades 的研究收盘
参考价和 prospective_unrealized 角色不能替代下一开盘执行回执，相关等待保留。

### 2026-10-09：Jupyter HTML 导出沙箱修复

独立小增量仅将 uv.lock 的 jupyter-server 2.17.0 升至 2.20.0，三个锁行
替换；其余包、模型合同、工作流保持原值。此包当前关联五项 GitHub 告警，
其中包括当前扫描仍报告的严重项；实际关闭数合并后核对。

在隔离环境使用从候选锁递归导出的原版本依赖运行真实 localhost 服务。
认证 API 200、无认证 API 拒绝、markdown notebook HTML 导出 200，
Content-Security-Policy 包含 sandbox allow-scripts 且无 allow-same-origin。
未启动内核、执行 notebook 代码或暴露远程服务，临时测试进程已退出。
依据为 [Jupyter 上游公告](https://github.com/jupyter-server/jupyter_server/security/advisories/GHSA-fcw5-x6j4-ccmp)。
修复使用原生包，不加入公告中的运行时 monkey patch 或常驻包装器。

### 2026-10-09：剩余 Python 依赖门禁收敛

前两次主分支扫描实际关闭 79 项，剩余 72 项（37 high、31 medium、4 low），
Critical 为零。本增量逐条核对全部 72 个 vulnerable_version_range，候选包
版本均在受影响范围之外；实际扫描关闭结果合并后核对。

解除两处已无源码调用依据的旧固定上限：protobuf 改为 >=5.29.6,<7，
setuptools 改为 >=83,<84。同步锁定 protobuf 6.33.6 / setuptools 83.0.0，
OpenTelemetry proto 升至 1.45.1 与已锁 SDK 对齐。其余修复版本：Starlette
1.3.1、JupyterLab 4.6.4、Notebook 7.6.3、nbconvert 7.17.1、Mistune 3.3.0、
Bleach 6.4.0、Pillow 12.3.0、lxml 6.1.0、Pygments 2.20.0、pytest 9.0.3。
Notebook 原生要求 JupyterLab >=4.6.4；不以不相容的单包升级绕过解析。
仅增加 Notebook 新版本必需的 jupyter-builder 依赖，其余原包 block 保留。
Qlib、MLflow、NumPy、pandas、LightGBM、池与模型合同保持原值。

冻结环境和 Qlib 记录/初始化/MCP/报告 12 项既有测试通过；真实 SDK 的 21
工具注册、初始化消息及非法 Host 拒绝通过。PNG 图像、Matplotlib 渲染、
HTML/XML、MLflow protobuf 与 OpenTelemetry 消息编解码兼容验证通过。
新增真实 MCP/ASGI 回归测试并加入既有 backend CI，不新增工作流或服务。
Doctor 正常；Notebook HTTP 的认证及 HTML 沙箱边界另行验收。
完整后端与最终主分支扫描、运行发布结果在本 PR 验收中记录。

PR #1193 主分支验收：3895 passed、8 既有 skips、71 warnings，1086.34 秒；
持久 MLflow 数据库 SHA-256 与测试前相同。运行发布 37812496839 成功绑定
89e4eef70d833b69f397642ed54850321d429ce0。Pages 影响检测成功，因无前端
产物变化而跳过重建。GitHub 重新扫描将原有 72 项全部关闭，同时新增
Mistune >=3.3.0,<3.3.3 的递归拒绝服务告警 #260，因此仍有一项 high。

后续增量仅将 Mistune 3.3.0 升至 3.3.3，锁文件六行替换。1000、3000、
10000 个强调符号在原生 Markdown API 下均完成渲染，Notebook HTML 导出
通过；不加入运行时 monkey patch 或调高 Python 递归上限。该增量使用
针对性报告、记录库及 MCP 回归验收；不将此前全量测试冒充为最终补丁的
全量测试。最终扫描和发布结果单独核对。

### 2026-10-15：按序落实运行完成度优化

用户确认推进 10-14 开发评估。基于远端 main `fb809e403` 的隔离分支，先修复
全览上下文与默认目录排序的混淆，并保留同模型日次运行之间的选择。191 项
前端测试、TypeScript、全站 ESLint、构建与预算通过；静态浏览器 40 passed、
2 个既有设备跳过。此前七项失败均来自固定等待 QQQ 默认上下文的共同假设，
当前全览按正式目录显示，各详情绑定自己的运行身份。

真实 US87 来源清单显示，08-04 是 EA 的受治理终止历史；其余活跃成员已到
10-13。归一化对完整核验的 publication 应用生命周期汇总，保留 EA、原历史
与 terminal 日期。现有 campaign 编译/执行复核新增必需时间序列的实验截止
检查，并复用同一门禁，减少重复验证实现。本地候选共享包完整校验通过，
原有两个 blocked profile 保持。没有覆盖 canonical evidence。

后续 pending 观察回执保留具体失败门禁与已有 prospective scope，原回执不
重写、不将用户采纳或工程验收当成效力通过。原取数工具增加轻量只读留存
检查，报告注册表身份、到期日、声明镜像与恢复动作；不下载大数据，镜像
声明不冒充真实取回验证。US 源保留期与 OTC 权限仍需既有来源治理解决。

上述受影响后端检查共 146 passed；修改范围 Ruff 和既有 CI 治理通过。
广泛扫描还报告了旧本地诊断脚本的 lint 问题，未修改这些非本轮文件，未
声称全工作区 lint 清零。当前实际运行基线和各阶段记录保存在
`artifacts/operating-closure-20261015/`。交付与远端验收尚在推进；真实 20 会话、
US 六个月、CN27 12 个月/240 会话等边界没有被本轮代码代替。

发布/提供器/原子 fan-in 另 98 项回归通过，合计 244 项相关后端检查。
既有 CI 实际 68 路径 Ruff 命令通过；修改的五个模块 mypy 通过。新增类型
声明只修正 companion index 的原有推断问题，不放宽校验。两项治理检查均
为 45 工作流、零违规。没有新增工作流、注册表、数据库或调度器。

### 2026-10-15：合并、正式发布与线上验收

工程 [PR #1203](https://github.com/liuh886/alpha_engine/pull/1203) 在全部相关检查
通过后合并为 `699708f5bb5cec576aa8250f6e8e413fca3d5cee`。主分支运行发布
38599383406 成功；[Pages 38599383367](https://github.com/liuh886/alpha_engine/actions/runs/38599383367)
部署及线上全部正式策略浏览器验收通过。

由原工作流自动启动的
[正式刷新 38599383616](https://github.com/liuh886/alpha_engine/actions/runs/38599383616)
完整成功。计划只运行三个需要推进的 CN 策略任务，QQQ 与 US ranker 为
no-op；两市场提供器、策略、候选完整验证和原子发布均通过。审核数据
[PR #1204](https://github.com/liuh886/alpha_engine/pull/1204) 合并为
`a9004350468851dd25a1506c88d244652110e280`，候选所有相关检查通过，包含
静态 PWA。最终 [Pages 38602000249](https://github.com/liuh886/alpha_engine/actions/runs/38602000249)
再次完成部署与线上五策略验收，2026-10-14T16:58:26Z 验收通过。

已发布共享数据清单实际为 CN 10-14、US 10-13；US87 仍计入 EA，并明确
保留 08-04 终止历史。共享包三项索引在本地再次完整校验通过。训练 profile
仍为 6 ready、2 blocked，没有放宽 US Alpha158/OTC 或旧窄池门禁。持续效力
回执仍按实际证据保留 pending/blocked，未因工程发布改判。

另逐项核对并关闭六个已被主分支修复覆盖的 Dependabot PR：#1165、#1163、
#1162、#1161、#1131、#1128。前五个目标版本已精确锁定；MLflow 已为较新的
3.16.1，其 Qlib SQLite 回环测试与 CI 入口也已被扩展实现覆盖。原分支及历史
保留，没有再次变更依赖或处理未完成的研究 PR。

本轮工程交付与一次实际正式刷新闭环已验证。仍未完成的条件是：20 个适用
会话的连续运行验收、冻结模型各自的充分前瞻观察、OTC 授权、以及 US events
与 QQQ reference 的合法长期源留存。当前精确截止与已发布结果可继续读取；
这些后续条件不能靠循环重跑、历史回放或乐观默认提前关闭。

### 2026-10-15：首条可核验运行观察

连续验收从既有证据累积，不另建调度或状态库。本条核对正式刷新
38599383616 的原始诊断包（artifact 11915025658，88,168 bytes），其压缩包
SHA-256 为 `0fc9e5d2129d9ad9bbc11f5c7c49513898833aaa1c8c55e2df49d85d5c3c09bc`。
解压成员与原包字节一致；refresh receipt 对 fan-in 的哈希、sync receipt 对
已合并正式 catalog 的哈希、两份回执对已合并 freshness 的哈希均一致。
诊断包到期为 2026-11-13T16:58:49Z，以下紧凑记录与代码/数据身份保留在本文。

运行 trigger=push、attempt=1，代码身份 `699708f5b`，正式数据身份 `a90043504`。
US cutoff=10-13、CN cutoff=10-14；三个 CN 任务执行，QQQ/US ranker no-op；
fan-in=complete，没有 retained strategy。正式发布、Pages 38602000249、BYD/
CN27 当前目标、运行发布与投递回执均已分别核对成功。回执中的
candidate_ready_for_review 是候选阶段状态，最终发布成立另由合并及线上验收
证明，不把候选回执单独当作已发布。

CN27 的 10-14 投递记录 `38602873587.json` 中 delivery.status=sent，与已封存
信号的 model/date/fingerprint/signal_sha256 一致；这是实际回执核对，不只看
outbox 作业绿灯。它仍不证明目标已经执行，执行等待继续保留。

| 作业阶段 | 单次墙钟耗时 |
| --- | ---: |
| prepare | 1 分 57 秒 |
| US provider | 1 分 07 秒 |
| CN provider | 3 分 07 秒 |
| plan | 11 秒 |
| BYD strategy | 1 分 04 秒 |
| CN ranker strategy | 1 分 11 秒 |
| CN27 strategy | 1 分 25 秒 |
| publish | 16 分 31 秒 |
| 首个作业开始至发布结束 | 23 分 20 秒 |

提供器和策略作业存在并行，不能把各行相加当总耗时；时间包含安装、验证与
审核/部署等待。本次任务集合、缓存与前次不同，不据此宣称系统总体提速。

使用已合并 canonical evidence、固定观察时点 2026-10-14T17:05:00Z 重建五策略
视图，整体 health=delayed，三个策略 current、两个 ranker delayed。价格和正式
cutoff 已到上述日期；两个 ranker 因子观察仍为 10-09，分别距评估还有 8/7 个
会话。旧因子日期继续如实显示，未因工作流成功改为 current，也没有为状态
读取重训。待执行目标仍待对应执行证据，不从时间经过推断成交。

人工介入次数缺少独立声明，记录为 unknown；attempt=1 和自动触发不能代替
“人工介入为零”的证明。本条为首条已核验运行观察，不记为已通过 1/20，
更不代表连续 20 会话、下一次完整调仓周期或模型效力验收。后续逐会话使用
同一组现有回执和状态字段记录，重复触发不增加会话数。

### 2026-10-15：当前状态读取恢复与故障隔离

基于 `702047ec9` 继续核对发现三个前端缺口：单条运行投影缺失或格式错误会
阻塞全部策略；运行投影仅核对策略/模型，没有核对当前正式包、运行与截止日；
后端保留决策 status 的同时降低 observation freshness，前端仍可能显示健康 Hold。
账号客户端初始化拒绝还会留下未处理的异步错误，使读取一直停在 loading。

现有 operations reader 按策略验证 payload 和正式身份，保留其他独立有效记录。
不合法的顶层 schema、研究边界和重复身份仍拒绝整个文档。缺少稳定策略身份时
保留未知，不从 model_version_id 或 model_family_id 推测，不生成可编辑权限项。
运行数据同样绑定当前正式包，正式截止日与决策日期仍可不同；身份不匹配保留
脱敏壳和读取失败提示，不拼接旧运行。公共投影的既有脱敏合同保持。

全览、策略列表和详情复用一个读取状态控件，提供只读刷新/重试与受影响策略
提示。公共身份先显示，独立运行记录完成后逐条显示；账号、权限、正式运行或
重试身份变化时立即隐藏旧结果，丢弃晚到的旧请求。仅请求当前账号具备访问
资格的策略，减少无权限读取。该操作不取行情、不训练、不回放、不写入证据。

状态摘要统一使用 observation freshness、staleness 和 state_detail；延迟或受阻
记录进入 Needs attention，保留实际截止日。全览 Operational 数量不再包含
受阻记录。正常到期本身不是故障；within_cadence、距评估会话数及待执行证据
仍单独披露。未知加载身份不能成为 owner 权限设置中的新资源。

这是本地前端实施，尚未部署。20 会话验收、充分前瞻窗口、OTC 权限及合法长期
来源留存仍未由本轮变更解除；本轮也不新增工作流、调度、注册表、数据库或依赖。

最终本地验证：49 个测试文件、219 项单测通过；其中读取/恢复/健康合同共
30 项。TypeScript、全站 ESLint、语言/账号/正式证据门禁及生产构建通过。
现有 Playwright 静态验收在 1280×720 桌面、1024×1366 平板和 Pixel 7 手机
共 49 passed、2 项既有离线设备跳过；新增失败恢复、身份拒绝及过期/未到期/
待执行并存场景在三种设备均通过。恢复场景不重载正式证据，缺少其他四策略
的受控响应仍可显示有效 QQQ 状态；相关页面异常检查与横向溢出检查通过。
截图复核新控件与手机布局，无框架错误覆盖层。Browser 插件未提供，沿用
仓库已有 Playwright；运行服务使用受控响应，不将它称为线上服务验收。
最终 gzip JS 为 471.36 KB，低于既有 480 KB 预算；不宣称系统总体运行提速。
只修改前端实现、受影响测试和本文；未改 canonical research evidence。

交付前复核继续在独立分支进行，基线快进至 `afcd7b42b`，仅接收原发布流程
新增的 US 10-14 / CN 10-14 正式证据和投递回执。独立五维代码复核指出并修正
两个恢复缺口：请求一直不返回会永久禁用重试；有唯一 model_version_id 但缺少
strategy_id 的记录仍会阻塞全组。后者现在只阻塞该模型，缺失身份保持未知。

同一个读取尝试设置 15 秒观察期限，包含公共投影、账号/权限准备、客户端和
运行读取。超时保留已验证的独立结果，恢复重试，并中止投影 fetch；不能取消
的账号或运行客户端响应由既有 active/request 身份隔离，不在晚到后启动读取
或覆盖当前结果。没有增加轮询、后台重试或 SDK 包装器。清理会取消定时器。
新增检查覆盖五种卡住状态、超时后重试、有效记录保留、晚到响应拒绝和缺失/
空稳定身份隔离；38 项针对性检查通过，独立复核确认两项问题均已解决。

交付复核最终验证：227 项全站单测、TypeScript、ESLint、完整构建与既有
前端门禁通过。桌面/平板/手机静态验收 52 passed、2 项既有离线设备跳过，
包含使用浏览器受控时钟验证的超时恢复；不是靠增加真实等待或放宽超时来
使检查通过。最终 gzip JS 为 471.47 KB，预算 480 KB。结果基于最新正式目录，
代码及本文待原有 PR/CI 交付；未将本地受控响应当作线上运行服务证明。

### 2026-10-15：读取恢复正式交付与第二条运行观察

[PR #1209](https://github.com/liuh886/alpha_engine/pull/1209) 的静态 PWA、正式
刷新契约、Bundle v2 同步和安全检查均通过，合并为
`5447ba5c9cc85fb642716b1b2e3544295d6b7b83`。
[Pages 38707544384](https://github.com/liuh886/alpha_engine/actions/runs/38707544384)
部署、提交身份校验及线上五策略浏览器验收全部成功；运行状态发布
38707544407 同样成功。上一节的“待交付/尚未部署”是其本地阶段记录，当前
工程修复已上线，不再是仅有本地候选的状态。

额外真实线上只读检查绑定 deployment.json 中上述提交和工作流身份，在
1280×900 桌面、412×915 手机分别打开 QQQR 策略并点击 Refresh operations，
均回到已读取状态。页面标题/主标题、控件、页面异常、控制台错误及横向溢出
检查通过；两端均为零页面异常、零控制台错误、零横向溢出。截图与临时收据
位于本机临时目录，不作为新的研究权威。此为访客读取与恢复控制验收；已登录
受保护运行响应的失败/身份拒绝/超时仍由受控浏览器及合同测试覆盖，不将
访客测试冒充为真实 Pro 账号的读取或交易执行证明。

日常闭环另已自动完成
[正式刷新 38666484844](https://github.com/liuh886/alpha_engine/actions/runs/38666484844)，
经审核数据 [PR #1208](https://github.com/liuh886/alpha_engine/pull/1208) 发布为
`ecdc24bea05a1fed66e429ff14a107868bdcda94`，原 Pages 38667714610 成功。
本次取回诊断 artifact 11943236853，87,239 bytes，压缩包 SHA-256 为
`0592a8d2ec93b5d5bc8aa1ef13cf97bf30ada07b6767f74981df48462a9a3e36`，与
GitHub 返回 digest 一致；到期 2026-11-14T01:53:12Z。refresh receipt 对 fan-in
的哈希、sync receipt 对已合并正式 catalog 的哈希，以及两份回执对已合并
freshness 的哈希均核验一致。

US/CN cutoff 均为 10-14；执行 QQQ 与 US ranker 两个正式刷新任务，三个 CN
策略为 no-op，fan-in complete、无 retained strategy，没有重开模型选择。
单次墙钟：prepare 121 秒、US provider 149 秒、CN provider 12 秒、plan 13 秒、
QQQ 75 秒、US ranker 47 秒、publish 695 秒；首作业开始至发布结束 1,061 秒。
作业并行且任务集合与上次不同，不相加或据此宣称整体提速。

这是第二条核验后的运行观察，不记为已通过 2/20。人工介入缺少独立声明，
仍为 unknown。以 canonical evidence 在 2026-10-15T08:40:19Z 重建五策略状态，
整体 delayed，仅 QQQ current；其余策略按当前已完成会话和保留观察如实显示
延迟，不从成功工作流推断刚更新。20 会话连续验收、各冻结模型的充分前瞻
窗口、OTC 授权和合法长期来源留存继续开放；工程交付未解除这些条件。

### 2026-10-15：本地诊断调度范围收敛

复核现有 `setup_cron.py` 的调用者、诊断 CI、运行手册、历史 ADR 和本机
Task Scheduler。系统任务清单读取成功，未发现 AlphaEngine 或引用项目/生成
启动器的已安装任务；仓库运行调用者仅为生成器及其测试，没有调用已提交
`scripts/run_weekly.bat` 的入口。该批处理固定绑定本机仓库和 Python 路径。
这是本机检查，不声明其他机器没有自行安装的旧任务。

原 POSIX 模板为 US23 诊断一并加入三个周任务，Windows 生成器也写入周研究
启动器并输出安装指令。现在只生成明确选择的一个 US23 诊断任务，Windows
产物与 POSIX crontab 一样放在 ignored `artifacts/`，不再改写源码目录；控制台
如实说明只是生成模板。机器绑定的旧批处理从维护运行面删除，精确 Git 源码
revision/hash 留在既有 archive manifest。周研究、因子衰减和周报仍可通过各自
原命令明确执行，独立冻结研究能力与 US23 来源/门禁不变。

没有安装、修改或移除系统任务，也没有改变任何活跃 GitHub Actions 调度。
迁移文档要求先检查现有任务 action/crontab，再更新明确保留的诊断启动路径；
旧 ADR 增补当前调度范围，原历史决定保留。后续仍不把本地诊断模板当作平台
自运行入口。工作流保持 45 个，两项治理检查均为零违规。

本地验证：16 项低换手诊断/决策/运行测试通过；Ruff、生成器 mypy、diff 检查
通过。真实 Windows CLI 仅生成 ignored 启动文件；在隔离子进程中去除
SEC_USER_AGENT 后启动该文件，退出码 2、未进入取数。归档清单中的 Git 源码
SHA-256 核验一致，独立五维代码复核无必改项。此处证明生成范围与失败边界，
不声称活跃策略总体提速或连续运行验收完成；PR/CI 交付另行核对。

### 2026-10-16：来源恢复与近期 US87 的可执行落地

用户确认没有 Tiingo 套餐，并选择先验证已有权益覆盖的近期 US87；完整历史
合同继续未完成。新研究来源合同没有修改原专业 v1 或完整 Alpha158 合同。

[ETF CI 38757752731](https://github.com/liuh886/alpha_engine/actions/runs/38757752731)
实际构建免费 Yahoo 三 ETF bundle，截止 10-14、专业来源标志 false，无 Tiingo
文件或请求。源 ZIP artifact 11983524280，SHA-256
`6da52ca8563264ec0fdaba50819bba828f9e1cd70e026bd85111297bb9bab9ad`。
US events 原 ZIP 的 SHA-256
`23d192b96e3bf4f38e1937c2c6896e112b7d8962f8a45bed06e56fe8fc5f686e`
保持不变。两份精确字节已存入私有 Git，注册表绑定独立不可变提交；
[archive_probe 38776911484](https://github.com/liuh886/alpha_engine/actions/runs/38776911484)
在真实 CI 用仓库限定只读 deploy key 取回并完成全部组件核验。私有 Release
尝试因既有 API token 不含新仓库权限而失败，已替换为 scoped SSH 读取；未扩大
个人 token 权限。源镜像声明与真实取回证明继续区分。

真实本地 QQQ 六输入截止 10-14 重放为 exact_replay，冻结前缀 679 report、
1017 positions、129 trades 完全保留，当前来源决策路径同样一致。10-15 构建
中 ^VXN 尚止于 10-14，正式重放门禁拒绝该 cutoff，失败证据保留；没有前填或
重算历史经济证据。换源不证明模型有效性。

近期第一轮 [38776904561](https://github.com/liuh886/alpha_engine/actions/runs/38776904561)
获得 87×158 面板、13,746 个质量组合通过，技术上证明 SIP/Polygon 组合可取。
归档 `19786e7a31e2f20bb007dc390b829fbe6c450239`、ZIP SHA-256
`58de9485c8d9520f19aff37b1cb7f4cc0a1c8a8386d16bb66e1bcaa57f7ec25e`
已实际取回并核验 88 个面板/质量文件哈希。但复核原始行发现 EA 超过受治理
08-04 终止边界，该轮不能作为生命周期合格最终证据。随后补齐原 builder 的
生命周期约束、绑定 registry 哈希，保留原失败研究并另跑纠正版本。

第二轮 38790372707 已使 EA 源历史止于 08-04，87×158 质量检查仍通过。
检查导出值又发现 Qlib rolling 表达式可在 source_close 缺失后输出数值；质量表
原本正确排除这些日期，但面板文件仍暴露 2,177 个不可用值。共用面板构建器
现在在写盘前按同一 canonical_close availability 全部掩码为空值，公式及门槛
不变；实现哈希使旧缓存不可复用。第二轮留存供复核，不冒充该修复后的最终包。

20 会话工具已接入既有诊断路径：观察保存 cutoff、正式身份、执行/no-op、
阶段时间、发布与阻塞，独立评审绑定真实决策/投递。修正复审发现的两个假阳性：
Actions 成功不是决策/投递证据；CN27 每日估值刷新不是 30 会话到期评估。
周期来自冻结合同，需前后封存调仓锚点。当前仍不能声明已通过 20 会话。

技术长期存储已验证，但许可不自动随存储解决。SEC companyfacts 可依据
[SEC 政策](https://www.sec.gov/about/webmaster-frequently-asked-questions)复用；
US 企业行动及 QQQ 的 Yahoo 来源仍受个人用途和数据条款约束。
[Polygon 条款](https://polygon.io/terms/market_data_terms.pdf)还要求核对非展示计算、
衍生作品和终止后保留权益。近期完整数据仅私有保存，不声明永久许可已经到位。
用户尚未提供 Polygon 套餐/非展示权益证明，独立许可确认继续开放；研究与
trade_ready=false 边界不变。恢复、运行与许可确认步骤已写入既有恢复手册。
