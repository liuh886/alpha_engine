---
path: 100_Project/2601_Trading/README.md
version: 1.2.0
last_edit_date: 2026-03-10
status: active
priority: tbd
owner_role: product_manager
type: project
---

# Agentic Alpha Engine 🚀

[English](#english) | [中文](#中文)

## English

A local-first trading research platform for CN/US markets, combining a Python runtime with an agent-oriented workflow layer.

---

### Module 1: Project Charter
- **Core Goal**: 在禁止自动下单前提下，构建高透明度交易决策 Copilot。
- **Success Criteria (KPIs)**:
  - Daily routine 稳定成功率持续提升。
  - 关键失败原因可复现、可归因。

---

### Module 2: PM2 Service Deployment 🛠️
To start all AlphaEngine services (API, Web, MCP) simultaneously as a robust system service:

1. **Prerequisites**: Install `pm2` globally.
   ```bash
   npm install -g pm2
   ```

2. **Start Services**:
   ```bash
   pm2 start ecosystem.config.js
   ```

3. **Check Status**:
   ```bash
   pm2 list
   pm2 logs
   ```

**Services Included**:
- `alpha-api`: FastAPI backend for core logic (Port 8000).
- `alpha-web`: Vite-based interactive dashboard (Port 5173).
- `alpha-mcp`: Model Context Protocol server for AI agent integration.

---

### Module 3: Bot & AI Agent Connection Guide 🤖
AlphaEngine is **Agent-Ready**. You can connect your favorite AI assistants (Claude Desktop, Cursor, Windsurf) to use the engine as their quantitative "brain".

#### 1. Integration Method (MCP)
Add the following configuration to your agent's setting file (e.g., `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "alpha-engine": {
      "command": "uv",
      "args": ["run", "python", "[FULL_PATH_TO_PROJECT]/src/api/mcp_server.py"],
      "env": {
        "PYTHONPATH": "[FULL_PATH_TO_PROJECT]"
      }
    }
  }
}
```

#### 2. Capabilities for Agents
Once connected, any Bot can:
- **`get_market_signals(market)`**: Analyze the current market (CN/US) and return high-conviction candidates.
- **`run_backtest(market, start, end)`**: Execute strategy validation and return performance metrics (Sharpe, MDD).
- **`repair_market_data(market)`**: Handle data gaps autonomously when the engine reports missing info.
- **`diagnose_platform()`**: Self-check environment health.

---

### Module 4: Architecture & Key Paths
- **Source**: `src/` (Core logic, Inference, Reliability)
- **API**: `api_server.py` (FastAPI)
- **Web UI**: `qlib-dashboard/` (Vite + React)
- **Agent Tools**: `src/agents/tools/` (Specialized skills for Advisors)

---

### Run Log
- **2026-03-10**: Finalized **PM2 Service Architecture** and **Bot Connection Guide**; decoupled Inference from Orchestrator.
- **2026-03-03**: Upgraded README to LifeOS 4.1.1 compliance.

---

## 中文 (快速启动)

### 1. PM2 一键启动方案
本项目支持通过 PM2 同时启动后端 API、前端看板以及 AI 助手所需的 MCP 服务：

```bash
# 确保安装了 PM2
npm install -g pm2

# 启动所有服务
pm2 start ecosystem.config.js

# 查看运行状态
pm2 list
```

### 2. 智能体 (Bot) 连接指南
您可以让 Claude, Cursor 或 Windsurf 直接调用 AlphaEngine 的量化能力。在您的配置文件中添加：

```json
{
  "mcpServers": {
    "alpha-engine": {
      "command": "uv",
      "args": ["run", "python", "绝对路径/src/api/mcp_server.py"]
    }
  }
}
```

**Bot 可调用的能力**:
- **市场分析**: 询问“今天美股有什么推荐标的？” -> 触发模型推理。
- **回测验证**: 询问“帮我回测这个策略在 2024 年的表现。” -> 获取 Sharpe 与最大回撤。
- **数据管理**: 自动修复数据缺失，确保分析的 Grounding（真实性）。
