# Alpha Engine

面向个人使用的策略研究与运行监测工具。核心任务只有一条：更新必需数据，按既定节奏评估现有策略，保留决策证据，并在同一个页面说明状态、原因、日期与阻塞。

入口：[Strategy Console](https://liuh886.github.io/alpha_engine/)。系统保持 `research_only=true`、`trade_ready=false`。

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

```powershell
uv run pytest tests -q
uv run python scripts/check_ci_governance.py --output artifacts/ci-workflow-inventory.json --enforce
cd qlib-dashboard
npm exec -- tsc --noEmit
npm run lint
npm run build
npm run check:bundle-budget
npm exec -- playwright test --config=playwright.static.config.ts
```

现有 Actions 负责数据、到期评估、决策投递和 Pages 发布。正式回测刷新保留审核与原子发布；日常读取不触发重型研究。工作流数量上限为 39，不为状态读取新增调度器或数据库。

完整规则见 [AGENTS.md](AGENTS.md)、[轻量运行契约](docs/architecture/repository_data_convergence.md#lightweight-operating-contract)、[产品边界](docs/product/strategy_console.md)和 [CI 治理](docs/ci-governance.md)。20 个合格交易时段的连续运行验收仍需真实积累，构建和单测通过不能代替它。
