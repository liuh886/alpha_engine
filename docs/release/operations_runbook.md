# Alpha Engine Research Operations Runbook

本手册覆盖 Python 研究任务、成果包生成和静态 PWA 验收。Alpha Engine 不运行常驻 Web 服务。

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

训练、全历史回放和宽因子扫描属于按契约明确发起的研究任务，不是每日自运行前置步骤。以下命令仅用于相应研究任务：

```bash
make doctor
make data
make train-us        # 或 make train-cn
make backtest
make research-bundle
```

`scripts/setup_cron.py` 的现有模板针对旧的 US 23 名诊断与周研究任务；它不能替代活跃策略闭环，不应作为平台默认自运行安装入口。复用现有工作流，避免再部署一套重复调度器。

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

## 5. 成果包故障

```bash
make research-bundle
```

若 Library 无法打开成果包，依次检查：

1. 根目录是否存在 `alpha-engine-bundle.json`；
2. schema version 是否受支持；
3. manifest 路径是否越界；
4. 文件大小和 SHA-256 是否匹配；
5. 必需成果是否被导出；
6. ZIP 是否为受支持的普通 stored/deflate 格式。

不要修改 manifest 以掩盖缺失文件；应重新生成成果包。

## 6. 静态产品验收

```bash
cd qlib-dashboard
npm ci
npx tsc --noEmit
npm run lint
npm test
npm run build
npx playwright test --config=playwright.static.config.ts
```

必须验证桌面、平板和移动端；浏览器运行期间不得出现数据接口请求、页面错误或旧操作路由。

## 7. 发布前检查

```bash
make ci
```

确认：

- 全仓测试可收集；
- Python 快速与发布契约通过；
- CN Qlib 集成通过；
- 前端单测、构建、PWA 和浏览器验收通过；
- 研究成果声明 `research_only=true`、`trade_ready=false`；
- 旧服务器架构门禁为完成态。
