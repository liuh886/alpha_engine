# 既有策略观察闭环修复

2026-10-25 Direction A W1：最新[20 会话盘点](../evidence/product_v1/w1_operating_2026-10-25.md)
核验私有归档 211 次采集、27 个正式尝试；US/CN 各仅覆盖 7/20 个真实会话，
独立合格均为 0。最新正式尝试 40169478271 的相同证据发布路径失败仍保留，
不回退挑选旧绿包、不把机械检查或历史五策略包算作当前四策略验收。A1 仍 BLOCKED。

当前目标是已有策略的研究跟踪、变化解释和风险观察；不新增交易授权、模型参数或选股池，也不宣称持续有效性已获证明。

## 数据接续

合并后的正式刷新 `37097230994` 中，两市场 provider 和四个策略任务成功；CN27 在 300274 的冻结 OHLC 重叠失败，原子正式发布被阻塞。

300274 的发行人公告 2026-068 明确规定：2026-09-21 除权参考扣减为每股 0.6351450 元，实际派息为每股 0.64 元。两者不可混用。公告 PDF 已保存并绑定 SHA-256；`data/research/source_reconciliations/cn27/price-basis-v1.json` 声明的是既定腾讯来源的加法前复权研究价格基准转换，不是从价格差拟合偏移。

转换后的所有 OHLC 仍通过原有冻结重叠容差；冻结 CSV 不被修改，追加数据沿用该研究价格基准。原始腾讯读数、转换数据、事件、文件哈希和转换回执保留。未知公司行动、其他变换或来源冲突继续阻塞，不能由这一现金事件兜底。价格用于研究特征及回放，不是原始可执行价格，也不能代替股息现金账本。

真实提供器输入验收：八只冲突证券均完成既定来源重读；300274 四个 OHLC 字段与冻结历史的最大绝对差均为 0.000855，低于未修改的 0.01 容差。完整本地刷新候选推进源证据截止至 2026-09-30，报告 729 行、持仓 8745 行、交易 326 行的原有前缀检查通过。该验收不是正式线上刷新成功的替代。

2026-10-08 正式刷新再次在 688676 的冻结重叠门禁失败。发行人 2026-081
权益分派公告声明 2026-10-08 除息，每股实际派息 0.22 元；除权参考扣减
按 100997026.46 / 459787393 计算，公告四舍五入显示约 0.2197 元。
已在同一 price-basis-v1.json 加入该事件并绑定公告 PDF 哈希，不以观察到的
0.22 价差拟合修正，也不把实际派息额代作参考扣减。真实失败输入转换后的
813 个冻结会话、四个 OHLC 字段均通过原门禁，最大绝对差 0.000339723 元；
冻结 CSV 和既有容差保持原值。最终正式发布仍须经过原子发布验收。
真实云端 provider 输入的完整本地刷新已生成
cn_27_v1_3-through-2026_10_08，原有报告 729 行、持仓 8745 行、交易 326 行
前缀检查全部通过，model_selection_reopened=false。公司行动与刷新回归
20 项通过。该本地候选不替代受审正式发布。

## 日常运行

- 复用 `market_session_clock` 的锁定交易所日历函数，既有 ranker 调度与运行状态使用同一会话定义；收盘边界与提供器实际覆盖仍单独验证。国庆及美股休市不再作为工作日计入延迟。日历范围不可用则状态未知，不退回工作日推测。
- 运行发布缓存按 canonical SHA 和六小时观察窗口去重。没有新提交时，也会重新物化时效；同一窗口的重复触发仍复用成功回执。
- 旧信号的 creation-time validity 单独保留；今天已经过期的数据及因子不再显示 current。
- `decision_schedule` 从已有冻结 YAML 的 rebalance_sessions 推导评估是否到期；没有新增阈值或评估器。未到期、每日数据缺口、等待执行证据分别显示。
- CN27 的稳健性电池使用冻结历史窗口；源更新没有改变冻结 OHLC，且报告前缀通过后，保留原有 window_summary，避免每次再跑历史扰动、bootstrap 和参数电池。失败门禁始终保留。

## 用户视图与效力判断

详情主层显示失败门禁/反证数量、源证据截止、信号日期、市场已完成日期、实际数据日期、距评估剩余会话及执行待确认。每日风险过时不被“尚未到下一次调仓”掩盖。

主层另显示最近两条真实财富观察之间的收益、最新观察相对已观察峰值的回撤及其变化，并明确展示实际日期、稀疏结算或 provisional MTM 边界。它复用经过 manifest 哈希/大小校验的 performance 序列，不触发数据下载或模型计算；没有完整初始本金、有效财富或有序日期时显示不可核验。首条失败门禁或反证直接可读，完整证据保留在展开层。

CN27 历史 trace 按原有合同保持在 2026-09-04；源截止推进不是历史收益 trace 自动延长，更不是前瞻验证完成。其既有独立 prospective contract 要求原始/调整行情、可交易性、公司行动、12 个月及至少 240 个会话。应通过该合同积累后续观察，不能把本轮来源核对替代为通过前瞻门禁。

CN27 current-target 状态同时报告 source_available 和 current_target_available；后者必须核验截止日的 manifest-bound 持仓。行情已更新但持仓未覆盖时，命令保留 data_blocked 回执且不生成权重；损坏或不合法权重仍以 invalid_evidence 拒绝。该入口补充路径限定的 PR 验证，PR 不执行决策写入。

新模型固定池数据计划继续按 AGENTS.md 执行。2026-10-09 核对：两个标准名称的
Alpaca Secrets 已就绪，真实 SIP 请求已通过；ABBNY、SBGSY 仍因 OTC 权限返回
403。用户确认暂时没有覆盖这些证券的授权服务，因此保留 US87 全池对应门禁，
不替换证券、缩池或降级到其他行情来源。已有策略日常观察不以全部训练 profile
就绪为前提，其他工程修复继续推进。

US x1.3 冻结模型使用 same_adjusted_close_research_mark；current-target 的
next_eligible_open 是目标执行意图，不是实际执行回执。正式 trades 中的
prospective_unrealized 和研究收盘参考价不能证明下一开盘成交。原有状态仍为
target_pending_execution，只有合同绑定的执行证据才能解除该等待；时间经过、
送达成功或价格估值均不能替代。该边界不阻塞独立策略的有效观察。

## 验收边界

### 2026-10-15：总览上下文与选择连续性

总览和策略列表的顶部明确显示正式策略全览，各策略保留自己的截止日；
不再把目录排序首条的 BYD 作为整个全览的日期或身份。单策略详情仍显示
精确运行上下文；侧栏文字改为 Selected evidence，区分已选证据与全览。
既有会话状态保存所选模型版本，同模型的新日次运行发布后继续选择该模型；
精确旧运行仍存在时保留原选择，版本消失时才回到当前有效目录。

本地 191 项前端测试、TypeScript、全站 ESLint、生产构建及 470.56 KB / 480 KB
JS 预算通过；桌面/平板/手机静态浏览器验收 40 passed、2 个既有设备跳过，
覆盖全览、详情上下文、刷新选择及桌面离线重开。此前七项静态失败的固定
QQQ 默认假设已移除，按权威正式目录验证全览。尚未提交、部署或完成远端
验收；本地通过不能代替连续 20 个合格交易时段的运行验收。

### CN27 运行观察接续修复

源截止已到 2026-09-30，但 `run_projected_recipe` 使用历史合同的
`evaluation.full_window.end=2026-09-04`，正式持仓因此没有推进。
刷新现在显式传入观察截止；同一冻结策略计算器保持原来选股、风险、成本、
30 会话相位和次日开盘重试逻辑。历史 report、positions、trades、收益指标及
失败稳健性门禁仍封存在原有窗口。

最新研究观察作为紧凑 `source_evidence.operating_state` 绑定到现有 Bundle v2
lineage，包含当前模拟权重、锁定目标、最近调仓日、待执行状态、因子观察及
来源/合同/实现哈希。它没有独立登记册或发布路径，也不代表账户真实成交或
通过独立 prospective validation。行情有效但缺少该状态的旧正式包可在相同
截止补齐一次；状态已存在且输入未变时，正式刷新仍是 no-op。

current-target 从经 manifest 校验的观察读取目标，日常观察不重置 30 会话
调仓锚点，价格漂移不生成重新配权。七个已有冻结输入只增加当前信号的规范
目录绑定，不改变公式或声称独立验证通过；摘要明确为固定候选截面等权均值。
公共决策账本现可校验、封存这些因子观察。

旧 projected discovery 的实现哈希仍按原始字节核验。精确历史源码压缩快照及
原 Git revision/blob 身份保存在该证据目录；它不是可导入或可调度的旧运行
路径。历史 manifest、输出哈希和失败结论不修改；当前运行另绑定当前实现哈希。

真实本地截止 2026-09-30 验收通过历史前缀 729 条 report、8745 条 positions、
326 条 trades，并完成 preview 封存、正式包校验读取、决策封存及 operations
投影。结果为 `current_no_change`、因子 `current`；最近调仓为 2026-08-25，
已过 25 个会话、距下次调仓 5 个会话。相同输入的后续计划不再请求正式刷新。
诊断位于 `artifacts/cn27-runtime-repair/`；本地验收不替代线上受审发布。

代码及来源修复需经过 PR CI、正式刷新原子发布、运行平面发布和实际 Pages 验收。没有改动正式发布的全策略检查或将 retained/data_blocked 状态认作成功。CI/部署通过只证明工程链路；持续有效性由冻结合同及后续真实观察决定。

## 2026-10-15：数据时间覆盖、观察评审与来源留存

US87 组件原来的 2026-08-04 汇总日期来自 EA 的受治理终止历史，并非其余
活跃股票未刷新。组件归一化现在只对已完整核验的 publication manifest
应用生命周期边界：活跃成员截止日参与当前覆盖汇总，EA 仍计入固定池，
历史仍止于 08-04，并另保留 retained_common_history_end 与终止成员列表。
未经核验的原始清单不能凭 terminal 字段获得此豁免。

使用当前精确来源 manifests 重建的本地候选组件截止 10-13、覆盖 87/87，
全部索引校验通过；原有 6/8 ready、2/8 blocked 不变。canonical evidence
未被本地候选覆盖，正式产物仍须走原子审核发布流程。

既有 optimization_campaign 编译与执行前复核共用数据门禁，额外要求必需的
价格、因子面板和 ETF 时间序列覆盖实验声明的 provider cutoff；共享 profile
ready 不能绕过此检查。事件/PIT 组件仍遵守自己的可用时间合同，不要求财报
每天产生新事件。数据归一化实现加入原有运行身份指纹，避免实现改变后复用
旧编译回执。没有改变任何冻结实验的模型、窗口、因子或成本。

后续新建 pending 观察回执会列出 lineage 中实际失败门禁，并保留声明的
prospective 状态与 scope；trade_readiness_only 不被误当作已经完成持续效力
评审。已封存的 companion receipts 原字节保留，仍不自动改为 supported。
US x1.3 的六个月新身份观察、CN27 的 12 个月/240 会话及 BYD 未完成的
前瞻验证继续按各自既有合同积累，不用工程测试或历史重放替代。

来源检查复用既有取数工具：

```text
uv run python scripts/data/fetch_governed_model_data.py --inspect
```

该模式无需 token，不访问网络、不读取因子/事件大数据，输出精确注册表哈希、
各来源实际截止、Actions 到期日、镜像声明和下一恢复动作。镜像声明始终标记
retrieval_verified=false；真正取回仍走原有压缩包及成员校验。US events 12-30、
QQQ reference 2027-01-01 的 Actions 留存缺口未被这一只读检查解除；合法留存
安排完成前不能声称跨到期自运行。OTC 权限阻塞继续保留。

20 会话运行验收沿用已有 workflow run、正式刷新/fan-in 回执、决策账本、
运行投影与 Pages 验收，不新增调度器或运行数据库。每个适用市场会话记录
expected/provider/formal/decision cutoff、到期/未到期、各阶段时长、发布与投递
身份及人工介入；未记录的人工介入显示未知，不记为零。重复触发只算一个
会话，合法 blocked 不算成功刷新，成功通知不替代正式发布。10/30 会话策略
还需覆盖真实到期周期。连续会话验收记录仍不完整，不能将一次发布当作
修复后 20 会话验收。

远端交付已完成一次闭环：工程 PR #1203 合并，运行发布 38599383406 与
Pages 38599383367 成功；正式刷新 38599383616 成功，经审核数据 PR #1204
发布 US 10-13 / CN 10-14，Pages 38602000249 的线上五策略验收通过。
US87 生命周期合格 cutoff 修复已进入正式共享包，原有两个训练阻塞保留。
这是一轮真实发布验收，不是 20 会话可靠性或模型持续有效性证明。后续仍
从既有运行/封存/投递记录累积逐会话证据，未记录的人工介入保持未知。

## MLflow 记录库一次性升级

冻结环境的 MLflow 安全升级不改变 Qlib 的既有实验管理器。已有 SQLite
记录库需要一次结构迁移，日常观察、状态读取和无变更决定不执行此操作。
新 CI 临时库由依赖原生初始化；持久旧库不能删除后重建来冒充兼容。

对既有 build_qlib_init_cfg 默认的 artifacts/mlflow.db：停止记录写入进程，
用 Python sqlite3.Connection.backup 留下可恢复副本（同时覆盖 WAL 内容），
先在备份副本上运行 `uv run mlflow db upgrade "sqlite:///绝对路径"`，核验
原运行 ID、参数、指标、artifact URI、证据字节及失败记录后，再升级原库。
升级完成后重新启动写入进程。自定义 exp_manager URI 仍是其所属合同的
配置，不重定向到新库。回退需要原依赖环境与升级前备份，不能用旧依赖直接
打开升级后的结构。原文件证据不搬移、不删除、不重封存。

该顺序遵循 [MLflow 数据库升级说明](https://mlflow.org/docs/latest/self-hosting/migration/)。
使用原生命令完成迁移，没有新增启动包装器、自动迁移服务或定期任务。

## 2026-10-16：精确私有归档、近期面板及逐会话验收

来源仍由 `configs/data/formal_model_data_sources_v1.yaml` 唯一管理。US events
原 ZIP 与新 QQQ research v2 ZIP 已存入私有 `liuh886/alpha-engine-data-archive`，
绑定精确 commit、路径、大小及 SHA-256，不以 latest/main 替代审核身份。
取回校验压缩包及既有成员/组件/市场/池身份；消费者仅安装已核验组件清单。
`GOVERNED_SOURCE_ARCHIVE_SSH_KEY` 是仅对该仓库有效的只读 deploy key；
`GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY` 是独立归档写入 key。消费者只用前者。
SSH 443 严格核验固定 GitHub 主机身份，临时私钥退出后清理，无个人 token 留存。
轮换时先验证新 key/secret，再撤销旧 key，不把写入 key 用于消费者。

复用已有 workflow 检验实际取回，无需行情请求：

```text
gh workflow run us87-professional-prices-ci.yml -f mode=archive_probe -f cutoff=2026-10-14
uv run python scripts/data/fetch_governed_model_data.py --source us_events --source qqq_reference --output-root artifacts/source-recovery
```

本地命令需要环境中的只读 SSH key，不把私钥写入命令或日志。
[实际 archive_probe 38776911484](https://github.com/liuh886/alpha_engine/actions/runs/38776911484)
已要求并验证两份回执均为 durable_git；Actions 回退不能冒充镜像验证。
这解决到期恢复问题，不等同数据许可证明。

用户没有 Tiingo 套餐。活跃 ETF/QQQ 路径使用明确冻结的
`configs/data/qqqi_qqq_tqqq_reference_research_v2.yaml`，不调用 Tiingo；原专业
v1 合同保留。三个 ETF 成员/角色不变，来源合同哈希进入复用身份，
professional_source_ready=false。正式重放仅接受该精确研究来源或原专业来源，
不接受任意 fallback；六个策略输入仍须共同覆盖 cutoff。截止 10-14 的真实
重放为 exact_replay；10-15 的 ^VXN 尚止于 10-14，门禁拒绝推进，没有前填。

许可边界：US events 的 SEC companyfacts 适用
[SEC 复用政策](https://www.sec.gov/about/webmaster-frequently-asked-questions)；
同包 yfinance_actions 和 QQQ Yahoo 数据不是 SEC 数据。
[yfinance 官方说明](https://ranaroussi.github.io/yfinance/) 明确工具许可不等于
数据许可、Yahoo 接口限个人用途。私有保存没有产生永久、商业或再分发授权。
当前落实个人研究恢复路径；QQQ/企业行动的无期限许可仍待确认。若要求跨账号
终止后永久保留或对外展示，须取得明确书面条款，不根据 HTTP 200 推断权益。

近期 US87 的独立合同是 `configs/data/alpha158_us87_recent_research_v1.yaml`，
从 2026-01-01 开始，85 只走 Alpaca SIP，ABBNY/SBGSY 走 Polygon。每只股票
OHLCV/VWAP 来自同一拆股复权聚合记录，不加入现金分红复权。生命周期复用
既有 registry：EA 历史截至 08-04，成员保留，之后不可参与。手动执行：

```text
gh workflow run alpha158-canonical-vwap-ci.yml -f market=us -f source_scope=recent_us_research -f cutoff=2026-10-14
```

完整源行、面板、质量表和失败研究进入私有 ZIP；公共 artifact 只保留清单及
归档绑定。只写独立命名空间，不注册原 model-data 或关闭完整历史门禁。
[Polygon 条款](https://polygon.io/terms/market_data_terms.pdf) 对非展示计算、
衍生作品及终止后保留另有约束；API 可取数只证明技术权限。近期结果不声称
这些许可已确认，也不据此自动训练。应向供应商确认现有账号是否覆盖：个人
非展示因子计算、原始和衍生数据私有云备份、账号终止后的审计留存期限及删除
要求。供应商回复需明确账号/套餐/日期/用途，作为许可证据单独保留。

20 会话观察由原 formal-backtest-refresh publish 作业采集，随既有诊断 artifact
按 run_id/attempt 分开保留 90 天；没有新增 workflow 或状态库。publish 未结束
时的时长明确不完整，需另取最终 run attempt/jobs 元数据。人工介入默认 unknown。
评审 JSON 按 run_id:attempt 索引，绑定 observation SHA、最终 Actions 元数据、
operations 快照及每个活跃策略封存 decision/delivery 文件 SHA，填写评审人及
实际人工介入次数，路径相对于评审文件。10/30 会话策略需 previous_decision
哈希，核验真实前后调仓锚点；周期读取既有冻结模型合同，日常估值刷新不算
到期评估。完整字段及可执行例子见 `tests/test_operating_acceptance.py`。

10 会话 ranker 未到期不会重新生成决策。旧信号继续显示实际日期及年龄状态；
运行会话可单独合格，但必须在 review.operating_inputs 提供 plan、fan_in 和
providers.us/cn 的 path/SHA 绑定，并与 observation.receipt_sha256 一致。
冻结周期和交易日历必须证明尚未到期。plan 的正式刷新需求为 false 时允许 MTM；
若为 true，只有已完成的 ranker 正式补齐可进入此分支，且该策略的 decision_delivery_evidence
必须额外提供 formal_manifest、formal_lineage 的 path/SHA。验收器验证正式 bundle ID、
lineage section 的 SHA/字节数、source_preview_bundle_id 与本次 fan-in 成功回执一致，
并要求原冻结回放成功、model_selection_reopened=false。
fan-in 完整无 retained，provider 当前且无未解决数据缺口，原封存因子及投递
仍有效。它不计作新决策或到期周期。缺少这些原件或已经到期时不能沿用该分支。

```text
uv run alpha ops acceptance --input-root artifacts/operating-observations --through 2026-10-14 --declarations artifacts/operating-observations/reviews.json --output artifacts/operating-observations/report.json
```

缺会话、中止、过期数据、未评审、未证实投递或未覆盖真实到期周期均不能完成
验收。重试不增加交易会话数，当前没有补造或追认 20 个合格会话。

## 2026-10-16：观察截止与供应商复权基准分别核验

CN27 的 Tencent qfq 重读可能在 10-16 使用新的除息表示来返回截止 10-15 的
历史。仅按请求截止日选择价格基准转换事件，会让合法重读仍报历史重述。
恢复步骤现在记录请求开始/结束 UTC 时间，要求两者处于同一上海日期，并以
实际取回日期作为来源表示所含事件的上界；不接受返回的截止日之后的价格行。

`reanchor_additive_qfq` 未提供来源时间时仍遵守原截止日上界。提供真实来源
时间时，只有观察截止前已公告、且除息日不晚于取回日期的已核验发行人事件
可用于还原固定价格基准。原始 vendor CSV、转换后 CSV、公告哈希、观察截止、
来源日期上界及全部冻结 overlap 核验共同进入原 recovery receipt。未知事件、
错误表示、跨日期取数和任一历史不匹配继续阻塞，不估算或拟合缺失的调整额。

这只转换供应商的价格表示，不增加未来价格行、现金股息账目或交易会话。
600938 的 0.81324 元公告金额在 10-16 取数时可还原 10-15 截止的历史，但
没有把 10-16 的收益或股息提前计入 10-15。旧失败证据保留，新候选仍需原子
审核发布；不追认旧失败，也不改变模型、因子、成本、池成员或历史匹配容差。

实际正式刷新 38842951989 已成功，数据 PR #1216 合并为
`b6147ed630548ff36c8765de1aac1be3252f9250`，Pages 38844290193 成功。
五条策略的正式证据截止均为 2026-10-15，CN27 目标作业 38844678809
随后封存 10-15 决策。此成功不自动构成合格运行会话：QQQ 每日信号在本次
核对时仍止于 10-14，等待原有定时作业；20 会话验收仍未完成。

本次成功恢复原始/还原 CSV、正式回执、最终 Actions 元数据、观察及未合格
复核原件已归档到私有仓库 `liuh886/alpha-engine-data-archive`，提交
`599a8ff925c2cac8f5c6b08cd495ffc828bb0abb`，路径
`archives/operating-recovery-38842951989.zip`，452181 bytes，SHA-256
`5f4fef9da40f6e3350d5cf5e0ad169acb986efbc4a3ca7889e7df623a4f44511`。
内部索引逐一校验 64 个证据文件；只保留必要原件和紧凑证明，不复制完整回测
到每个消费者，也不把尚未合格的整体验收标为通过。

## 2026-10-16：发布衔接与自动评审原件

PR #1218 把正式刷新成功接入原 QQQ 日评估工作流，保留原定时兜底。
评估前使用当前正式 Bundle 和原封存账本核验已完成交易日；已有决策则跳过
来源获取与计算，正式数据落后则阻塞。新来源的 inclusive cutoff 与 monitor 的
exclusive end 使用同一计划，monitor 必须确实达到该 cutoff 才能封存。
实际补评估 38849909546 已成功，随后 outbox 38850010584 成功。

CN27 完成同样进入原投递 outbox；outbox 在写入投递原件后使用已有
repository_dispatch 路由请求运行视图发布，避免深层 workflow_run 链截断。
失败投递仍先持久化并更新视图，再让投递作业失败；没有新增收件人或订单路径。

原运行视图发布工作流增加独立的原件采集作业，不受视图发布缓存命中影响。
它使用原命令：

```text
uv run alpha ops acceptance --collect-repository liuh886/alpha_engine --input-root artifacts/operating-review --output artifacts/operating-review/acceptance-report.json
```

采集最新 completed formal run/attempt（包括失败，不选择旧的成功代替），验证
Actions artifact 的精确名称、digest、字节数、观察 identity 与最终 run/jobs。
只提取观察、plan、fan-in、两地 provider manifest 等紧凑 JSON，再绑定当前真实
operations、原封存 decision/delivery、前次 decision 及正式 manifest/lineage。
逐策略复用原验收器列出缺口，不从历史日期重建一份假装当时存在的运行快照。

`readiness.json` 是机械证据检查，`review-draft.json` 始终保留
manual_interventions=null、reviewed_by=null、cadence_and_freshness_verified=false。
机械检查全通过仍只是 awaiting_independent_review，不自动增加合格会话。
最终 Actions 原件中的 publish 时长完整可查；采集失败与策略阻塞分别显露。

CI 在原 artifact 存储保留 90 天，并通过已有私有归档函数/专用写入 key 把紧凑
原件包保留到 `liuh886/alpha-engine-data-archive`，返回固定 commit/path/SHA。
归档失败只影响验收证据作业，不撤销已经独立完成的运行视图发布。
每份包明确只覆盖最新一次已完成 attempt。历史包分别保留；独立复核后合并
评审时，每个 run/attempt 只选一份，日历仍按真实市场会话计数，不能把多个包
或重试凑成 20 个会话。没有新增工作流、注册表、状态数据库或并行评估器。
