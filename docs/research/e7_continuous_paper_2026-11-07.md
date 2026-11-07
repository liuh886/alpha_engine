# E7 连续纸面研究运行交接

状态：**本地部署与真实行情预热通过；连续前瞻 NOT_STARTED**。
承接 [#1382 的 Owner Review](https://github.com/liuh886/alpha_engine/pull/1382)
所确定的规则基准先行方向。只使用 `rule_momentum60`、`rule_momentum120`，
不训练模型、不启动 Colab，不接券商，不修改正式策略注册或前端。
XGBoost/LightGBM 仍因缺少可验证模型文件而阻塞。

冻结依据是 [E7 独立合同](../../configs/research_experiments/e7_rules_paper_20261110_v1.json)，
先于任何未来预测提交于 `5bb982ed82`，SHA256：
`f37a4d7a039c52f8acd0175e22715f8f2f7cd0c5c02d20c240ab6e2baa857b1b`。
首个信号日为 **2026-11-10**；11/09 留给部署预演。
这不修改、不恢复 E6 原四模型 11/09 登记，也不暗示它已提交预测。

## 实现与时序

`python -m src.research.e7_paper_daily` 提供 `init/run/status`。
独立 episode 根目录必须位于源码仓库外；初始化必须早于首个交易日开盘。
注册回执绑定合同、计算链源码、`uv.lock` 与实际 Python/关键依赖版本。
只有既有 canonical Yahoo adapter 负责获取与标准化行情；E7 校验和保留每次请求、
原始响应、标准化表、行情面板及其 SHA256，不新建数据供应商或回测引擎。

1. 交易所实际收盘后，读取 US73 + 独立 QQQ 的最近 121 个 XNYS 交易日。
   每只必须全日历覆盖，原始/复权收盘价有限且正，成交量有限且非负；不删股、不填补。
   `first_seen/available_at` 记录这次真实请求时刻，不能倒写为行情所属日期。
2. 用当次来源快照计算 60/120 日收益评分，一次封存两份完整 73 股评分。
   截止时间为下一实际交易日开盘；CLI 使用真实 UTC 时钟，没有历史日期覆盖参数。
3. 仅已封存的上一交易日预测，可在下一交易日收盘后生成纸面成交代理与持仓。
   同时记录预测 SHA、信号日、成交参考日、生成时间和当前未计费用。
4. 使用既有 `replay_ledger` / `_simulate_portfolio` 和 E6 selection callback 计算
   漂移、换手、成本、个股贡献与连续参考净值。新增 opt-in `end_state` 只暴露
   最新收盘目标/待计成本，不给缺少下一价格的区间伪造收益。默认 E4/E5/E6 路径不变。
5. 每个截止日封存纸面 Parquet、来源调整桥、回执、周期记录和 Markdown 绩效报告。
   当日已完成则校验保留证据，不重新下载或重复下单；失败逐次保留，OS 单写锁防止并发。

执行政策保持 E6 **预注册主政策**：按分数降序、并列 symbol 升序，Top5，
每周首个实际交易日调仓，最小持有 5 个交易日，保留至 rank10，延迟 1 日，
单向换手摩擦 8bps。不会按历史结果换规则。episode 不在报告截止日强制清仓。
最早 11/10 封存预测、11/11 收盘产生首份纸面成交代理、11/12 观察首个持有收益区间。

## 价格和净值的含义

请求保留 `auto_adjust=false / repair=false / actions=true`，客户端 yfinance 1.2.0。
adapter 将 OHLC 按 `Adj Close / Close` 同比调整，Volume 保留供应商值，
`factor=1` 是已调整序列身份，amount 为合成值，不能冒充真实 VWAP。
纸面成交引用当次原始 `Close` 字段，只是收盘参考价，**不是实际成交或可执行报价**。

每日收益用同一次已观察快照中的当日/前日 Adj Close 比值串接；
不会直接相除两个不同复权版本的历史价格。另存前一收盘历史修订比例及来源 SHA。
这可避免跨快照拆股修订造成虚假大额损益，但不认证分红再投资、拆股入账、
公司行为发布时间或 as-traded 股数。纸面参考净值不等于现金/股票托管账户。

费用沿用 E4 收益区间扣减语义：收盘交易的费用在下一已观察收益区间计入；
最新收盘的 pending fee 明列于成交回执。没有独立手续费筹资模型，不能将
最新待计费前的值当作已结算账户净值。容量、真实滑点/价差、PIT、独立样本认证均未通过。

## 已观察的部署结果

冻结计算源码 `a5b8e3fef3` 已导出到仓库外独立目录，单独创建环境，按 `uv.lock`
安装：Python 3.12.12 / NumPy 1.26.4 / pandas 3.0.1 / pyarrow 23.0.1 /
yfinance 1.2.0 / exchange_calendars 4.13.2。后续工作分支改变不会更换运行源码。
部署脚本提交为 `67ef981c8e`，只创建自身的原生 Windows Task Scheduler 任务。

| 检查 | 实际结果 |
| --- | --- |
| 首次注册 | 2026-11-07 13:36:19 UTC，早于首个信号日 |
| 真实行情范围 | 2026-05-18～2026-11-06，74 个资产各 121 日，共 8,954 行 |
| 独立来源核对 | 74 份 raw/request/normalization/normalized SHA；Close、Adj Close、Volume、Dividends、Stock Splits 与面板逐项一致 |
| 请求实际可得时间 | 2026-11-07 13:36:45～13:37:21 UTC；不声称 11/06 已掌握 |
| 定时任务试跑 | 2026-11-07 21:42:32 +08 启动，LastTaskResult=0，同截止日校验完成，无重复下载 |
| 当前预测 / 纸面成交 / 持有收益区间 | **0 / 0 / 0** |
| 原证据保护 | E4 288、v6 261、E5、E6 归档重新计算 SHA256 全部未变 |
| 针对性验证 | 22 个 kernel/ledger/selector/E6-forward/E7 测试通过；新增 E7 两模块 Ruff/mypy 通过 |

其中完整时序测试使用合成未来日期，只验证程序，不作为真实前瞻证据。
完整机器可读核验见 [acceptance.json](../evidence/e7_rules_paper_2026-11-07/acceptance.json)。
市场回执 SHA `1485031d636c5918897d65df2c55c5e5d9c664f247a61dfa26061c799c757994`；
首个周期 SHA `4996327182b27707080bd543fc8a9bd88f6e240043456cf3268b672bff7674e1`。
本机 SHA 封存及独占写入不是第三方时间戳、公证或防本机管理员篡改认证。

## 每日操作与故障处理

实际运行根目录：`D:/Documents/AlphaEnginePrivate/P2-E7/2026-11-07`。

- 独立源码/依赖：`runtime-a5b8e3fef3/`（内含专用 `.venv`）。
- 活跃记录：`episode-20261110-v1/`；看 `health/latest.json`、`reports/<session>.md`。
- 审计：`market/`、`sources/`、`predictions/`、`fills/`、`paper/`、`cycles/`、`failures/`。
- 每次原生任务日志及退出码：`jobs/`；可用 `Get-ScheduledTaskInfo -TaskName AlphaEngine-E7-Rules-Paper` 查看任务状态。

任务每天 **22:00 UTC（北京时间次日 06:00）** 运行，启用 WakeToRun、
StartWhenAvailable、失败后 30 分钟重试两次；未改变既有 PR monitor。
当前用户须保持登录、主机有电且网络/本机 Clash 7900 可用；休眠唤醒不等于保证关机或注销后运行。
手动重试必须在冻结 runtime 目录使用其 `.venv/Scripts/python.exe`：

```powershell
$e7Base = 'D:/Documents/AlphaEnginePrivate/P2-E7/2026-11-07'
Set-Location "$e7Base/runtime-a5b8e3fef3"
& ./.venv/Scripts/python.exe -m src.research.e7_paper_daily status --root "$e7Base/episode-20261110-v1"
& ./.venv/Scripts/python.exe -m src.research.e7_paper_daily run --root "$e7Base/episode-20261110-v1"
```

若已过预测期限或漏掉任何已到期日，episode HALT，保留失败记录；必须明确另建
未来日期、独立 ID/目录并重新冻结，不能删 `HALTED.json`、改注册日期或补写评分。
未完成周期的文件若因故不一致，应保留失败供诊断，不能覆盖旧证据强行续跑。
日常源码升级也需要独立新冻结/迁移，不能直接改活跃 runtime。
未来连续验收应逐日检查封存时间、上一日预测哈希、持仓漂移/净值费用对账和漏日记录，
积累实际日数后再作金融评估；本次没有为尚未观察的收益提供结论。

## 元数据交接归档

已写入 Drive Desktop 的 4 个文件并逐项回读大小/SHA256：
`G:/My Drive/AlphaEngine/03_Data/Research_Exchange_P2/incoming_unreviewed/e7-rules-paper-bootstrap-20261107-a5b8e3fef3`。
ZIP 为 **2,588,803 bytes / 11 members**，SHA256
`61c2908f1371ebbce8a8816aa22517852f34746e5e42327381536be9ec335ce7`；
外置 manifest SHA256 `8845752a6f2273eb4ce8c23c6731dd2071d7440585a1d3d8e5a9e9d1ee4a1637`。
见 [delivery.json](../evidence/e7_rules_paper_2026-11-07/delivery.json)。

这是公开计算源码、合同和清理后的部署/覆盖审计元数据快照，**不是全量数据包**。
新的原始行情、任务账户 XML、日志内容和未来每日预测/成交均不在此包内，仍以本地
活跃 episode 为准。未推定新的来源云复制许可；没有认证远端同步完成或私有 ACL。
ZIP 内的报告为封存当时版本，后续运行说明以本 PR 文档为准。

## 依赖与合并边界

| 顺序 | PR | 当前处置 |
| --- | --- | --- |
| 1～4 | #1368 → #1374 → #1376 → #1377 | OPEN / Draft；先验收数据、许可、实际目标主干，再顺序集成 |
| 5 | #1380 | OPEN / Draft；`1629241259` 修复漏核 published worst drawdown / median Rank IC；30 测试及原 v6 261 回执核验通过，未重训 |
| 6 | #1381 | OPEN / Draft；保留 E5 原始复现与延迟执行证据 |
| 7 | #1382 | OPEN / Draft；Owner 接受研究工程，ML 优势未通过、容量阻塞、原前瞻未启动 |
| 8 | E7 独立功能 PR | 以 #1382 为 base；只增加两规则真实时间记录链路 |

没有合并上游、放宽筛查、发布正式交易信号或改写已完成模型回执。
独立本地研究任务已部署，不代表 Draft 依赖栈或正式产品获准合并/发布。
