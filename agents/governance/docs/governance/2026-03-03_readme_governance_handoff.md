---
title: Governance Handoff from Legacy README
date: 2026-03-03
owner: governance_agent
status: active
---

# Governance Handoff from Legacy README

## Purpose
Capture governance-relevant content that should not stay in a public-facing GitHub README.

## Governance Inputs Migrated

### Rule Authority
- Cross-agent SSOT: `agents/README.md`
- Developer local rules: `agents/skills/developer_agent.skill.md`

### Execution Governance
- Governance execution bus: `agents/governance/workflows/trading_execution_bus.workflow.md`
- Governance workflow: `agents/governance/workflows/governance_execution.workflow.md`

### Operational Governance Signals
- Core operational commands:
  - `python scripts/daily_run.py`
  - `python scripts/e2e_smoke.py --market us`
  - `python scripts/build_dashboard_db.py`
  - `python scripts/doctor.py`
- Data/model artifacts of record:
  - `artifacts/dashboard/dashboard_db.json`
  - `artifacts/metadata/metadata.db`
  - `reports/`

### Prior Governance Log Pointer
- `agents/governance/docs/history/RUNLOG.md`

## Governance Actions Requested
- Keep this document as continuity bridge for README split.
- Continue recording governance execution and incidents in runlog/history artifacts.
- Ensure public README avoids embedding governance control policy as primary content.

## Acceptance
- Governance-specific content from legacy README is preserved in governance-owned path.
