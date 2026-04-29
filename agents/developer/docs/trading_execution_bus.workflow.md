---
id: project.trading.execution_bus
name: Trading Execution Bus
path: 100_Project/2601_Trading/Workflows/trading_execution_bus.workflow.md
type: task_runner
status: active
version: 1.0.0
last_edit_date: 2026-03-03
project_id: 2601_Trading
context_sources:
  - 100_Project/2601_Trading/README.md
writeback_target: 100_Project/2601_Trading/README.md
---

# Trading Execution Bus

本工作流是 `2601_Trading` 项目的 canonical 执行中枢，负责调度项目内的各种 Python 脚本进行数据更新、回测、模型注册与验证。

## 1. 核心动作映射 (Action Mappings)

| 动作 ID | 描述 | 执行脚本 |
| :--- | :--- | :--- |
| `daily_run` | 日常数据更新与全流程运行 | `python scripts/daily_run.py` |
| `e2e_smoke` | 端到端冒烟测试 (默认 US 市场) | `python scripts/e2e_smoke.py --market us` |
| `build_db` | 构建/刷新 Dashboard 数据库 | `python scripts/build_dashboard_db.py` |
| `agent_entry` | 运行指定 Agent 入口 | `python scripts/agent_entry.py --agent {agent}` |

## 2. 运行逻辑

- 助理应优先通过 `e2e_smoke` 验证环境稳定性。
- `daily_run` 产生的日志与制品应在 `artifacts/` 目录下进行索引。
- 所有的失败信号需归因到 `Daily Routine FAILURE` 分类。

## 3. 依赖项

- Python >= 3.10
- `uv` (推荐环境管理器)
- 环境变量: `AGENT_PASSWORD` (API 鉴权)
