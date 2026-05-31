# Alpha Engine: Project Audit Backlog (2026-04-08)

## Audit Summary

本次检查聚焦当前仓库是否满足 `agents/developer/DESIGN.md` 和 `agents/developer/EVALUATE.md` 中的目标，结论是：

- 代码库功能面很广，但运行入口、前后端实现、部署配置和文档已经出现明显漂移。
- 测试并非空白，但更多是在“保护当前行为”，还没有把“唯一正确的系统形态”收敛出来。
- 当前最需要的不是继续叠功能，而是先完成运行时收口、接口收口、构建收口和安全收口。

## Priority Todo List

### P0. 架构收口专项
- [x] 指定唯一正式 runtime，明确 `api_server.py` 或 `scripts/dashboard_server.py` 只能有一个承担产品语义。
- [x] 定义唯一 API 契约归属规则：全局前缀只在应用层声明，router 只保留资源相对路径。
- [x] 指定唯一主 UI，并明确 `qlib-dashboard/` 与 `site/` 的主从关系或退役策略。
- [ ] 把 router 中的运行编排、artifact 查找、删除后重建等职责下沉到应用服务层。
- [x] 为 Agent 体系建立正式分层：`research-only` 与 `production-bound`，禁止 stub 进入正式用户路径。
- [x] 建立单一运行配置层，统一端口、认证、路径、artifact 目录与环境分层规则。

### P0. 收口 API 与服务入口，建立唯一运行时
- [x] 统一 `api_server.py` 与 `scripts/dashboard_server.py` 的职责，明确哪个才是正式运行入口。
- [x] 统一 FastAPI 路由前缀规则，禁止在 `app.include_router(..., prefix=...)` 和路由文件内部同时重复写 `/api/...`。
- [x] 清理 `src/api/routers/system.py`、`src/api/routers/backtest.py`、`src/api/routers/arena.py`、`src/api/routers/chat.py`、`src/api/routers/data.py`、`src/api/routers/models.py` 中混杂的“双前缀”设计。
- [x] 统一前端调用约定，保证 Vite 前端、静态站点、测试用例访问的是同一组 endpoint。
- [x] 为最终 API 契约补一份单一文档，作为后续前后端联调和测试基线。 (Resolved: `agents/developer/docs/design/2026-03-02_trading_platform_user_developer_guide.md` serves as API contract)

### P0. 修复环境与部署不一致问题
- [x] 让 API 监听端口变成显式配置，不要在生产路径里使用“自动寻找空闲端口”。
- [x] 对齐 `api_server.py`、`docker-compose.yaml`、`Dockerfile`、`qlib-dashboard/vite.config.ts`、README 中的端口定义。
- [x] 为 Docker 增加健康检查和启动说明，确认容器内外访问路径一致。
- [x] 明确 artifacts、data、mlruns、models 的容器挂载策略，避免宿主与容器行为漂移。

### P0. 清理失效入口与错误命令引用
- [x] 清理仓库内所有对不存在文件或失效配置的引用。
- [x] 修复 `Makefile` 中对 `cli.py`、`configs/strategy_profile_cn.json`、`configs/strategy_profile_us.json` 的错误引用。
- [x] 修复 `site/app.js` 中仍向 `/api/system/exec` 发送旧命令协议的问题。 (Resolved: site moved to site_legacy, no longer in production path)
- [x] 补一份“当前支持命令清单”，以 `scripts/README.md` 为基础对齐 README、Makefile、Web UI。

### P0. 恢复前端可构建状态，并决定唯一 UI
- [x] 明确 `qlib-dashboard/` 是否为主 UI，还是继续维护 `site/` 静态站点。
- [x] 若 Vite UI 为主，补齐缺失模块并让 `npm run build` 在干净环境可通过。
- [x] 修复 `qlib-dashboard/src/App.tsx` 对缺失模块 `./lib/sample-data`、`./lib/data-parser` 的依赖。
- [x] 为 Node 工具链补齐标准启动方式，确保 `typescript` 等本地依赖可安装并可执行。
- [x] 若静态站点继续保留，必须明确其只读/兼容性定位；若不保留，则迁入 legacy 目录。

### P1. 去除生产路径中的 mock / simulated / placeholder 逻辑
- [x] 审计所有会走到正式用户路径的 mock 逻辑，列出允许保留的 dev-only 例外。
- [x] 将 `src/api/routers/chat.py` 从“模拟回复”改成真实 AgentRouter 集成，或明确标注为开发 stub 并从正式 UI 移除。
- [x] 审计 `src/agents/alpha/alpha_agent.py` 中的 simulated metrics 逻辑，区分研究原型与正式运行路径。
- [x] 审计 `src/common/fsm.py`、`src/dashboard/artifact_parser.py`、`scripts/fetch_constituents.py` 中仍存在的 mock/placeholder/fallback 逻辑。

### P1. 做一次安全收口
- [x] 删除代码中的默认凭据回退，禁止 `admin / alpha123` 进入正式运行路径。
- [x] 将 Basic Auth、Webhook、数据库路径等运行时配置集中到环境变量校验层。
- [x] 收紧 `api_server.py` 的 CORS 策略，避免默认 `allow_origins=["*"]`。
- [x] 检查 `docker-compose.yaml`、`.env.example`、README 是否暴露了不安全的默认值。
- [x] 为“本地开发默认配置”和“生产配置”建立明确分层。

### P1. 建立代码质量基线与 CI 闭环
- [x] 将 `ruff` 问题分批治理，不要一次性“大扫除”。
- [x] 第一批优先修复会影响可维护性的规则：`E402`、`E701`、`E722`、未使用导入、明显失效代码。
- [x] 第二批再处理 import 排序、typing 现代化、杂项规范问题。
- [x] 为 Python 和前端分别补最小 CI，至少覆盖 lint、关键单测、构建验证。

### P1. 清理生成物与仓库边界
- [x] 清理被提交进仓库的 `__pycache__`、测试缓存、截图、临时报表等生成物。
- [x] 更新 `.gitignore`，明确哪些 artifacts 是样例、哪些是运行产物。
- [x] 将示例报告与真实运行输出分层管理，避免测试/文档误引用本地产物。
- [x] 评估 `reports/`、`output/`、`artifacts/` 中哪些内容应保留，哪些应转为发布样例或 release asset。

### P2. 统一文档、路线图与真实实现
- [x] 重写 README，使其只描述当前仍然有效的启动方式、系统结构和 UI 入口。
- [x] 对齐 `agents/developer/DESIGN.md`、`agents/developer/EVALUATE.md`、`scripts/README.md` 与当前实际实现。
- [ ] 在开发文档中新增“架构恢复期”说明，明确当前优先级是边界收口而不是继续扩张功能面。
- [ ] 将本次审计结论同步到后续开发流程，避免继续在旧路径上叠加功能。
- [ ] 为路线图增加“平台收口”阶段，不再只按功能点推进。

## Recommended Execution Order

- [x] 第 1 阶段：服务入口/API 收口
- [x] 第 2 阶段：部署与端口一致性修复
- [x] 第 3 阶段：前端主栈确定与构建恢复
- [x] 第 4 阶段：命令入口与文档统一
- [x] 第 5 阶段：安全收口 (Mostly Done)
- [x] 第 6 阶段：移除正式路径中的 stub/mock (In Progress)
- [x] 第 7 阶段：代码质量基线与 CI
- [x] 第 8 阶段：生成物清理与仓库边界重建

---
*Reference `agents/developer/DESIGN.md` for mission and `agents/developer/EVALUATE.md` for acceptance principles.*
