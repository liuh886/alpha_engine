# 单人本地工作站运行与恢复手册

方向 A / #1281，最新更新 2026-11-02。当前已部署验证为 Pages
`f97d8b55077d85ea7aa559f2146f4817a3a92543`，主线 commit
`4202741d81ba663f551e231e1133e98b061451d4`。官方候选清单见
[`release_candidate_v1_manifest.json`](../evidence/product_v1/release_candidate_v1_manifest.json)。
详细 [A0–A7 状态矩阵](#8-当前放行结论) 给出的 Agent 建议维持 **NO-GO**；
A7 最终放行决策仍由 owner 决定。

## 1. 从当前权威开始

先读 [AGENTS.md](../../AGENTS.md)、[当前 Console 合同](../product/strategy_console.md)、
[单人本地研究 ADR](../adr/0003-single-user-local-quant-research-platform.md)。
策略、候选池、参考工具、正式历史、决策账本各用既有权威；不用旧 Research
Studio 文档恢复页面。只支持现有四策略和显式本地研究，始终 research-only。
W0 权威整理见 [#1283](https://github.com/liuh886/alpha_engine/pull/1283)。

## 2. 锁定环境与配置

在实际仓库目录运行；本机 `alphaengine` 是指向 `alpha_engine` 的目录联接，
Vitest 使用真实 `D:\Documents\GitHub\alpha_engine` 路径，避免 setup 文件解析错误。

```powershell
git status --short --branch
git fetch origin
uv sync --frozen --extra dev
uv run --frozen alpha --help
cd qlib-dashboard
npm ci
```

Python 与前端分别使用 `uv.lock` 和 `package-lock.json`。不要用更新锁文件来
消除验收失败。锁定 Python 安装及 CLI 帮助本轮已执行；全新机器、全新 Node
安装尚未演练，不宣称从零安装已验收。

配置名称看 [环境变量模板](../../.env.example) 和各既有来源合同；实际密钥只放
本机受忽略环境或现有 Actions Secrets。不要在 PR、日志、截图、浏览器打包
或共享回执中保存 provider token、JWT、私钥、service-role key。
QQQ 当前冻结研究合同使用 Yahoo 来源，Tiingo 显式禁用；不得将专业来源要求
误加到该研究重放。其他专业来源合同仍须满足各自门禁。

## 3. 日常只读与本地投影

回到仓库根目录：

```powershell
uv run --frozen python scripts/doctor.py
uv run --frozen python scripts/data/fetch_governed_model_data.py --inspect
uv run --frozen alpha data status qqq-rotation-sgov --cutoff 2026-10-23
$observedUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
uv run --frozen alpha ops build --generated-at $observedUtc --output artifacts/local-review/operations.json
```

本轮 doctor 返回 0，四策略 provider/formal/factor/decision 均至 2026-10-23。
两个研究训练 profile 仍 blocked，不能把它们当成四策略现行观察失败，也不能
把活跃策略健康当成所有研究输入完整。来源 inspect 只核对声明，不证明已取回
归档。日期应为本次实际 UTC；生成时间不会更新原始证据截止日。
本地 operations 文件可能含当前信息，仅供本机审阅，不复制进公开目录。

## 4. 显式研究与来源阻塞

```powershell
uv run --frozen alpha research replay cn_27_v1_3
uv run --frozen alpha research replay qqq_v4_3
```

CN 冻结历史至 2026-09-04 两次复现一致。QQQ 初始通用 CLI 因重复的专业来源
检查退出 2；[#1293](https://github.com/liuh886/alpha_engine/pull/1293) 复用既有权威
验证器后，按原 Yahoo 研究合同三次成功且回执一致，34 项相关测试通过。
该修复仍待审阅/合并；冻结历史经济前缀核验和重新计算的决策路径在回执中
分别说明，不能宣称用当前来源独立重算了全部历史收益。A5 等待 owner 验收。
详见 [#1289](https://github.com/liuh886/alpha_engine/pull/1289)。
需要准备来源时先读 `alpha data prepare --help`，按选定合同明确 cutoff，
复用已核验产品；需要网络刷新必须显式执行。不能前填缺失 bars、改模型/费用/
池或调参来让回放通过。失败实验和来源阻塞保留。

## 5. 正式刷新、发布与故障定位

数据与正式发布继续走现有 `formal-backtest-refresh.yml` 的 provider、计划、
策略及原子 fan-in/审核路径；当前投递用既有 outbox 和 runtime 发布路径。
网页 Refresh 只重读，不能替代来源修复。核对 run/attempt、模型/Bundle 身份、
provider/formal/decision/delivery 各自截止及 due/not-due，再采取现有恢复动作。
恢复细节见[既有运行手册](decision_loop_recovery_2026-10-03.md)。

真实失败 40169478271 的 latest-main `semantic_no_change` 被 `jq -e false`
错误中止，修复 [#1286](https://github.com/liuh886/alpha_engine/pull/1286) 已通过
CI，仍待 owner 审阅和真实恢复观察。不要改写该失败回执或回退挑选旧绿包。
持续运行证据 [#1284](https://github.com/liuh886/alpha_engine/pull/1284) 仍为
US/CN 各 7/20 已观察、0 独立合格；unknown 人工干预不能记成 0。

## 6. 发布前检查与拒绝条件

完整候选质量清单用现有入口，不新增工作流：

```powershell
uv run --frozen python scripts/release_gate.py --run-quality-gates --evidence-dir artifacts/release_gates
```

它会执行完整后端、前端、浏览器与打包验证。本轮质量命令已执行：13 项中
12 项通过，完整后端在测试收集时内存不足而失败。按既有 CI 分片方式运行全部
500 个测试文件后，发现并修复两项仍要求退役 CN x1.2 活跃的过时断言；
[#1295](https://github.com/liuh886/alpha_engine/pull/1295) 的回执记录合计
3938 通过、8 项已批准跳过、0 失败，包含修复后整个受影响分片的重跑。
这是组合后端覆盖；不含另一分支的 QQQ 修复，也不是固定集成候选的新整套证书。
原始失败继续保留，不能将分片结果、PR CI 或 quality-only PASS 当成产品发布许可。候选审批还须提供显式 `--candidate` 对应的精确清单；本轮不带
候选运行 release gate 得到预期退出 2，证明不会默选候选。

实际部署/公开历史/静态保护壳已用现有 verifier 验证 36 个正式分节；额外扫描
发现 CN_27 公共 lineage 含当前 operating_state，见
[#1288](https://github.com/liuh886/alpha_engine/issues/1288)。匿名读取公开 Git 源也
可取得当前账本，因此只修 Pages 不足以闭环；完整边界方案在草稿
[#1291](https://github.com/liuh886/alpha_engine/pull/1291) 等待 #1279 要求的 owner 审阅。**A4 FAIL**，即使
现有 verifier 通过也不能发布为 v1。真实账号过期/撤销与逐策略场景尚未完成。
现行服务端策略均 public 的含义需 owner 复核，本手册不授权改 RLS 或 entitlement。

## 7. 恢复和回滚

本轮只演练了本地静态恢复：从实际成功部署 40157888669 取回 Pages artifact
12585252801，验证 ZIP SHA-256/大小和安全成员，在临时目录解包并经 loopback
服务器验证 36 个分节及 SHA `4a6c7a50e...`。原 data/configs 无差异。
这不证明受保护 runtime 状态恢复，也不批准把含同一隐私问题的旧包部署回去。

真实回滚须先由 owner 审核精确目标 SHA、CI、隐私修复、来源及当前权限影响。
随后使用既有 `deploy-pages.yml` 的 `target_sha` 输入，并用现有
`scripts/verify_pages_release.py --base-url <站点> --expected-commit <完整SHA>`
核对部署和公开历史，再独立核对权限与当前观察。这里的尖括号是待审批输入，
本轮没有执行生产 dispatch、发布或回滚。只恢复获审查的产品产物；不回退或
重写不可变研究包、决策/投递账本，不删有效保留状态，不新增数据库或调度器。

### 7.1 Owner 专属审批与执行边界 (Owner-Only Operations)
以下高风险关键生产操作**严禁自动化 Agent 自行执行，必须由 Owner 独立批准或在本机执行**：
1. **Pages 生产发布与域名切换**: 必须由 Owner 本人执行 `scripts/verify_pages_release.py` 并触发正式部署流水线。
2. **生产环境物理回滚**: 必须由 Owner 亲自审查回滚目标 SHA，确认目标版本不会重新引入已修复的敏感信息泄露 (#1288)。
3. **生产数据库权限与结构迁移**: 针对 `supabase/migrations/20261102000000_retire_cn_x_strategy_operations.sql`（清理 `cn_x` 运行快照与策略），必须由 Owner 在 Supabase 生产控制台或通过安全凭据应用迁移。

## 8. 当前放行结论 (2026-11-02 状态矩阵)

| Gate | 本轮状态 | 现状依据与尚缺事项 |
| --- | --- | --- |
| **A0 身份权威** | **PASS** | 单一 ResearchAssistant 运行；四策略合同与 ADR-0003 唯一权威锁死 |
| **A1 连续运行** | **BLOCKED** | 各市场 12/20 个已观察会话，0 个独立合格；等待自然交易日累积与干预审计 |
| **A2 数据完整性** | **OPS_PASS** | 四策略日常运行输入与复权对账全绿通过；US87/CN130 训练宽表维持范围隔离阻断 |
| **A3 用户路径** | **BASELINE_PASS** | 8 条基础交互路径在桌面与移动端 375px 全绿；未授权/受限旅程无测试账号记为 NOT_TESTED |
| **A4 隐私与安全** | **FAIL** | 主动四大泄露面已止血；生产观测 4 策略均为 public；服务端发布强校验通过；`cn_x` 迁移待 Owner 执行；历史 Git 披露作为已知残留风险待 Owner 签批 |
| **A5 本地研究** | **BOUNDED_PASS** | CN27 精确重放 (容差 $\le 10^{-6}$)，QQQ 真实记录缺源阻断；有界回放口径待 Owner 独立确认 |
| **A6 发布恢复** | **REHEARSAL_PASS** | 篡改证据强制拦截，离线恢复验证通过；生产发布/回滚专属边界明确归属 Owner |
| **A7 owner 决策** | **PENDING_OWNER** | **Agent 综合建议维持：NO-GO**。等待 A1 交易日累积完成与 Owner 最终裁决 |

RDI 独立研究不阻塞本轮；正 alpha、绿色测试或历史收益都不能代替上述验收。
