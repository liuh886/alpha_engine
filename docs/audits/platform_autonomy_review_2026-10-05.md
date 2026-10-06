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
