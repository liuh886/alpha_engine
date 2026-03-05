---
path: 100_Project/2601_Trading/agents/risk/workflows/risk_execution.workflow.md
version: 0.1.0
status: active
workflow_role: risk-control
workflow_family: trading
primary_output: "Risk decisions, guardrail checks, and failure/risk case records"
writeback_target: 100_Project/2601_Trading/agents/risk/
context_sources:
  - 100_Project/2601_Trading/agents/risk/**
  - 100_Project/2601_Trading/artifacts/**
  - 100_Project/2601_Trading/reports/**
---

## Purpose
Own risk gate and veto responsibilities under the trading system.

## Responsibilities
- Run risk checks on volatility/liquidity/extension/data quality
- Emit pass/block with explicit rationale
- Accumulate reusable risk cases and thresholds

## Not Responsible
- Alpha signal generation
- Governance write-back ownership
