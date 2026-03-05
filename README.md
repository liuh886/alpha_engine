---
path: 100_Project/2601_Trading/README.md
version: 1.1.0
last_edit_date: 2026-03-03
status: active
priority: tbd
owner_role: product_manager
type: project
---

# Agentic Alpha Engine

[English](#english) | [中文](#中文)

## English

A local-first trading research platform for CN/US markets, combining a Python runtime with an agent-oriented workflow layer.

---

### Module 1: Project Charter

- **Core Goal**: 在禁止自动下单前提下，构建高透明度交易决策 Copilot。
- **Success Criteria (KPIs)**:
  - [ ] Daily routine 稳定成功率持续提升。 #todo/next
  - [ ] 关键失败原因可复现、可归因。 #todo/next
- **Anti-Goals**:
  - [ ] 禁止 direct-broker auto-execution。 #todo/next

### Module 2: Strategy & Key Factors

- **Key Success Factors (KSF)**:
  - 以 `trading_execution_bus` 作为执行路由中枢。
  - 优先解决 inference failure 这类高频影响稳定性的故障。

### Module 3: Architecture & Methods

- **Operational Workflow Bindings**:
  - `100_Project/2601_Trading/Workflows/trading_execution_bus.workflow.md`: Trading Execution Bus
- **Key Paths**:
  - Source: `src/`
  - Scripts: `scripts/`
  - Web UI: `qlib-dashboard/`

### Module 4: Roadmap & Status

- **Current Status**: **Active**（有成功与失败混合信号）。
- **Milestones**:
  - [ ] 建立 daily failure triage 看板
  - [ ] 稳定通过一段连续日常运行
- **Blockers**:
  - Inference failure 尚未形成固定排查闭环。

### Module 5: Next Actions
- [ ] 固化 smoke->daily->dashboard 三段验证顺序。 #todo/next

### Module 6: MCP - Decision Support Skills
This project now supports **Model Context Protocol (MCP)**, allowing it to be used as a "skill provider" for other AI agents.
- **Entrypoint**: `python src/api/mcp_server.py`
- **Exposed Tools**:
  - `get_market_signals(market)`: Returns top trading candidates.
  - `run_backtest(market, start, end)`: Validates strategy performance.
  - `update_market_data(market, lookback)`: Ensures the engine has fresh data.
  - `diagnose_platform()`: Checks for common environment or data gaps.

---

### Run Log

- **2026-03-03**: Upgraded README to LifeOS 4.1.1 compliance; added `trading_execution_bus` workflow binding.
- **2026-03-02**: Established Failure Classification & Attribution Template; performed review of 2026-03-01 Risk Veto.

---

### Quick Start

#### Prerequisites
- Python `>=3.10`
- Node.js + npm
- `uv` (recommended Python runner)

#### Start backend
```bash
uv run python api_server.py
```

#### Start frontend
```bash
cd qlib-dashboard
npm install
npm run dev
```

---

## 中文

一个面向中美市场（CN/US）的本地优先量化交易研究平台，采用 Python 运行时 + Agent 工作流双层架构。
