# Alpha Engine Research Operations Runbook

本手册覆盖 Python 研究任务、成果包生成和静态 PWA 验收。Alpha Engine 不运行常驻 Web 服务。

## 1. 日常研究流程

```bash
make doctor
make data
make train-us        # 或 make train-cn
make backtest
make research-bundle
```

每日或每周任务可由 GitHub Actions、标准 crontab 或 Windows Task Scheduler 调用对应脚本。`scripts/setup_cron.py` 可生成本地计划任务模板。

## 2. 日志和证据

优先检查：

- `artifacts/logs/`
- `artifacts/runs/`
- `artifacts/evidence/`
- `artifacts/release_gates/`
- `reports/`
- 研究成果包中的 warnings、blocked gates 和 identity 字段

不要仅根据终端最后一行判断成功。有效运行必须同时具备退出码、成果文件、identity、数据覆盖和质量门禁证据。

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
