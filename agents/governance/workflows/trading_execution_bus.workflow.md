---
path: 100_Project/2601_Trading/agents/governance/workflows/trading_execution_bus.workflow.md
version: 0.3.0
last_edit_date: 2026-03-02
status: active
workflow_role: business-execution
workflow_family: trading
primary_output: "Agent-routed execution bus for Trading operations"
writeback_target: 100_Project/2601_Trading/README.md
context_sources:
  - 100_Project/2601_Trading/README.md
  - 100_Project/2601_Trading/scripts/README.md
  - 100_Project/2601_Trading/agents/alpha/workflows/alpha_execution.workflow.md
  - 100_Project/2601_Trading/agents/risk/workflows/risk_execution.workflow.md
  - 100_Project/2601_Trading/agents/governance/workflows/governance_execution.workflow.md
  - 100_Project/2601_Trading/agents/developer/workflows/developer_execution.workflow.md
task_ids:
  - project.trading.e2e_smoke
  - project.trading.dashboard_db_build
  - project.trading.daily_run
---

## Purpose
Provide a thin, agent-routed execution bus for `100_Project/2601_Trading`.

The bus is orchestration-only; domain rules are owned by agent workflows.

## Agent Responsibility Split
- `alpha_agent`: `agents/alpha/workflows/alpha_execution.workflow.md`
- `risk_agent`: `agents/risk/workflows/risk_execution.workflow.md`
- `governance_agent`: `agents/governance/workflows/governance_execution.workflow.md`
- `developer_agent`: `agents/developer/workflows/developer_execution.workflow.md`

## Bus Responsibilities
- Classify incoming operation and route to the right agent workflow.
- Keep execution order stable: `developer(plan)` -> `alpha(signal)` -> `risk(veto)` -> `governance(execute/writeback)`.
- Prefer registered runtime tasks for P0 entrypoints.

## Routing Classes
- `daily_run`
- `train_and_backtest`
- `rebacktest`
- `arena_settle`
- `dashboard_refresh_or_serve`
- `report_or_export`
- `diagnostic_or_maintenance`

## Runtime Task Bridge (Current)
- `project.trading.e2e_smoke`
- `project.trading.dashboard_db_build`
- `project.trading.daily_run`

## Write-back Discipline
- Final governance write-back target remains `100_Project/2601_Trading/README.md`.
- Domain knowledge writes back to each agent-owned directory.

## Lifecycle
- Status: Active
- Change policy: Keep this file orchestration-only; domain rules remain in agent workflows.
