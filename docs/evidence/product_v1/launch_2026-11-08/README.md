# Launch · 2026-11-08 单页验收

**Preview NO-GO；正式 v1 NO-GO。** Owner允许公开的范围仅为历史证据与脱敏状态。
当前匿名REST仍返回5条含非空allocation的运行记录（含退役cn_x1_2），不能用静态壳安全替代后端安全。
修复 [#1388](https://github.com/liuh886/alpha_engine/pull/1388) 尚未改变生产权限或部署Edge函数。

基线/实际Pages：`1463156c4ad22757d10413a34ef91ca83266e830`，
[部署run42448063579](https://github.com/liuh886/alpha_engine/actions/runs/42448063579)。
安全功能代码：`c1c3c005759b6cdee37e36a9fbbacce111231a62`；后续提交仅测试与验收材料。
私有来源：`a3ddb4482e801c9d6efcbc7bd5b931d0da2948f9`；此包不含私有决策/权重/账户/原始日志。
全部研究只读，`research_only=true / trade_ready=false`。

| Gate | 当前事实及结论 | 剩余阻断 |
| --- | --- | --- |
| A0 | PASS；四个正式身份、Pages精确SHA、36个formal sections验证 | 保持同一registry/catalog，不引入第五策略 |
| A1 | BLOCKED；535个固定归档中525有观察、10无观察；按实际captured_at选72个attempt，保留2个无观察run阻断。US/CN最新20日均为10/12～11/06，各17 observed、0 qualified；独立机械审查7 PASS/65 BLOCKED | 缺少10/12～14观察；cadence/freshness/最终Actions元数据等仍有失败；人工干预声明未知，不能写0，也不把回抓称按时collector |
| A2 | 正式四策略运行数据限域PASS；已发布cutoff US/CN11/06 | 宽研究训练/VWAP/PIT门禁单列，不全局否决安全的历史Preview |
| A3 | 实际部署desktop/mobile 2 PASS，额外375px 1 PASS；当前本地生产build含321测试PASS，bundle398.77KiB/480KiB；历史视图截图本机检查 | 真实受限账号旅程NOT_TESTED。初次Windows别名路径失败保留，canonical路径构建通过 |
| A4 | **FAIL**；Git/Pages活动壳负测及5个确切formal-run制品JSON扫描未见新operational字段；匿名API直接暴露5条allocation记录 | 生产迁移/Edge部署未执行；授权/无授权/过期/撤权及真实缓存隔离NOT_TESTED；历史Git披露风险待Owner处置 |
| A5 | bounded PASS；当前QQQ和CN27均exact_replay至11/06，无取数/重训 | Owner确认有界口径；不是全策略训练/PIT验收 |
| A6 | isolated PASS；实际静态build在两个新目录恢复为相同405文件；私有checkpoint两次恢复288文件字节一致，篡改拒绝；67个release/checkpoint测试PASS | 当前可验证RC清单与Owner批准的生产演练未闭合，完整A6 BLOCKED |
| A7 | NOT_TESTED；Agent建议Preview/v1均NO-GO | Owner正式签署未发生；绿色CI不代签 |

## P0修复与生产次序

既有表撤销anon SELECT，增加restrictive entitlement floor，保留Pro/Owner且不降低已有Owner策略。
退役行在读取层拒绝，不删除生产行；既有publisher遇public/authenticated/缺失/未知tier必须在任何写入前拒绝。
13个publisher测试及11项**临时本地PostgreSQL合成角色夹具**通过，测试服务已停止。
这些不是生产账号实会话；没有新产品数据库、调度器、回测器或策略注册。

1. Owner审阅并只应用 [确切新SQL](../../../../supabase/migrations/20261108000000_protect_current_operations_preview.sql)，先关闭匿名读。
   不建议bulk `db push`，避免顺带执行未审旧迁移/删除退役行。
2. 部署既有 `alpha-engine-publish-strategy-operations` Edge函数；再复测匿名与隔离授权/拒绝/过期/撤权/缓存隔离。
3. 仅Preview范围的匿名/披露边界真实关闭后再裁定Preview；A1/A4完整实会话/A6/A7未闭合仍不能叫正式v1。

首轮前端CI为120 PASS/3 FAIL：两个测试将可选source-opening上下文误作必填。
已按真实来源合同修正测试：缺声明时要求公开performance与原文SHA/内容一致，并明确observed-range且不显示未经认证的opening wealth；
旧声明来源的严格正例/篡改拒绝仍保留。定向3布局和24项安全/来源测试通过；不改任何密封经济数值或放宽来源校验。

回滚：停止新部署，静态包与私有checkpoint按 [哈希](a6-private-restore.json)恢复到新目录；
必要时仅回滚publisher代码，**保持restrictive SQL floor**，不得把匿名目标重新暴露作为回滚。
不回退私有Git历史、不恢复旧公开writer、不删除失败记录。

原始命令/退出码、脚本SHA及门禁见 [acceptance.json](acceptance.json) 和 [commands.json](commands.json)。
完整本机证据位于 `D:/Documents/AlphaEnginePrivate/Launch-Research/2026-11-08/launch`；
公开材料仅含来源身份、哈希、数量、状态。未执行生产回滚、权限写入或A7发布。
