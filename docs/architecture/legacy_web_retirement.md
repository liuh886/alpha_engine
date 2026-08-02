# Legacy Web Retirement Policy

Status: **Completed — 2026-08-02**  
Parent: #316  
Delivery: #317, #318, #319 and #320

## Final decision

Alpha Engine 的唯一 Web 产品是通过 GitHub Pages 发布、可安装为 PWA 的静态 **Research Artifact Studio**。

浏览器只读取版本化研究成果，不承担身份认证、数据刷新、训练、回测执行、模型变更、任务控制、基础设施操作或交易执行。Python 研究能力通过 CLI、脚本和工作流保留。

## Final boundary

```text
Python services / CLI / scripts / workflows
                  ↓
      versioned research artifact bundle
                  ↓
   GitHub Pages / PWA / local bundle reader
```

- 数据边界：`alpha-engine-bundle.json`；
- 执行边界：Python CLI、脚本和工作流；
- Web 模式：`static_artifact`、`local_artifact`；
- 产品状态：`research_only=true`、`trade_ready=false`。

## Completed removal

### Phase 0 — freeze and inventory

Completed in #317:

- Pages/PWA 和 CLI 成为规范入口；
- 新服务器能力被冻结；
- 迁移清单和 CI 边界建立。

### Phase 1 — frontend product cutover

Completed in #318 through PRs #329 and #334:

- 删除认证、服务探测、任务轮询和 Developer 产品面；
- 生产路由只保留成果审阅；
- Compare、Backtests、Methodology 和名称解析改为成果包原生；
- 物理删除旧页面、HTTP 客户端、mutation/query hooks 和 demo-server 测试；
- 桌面、平板、移动端、零网络取数和离线重载通过。

### Phase 2 — domain extraction and adapter deletion

Completed in #319 through PRs #336 and #337:

- 每个旧适配器完成 artifact-replaced、browser-control-retired、service-owned 或 dead 分类；
- 模型、数据、回测、训练、研究、Evidence、Portfolio 和因子能力均有 Python 所有者；
- 所有 HTTP router、schema 和临时 Python Web host 被删除；
- endpoint 测试迁移为 service、CLI、artifact 或 domain contract；
- 全仓 pytest collection 防止隐藏导入。

### Phase 3 — deployment and runtime deletion

Completed in #320 through PR #346:

- 删除进程管理器、窗口启动器、API 容器、Compose、entrypoint 和健康检查；
- 删除直接 Web 服务器依赖；
- 删除 host、port、跨域、UI 凭据和静态挂载设置；
- Makefile 只保留研究、成果导出、静态 PWA 和质量门禁；
- 本地自动化改为标准 crontab 或 Windows Task Scheduler；
- 回撤风控改为 Python fail-closed 阻断信号；
- 发布、运维、安全和快速开始文档改为成果优先架构。

## Permanent rules

1. 不增加浏览器数据端点或 HTTP 客户端。
2. 不增加认证、轮询、mutation 或系统操作 UI。
3. 新读取需求必须进入版本化成果包契约。
4. 新执行需求必须进入 Python service、CLI、脚本或工作流。
5. 领域逻辑不能只存在于协议适配层。
6. 静态和本地成果模式永久只读。
7. 缺失、不兼容或摘要不匹配的证据必须显式失败。
8. 不得通过恢复本地服务器解决前端需求。

## External protocol exception

MCP JSON-RPC integration 作为独立研究协议保留：

- 不托管前端或静态文件；
- 不成为浏览器运行依赖；
- 不提供恢复旧 Web 产品的理由；
- 传递依赖必须按 MCP 的独立协议边界解释和审查。

## Enforcement

`scripts/check_legacy_web_boundary.py` 要求：

- 退役清单状态为 `completed`；
- active legacy zones 为零；
- 生产仓库中没有旧入口、进程管理、UI 凭据、跨域、服务 host/port 或服务器框架直接依赖；
- 前端没有数据 endpoint literal 或已删除 HTTP 模块。

任何违反项都会在研究测试之前阻断 CI。

## Final product truth

- Web：GitHub Pages/PWA Research Artifact Studio；
- Data：manifest 声明的版本化研究成果；
- Execution：Python CLI、脚本和 GitHub Actions；
- Local files：浏览器本地读取，不上传；
- Scope：研究专用，不构成交易授权。
