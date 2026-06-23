# AlphaEngine V2

## 极简、优雅、自包含的量化策略研究引擎

### 1. Quick Start: Demo Mode

最快体验 AlphaEngine 的方式是启动 Demo Mode，无需真实数据即可查看完整 Dashboard。

> **Note:** This project uses [Astral `uv`](https://astral.sh/uv/) for dependency management. `uv.lock` is the source of truth.

```bash
# 安装 Python 依赖
uv sync

# 安装前端依赖
cd qlib-dashboard && npm ci && cd ..

# 启动 Demo 模式
uv run python api_server.py --demo
```

打开 http://localhost:8000，任意用户名/密码登录即可。

**你应该看到：**
- ✅ **Demo Mode** 标签显示在页面顶部
- ✅ Dashboard 展示 Equity Curve 图表
- ✅ Holdings 标签页显示 SH600000 持仓
- ✅ Attribution 标签页显示归因数据

### 2. 本地开发 (Full Mode)

```bash
# 启动后端 (默认端口 8000)
uv run python api_server.py

# 启动前端开发服务器 (在 qlib-dashboard 目录下)
cd qlib-dashboard && npm run dev
```

访问 `http://localhost:5173` (开发模式) 或 `http://localhost:8000` (生产模式) 查看策略看板。

### 3. Release Validation

```powershell
.\validate_all.ps1
```

运行 11 个质量门禁：Ruff lint、Mypy、Pytest、TypeScript check、前端 lint、单元测试、构建、E2E 测试等。

### 2. 核心架构
- **单一运行时**: 所有 API 请求都通过 `api_server.py` 路由。
- **Agent 驱动**: 内置 Alpha, Risk, Governance, Developer 四大 Agent 协同工作。
- **Qlib 集成**: 底层基于微软 Qlib 量化框架，支持多种市场和特征包。
- **架构收敛交接**: Phase 1-6 重构规则与任务边界见 docs/architecture/phase_1_6_agent_handoff.md。
- **发布文档**: 安装、配置、运维、安全、性能、合同见 docs/release/index.md。
- **工作成果总结**: 见 docs/release/work_summary_20260620.md。

### 3. 任务管理 (Makefile)
使用 `Makefile` 快速执行常用任务：
- `make data`: 更新市场数据。
- `make train-us` / `make train-cn`: 训练模型。
- `make backtest`: 运行回测流水线。
- `make breakfast`: 生成每日晨报。

### 4. 容器化部署
推荐使用 Docker Compose 进行一键部署：
```bash
docker-compose up -d
```
API 服务将运行在 `8000` 端口，前端已集成在容器内由 FastAPI 直接挂载。

---
*更多细节请参考 `agents/developer/DESIGN.md` 和 `scripts/README.md`。*

