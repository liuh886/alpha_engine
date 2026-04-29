---
path: 100_Project/2601_Trading/agents/governance/workflows/governance_execution.workflow.md
version: 0.1.0
status: active
workflow_role: workflow-governance
workflow_family: trading
primary_output: "Execution compliance, task status integrity, and governance write-back"
writeback_target: 100_Project/2601_Trading/README.md
context_sources:
  - 100_Project/2601_Trading/agents/governance/**
  - 100_Project/2601_Trading/agents/governance/workflows/trading_execution_bus.workflow.md
  - 100_Project/2601_Trading/scripts/README.md
---

## Purpose
Own governance execution rules and auditability of the trading pipeline.

## Responsibilities
- Ensure supported entrypoint routing compliance
- Enforce pass/fail contract integrity and evidence-first completion
- Maintain governance status updates in project README modules

## Not Responsible
- Defining alpha logic
- Defining risk model semantics
