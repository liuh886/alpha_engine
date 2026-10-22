# Alpha Engine Research Operations Runbook

本手册覆盖五策略日常观察、受治理研究任务和现行控制台验收。默认入口与安装步骤见 [README](../../README.md)。

## 1. 日常运行与重研究分开

日常闭环由现有 GitHub Actions 调度：数据增量刷新、到期策略评估、追加决策证据、正式证据审核发布、当前状态生成与通知重试。活跃策略以 `configs/strategies/registry.json` 为准。

| 环节 | 现有入口 | 操作边界 |
| --- | --- | --- |
| 正式数据与证据刷新 | Reviewed Formal Backtest Refresh | 保持原有原子发布与审核门禁 |
| 10 日排序策略 | 10D Ranker Current Target | 先检查是否到期；未到期不训练或重放 |
| 日常规则策略 | QQQ Rotation v4.3 Signal Alert、BYD v1.3 Daily Signal | 按冻结契约评估，保留无变化记录 |
| 当前状态 | Publish Strategy Operations Runtime | 读取已验证证据；不触发数据下载或训练 |
| 通知恢复 | Strategy Signal Delivery Outbox | 复用决策账本与投递回执，重试符合门禁的通知 |

本地查看状态只需生成可丢弃的投影，PowerShell 示例：

```powershell
$observedAt = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
uv run alpha ops build --generated-at $observedAt --output artifacts/operations/strategy-operations.json
```

同时读取 `artifacts/operations/system-health.json`：确认市场截止日、各策略正式/决策/因子截止日、到期状态和投递状态。整体 `delayed` 不等于所有策略失效；训练配置受阻也不能自动阻塞未绑定该配置的现有策略。交易所日历用于检查延迟，数据有效性仍由来源证据决定。通知工作流成功不能证明产生了新决策。

训练、全历史回放和宽因子扫描属于按冻结契约明确发起的研究任务，不是每日自运行前置步骤。通过现有登记册选择数据配方和研究命令：

```bash
uv run alpha data --help
uv run alpha data list
uv run alpha research --help
```

旧 Makefile 的全量训练、零门槛回测、周研究和 Artifact Studio 导出便捷入口已退役。
研究计算库和封存证据继续保留；日常调度使用上表中的现有工作流。

## 2. 日志和证据

优先检查：

- `alpha ops build` 生成的策略投影与 `system-health.json`；
- `data/research/model_data_bundle_v1/training-profiles.json` 中具体配置的失败门禁；
- `artifacts/logs/`
- `artifacts/runs/`
- `artifacts/evidence/`
- `artifacts/release_gates/`
- `reports/`
- 研究成果包中的 warnings、blocked gates 和 identity 字段

不要仅根据终端最后一行判断成功。有效运行必须同时具备退出码、成果文件、identity、数据覆盖和质量门禁证据。

少干预运行按现有架构契约连续观察 20 个合格交易时段：在现有诊断与回执中记录各阶段耗时、截止日延迟、人工介入次数、具体阻塞及投递/发布回执。未到期、无变化、节假日、数据延迟和执行失败必须可区分。合法阻塞仍需保留，不能计为成功刷新。

## 3. 任务失败

按以下顺序诊断：

1. `make doctor` 检查环境和路径；
2. 检查数据 provider、截止日期和 coverage；
3. 检查 Snapshot、benchmark 和 universe identity；
4. 检查 label horizon、embargo 和 OOS 窗口；
5. 检查结果是否触发 fail-closed 风控或发布门禁；
6. 修复根因后用相同配置重新运行。

禁止通过补零、缩短未声明窗口、替换当前成分股或忽略失败标的来使任务“通过”。

## 4. 安全停止和重跑

研究任务是前台 CLI 或独立计划任务。停止方式由调用环境负责：

- 本地前台任务：终止当前进程；
- GitHub Actions：取消具体 workflow run；
- crontab/Task Scheduler：禁用对应计划任务；
- 失败后保留已有日志和成果，不覆盖原始证据。

重跑时使用新的 run identity，并保留配置、commit SHA、数据快照和时间边界。

## 5. 正式证据与控制台故障

正式历史以 `data/research/formal_model_runs/catalog.json` 及其声明的 Bundle v2 为准。
检查时复用现有 Formal Bundle v2 Sync 和 Pages 发布校验：

1. 活跃策略集合和正式 catalog 身份一致；
2. manifest 的 SHA-256、路径和 accepted formal 状态有效；
3. 每个可用分节的字节数和 SHA-256 与声明一致；
4. 正式历史与当前观察分别展示真实截止日；
5. 受保护运行状态通过现有鉴权路径读取。

按 README 的构建步骤重建可丢弃的前端投影。旧 Library 本地成果包入口已退役，
不要用旧导出替代正式历史、当前决策或权限失败。
