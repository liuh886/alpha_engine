# Alpha Engine

Alpha Engine 的长期定位是个人使用的 **Investment Research Infrastructure（投资研究基础设施）**：复用可信数据、明确历史信息边界，快速验证或否定投资假设，并保留可比较的研究证据。现行 Strategy Console 是其中的正式策略观察应用，不承担研究实验执行或交易委托。

入口：[Strategy Console](https://liuh886.github.io/alpha_engine/)。系统保持 `research_only=true`、`trade_ready=false`。

本地 Agent 从 [AGENTS.md](AGENTS.md) 开始，按[当前产品与交接入口](docs/product/strategy_console.md#local-agent-start-here)定位权威、运行恢复与验收任务。旧任务板和 Research Studio 页面清单只保留历史，不代表当前支持范围。

## 投资研究工作流（本地）

研究者无需为每次假设重新编写数据获取、回测或证据保存脚本。首个可用流程围绕既有的 US Tech Volatility/Reversal Walk-Forward 引擎，支持：

```powershell
# 1. 发现可执行研究模型及其边界
uv run alpha research study list

# 2. 生成研究规格（可修改股票、参数网格、折叠时间与交易摩擦）
uv run alpha research study init --output artifacts/my-volatility-study.json

# 3. 冻结规格后运行：使用已有受治理数据切片，生成研究收据
uv run alpha research study run --spec artifacts/my-volatility-study.json

# 4. 调整另一个研究规格，重跑并对比两份收据
uv run alpha research study compare artifacts/research_studies/<study_id>/<hash_A>.json artifacts/research_studies/<study_id>/<hash_B>.json
```

也可直接执行默认研究：`uv run alpha research study run`。收据保存在 `artifacts/research_studies/<study_id>/<study_hash>.json`，同一证据重复运行不会覆盖旧收据；被阻断的研究仍保留原因，命令退出码为 10。比较必须使用相同研究标的、交易窗口、底层数据哈希和执行代码，否则拒绝比较，避免误导。

**范围限制：** 当前只提供一个经过代码实现的波动率/短期反转研究家族；修改规格不会自动创造新因子。源数据的历史可得性尚不构成完整 PIT 认证；所有结果严格为 `research_only=true`、`trade_ready=false`。详见[研究工作流](docs/product/research_study_workspace.md)。

## 日常使用

- **Overview**：查看正式策略的当前观察、目标变化、下次评估与异常；打开网站直接进入这里。
- **策略详情**：从总览进入，阅读当前决策和正式历史的绩效、风险、持仓、交易、归因及因子证据。
- **Status**：核对当前观察和带日期的数据发布快照；通过现有工作流入口处理延迟或失败。刷新页面不会启动训练、回放或数据抓取。

正式历史证据公开；当前仓位与信号通过既有账户及服务端权限策略读取。观察日期、锁定目标日期和正式历史截止日分别显示。缺失或过期的证据明确标记，浏览器不会从历史回测推断当前仓位。

2026-10-21 起，产品移除了研究浏览器、模型比较、独立报告/因子页面、本地 ZIP/预览导入、营销分享、推荐奖励、离线安装和浏览器权限编辑器。旧 Decision Desk、观察名单及层级/小池轮动实验也退出运行路径。历史研究结果和失败记录保留，删除源码的定位见[归档清单](scripts/archive/ARCHIVE_MANIFEST.json)。

## 唯一权威与边界

| 内容 | 权威 |
| --- | --- |
| 正式策略及 active model 身份 | [策略注册表](configs/strategies/registry.json) |
| 候选池与参考工具 | [候选池注册表](configs/pools/selected_pool_registry_v1.yaml)、[参考工具注册表](configs/pools/reference_instrument_registry_v1.yaml) |
| 正式历史 | 不可变 Model Run Bundle v2 与 formal catalog |
| 当前决策事实 | append-only Strategy Decision Ledger |
| 当前可读状态 | 由上述证据生成的 Strategy Operations 投影 |
| 当前状态读取权限 | 既有服务端策略与账户 entitlement |

`data/research/strategy_operations/`、`qlib-dashboard/public/data/`、索引和缓存均可重建，不是第二套事实库。正式发布继续使用现有原子审核边界。US87/CN130 的来源权限、PIT、生命周期、因子与训练门禁继续生效；某份历史合同阻塞不会阻止读取其他有效证据。

## 本地运行

Python 依赖由 `uv.lock` 固定，前端依赖由 `qlib-dashboard/package-lock.json` 固定。

```powershell
uv sync --extra dev
uv run alpha ops build --generated-at 2026-10-21T07:00:00Z
cd qlib-dashboard
npm ci
npm run dev
```

`--generated-at` 应填写本次构建的真实 UTC 时间；它不改变证据截止日。开发命令会生成正式历史、决策摘要和运行状态三类必要前端投影。

执行仍通过现有 CLI：

```text
alpha data ...                 数据增量准备与 readiness
alpha research ...             显式研究、训练、replay 与 run import
alpha ops record-decision ...  追加不可变策略决策
alpha ops build ...            重建只读状态与健康快照
```

## 验证与运行

只读诊断：`uv run python scripts/doctor.py`。它校验正式分节并复用现有运行健康事实，
按策略报告真实截止日和延迟；未绑定当前运行的训练权限阻塞单独展示。运行延迟或证据校验失败返回非零退出码。

完整本地验证只执行现有 release quality 清单（安装 GNU make 的环境也可用 `make ci`）：

```powershell
uv run python scripts/release_gate.py --run-quality-gates --evidence-dir artifacts/release_gates
```

清单涵盖架构/CI 治理、Python/TypeScript 类型与 lint、Python 测试与 skip 审计、
含单元测试的前端构建、包体预算、浏览器和 Python 打包。每项实际退出码、耗时、输出哈希
以及 Git revision 写入 `artifacts/release_gates/quality_gate_report.json`；单项开发检查继续使用对应工具。


现有 Actions 负责数据、到期评估、决策投递和 Pages 发布。正式回测刷新保留审核与原子发布；日常读取不触发重型研究。工作流数量上限为 39，不为状态读取新增调度器或数据库。

完整规则见 [AGENTS.md](AGENTS.md)、[轻量运行契约](docs/architecture/repository_data_convergence.md#lightweight-operating-contract)、[产品边界](docs/product/strategy_console.md)和 [CI 治理](docs/ci-governance.md)。20 个合格交易时段的连续运行验收仍需真实积累，构建和单测通过不能代替它。
