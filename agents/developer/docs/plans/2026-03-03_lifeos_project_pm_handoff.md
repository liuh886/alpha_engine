---
title: LifeOS Project PM Handoff - Trading (2601)
date: 2026-03-03
owner: developer_agent
status: active
---

# LifeOS Project PM Handoff - Trading (2601)

## Purpose
Move project-management content previously embedded in root README into a PM-owned LifeOS management artifact.

## Source
- Previous management-style README (`README.md` before 2026-03-03 rewrite).

## PM Intake Summary

### Project Charter
- Project ID: `2601_Trading`
- Mission: Local-first CN/US trading copilot with agent-routed execution and strict risk boundaries.
- Product boundary:
  - Decision support only
  - No broker auto-execution
  - Focus: research -> backtest -> risk -> review

### Strategy and Priorities
- Keep runtime and agent layers decoupled.
- Route major operations through governance execution bus.
- Priority tracks:
  - Daily-run stability and data-feed reliability
  - Strict train/inference feature contract
  - Environment consistency hardening

### Architecture Decisions (PM-relevant)
- Runtime layer remains independently runnable: `src/`, `scripts/`, `api_server.py`, `qlib-dashboard/`.
- Agent layer hosts intelligent workflows and domain ownership: `agents/`.

### Roadmap Snapshot
- P0: e2e smoke, daily run, dashboard DB build, runtime health checks
- P1: data quality recoverability, drift observability
- P2: operator workflow ergonomics in dashboard/reporting

### Next Actions (from prior README)
- Run `project.trading.e2e_smoke` after major runtime updates.
- Keep `project.trading.daily_run` and `project.trading.dashboard_db_build` in sync with execution bus.
- Add one regression check for data-feed interruption recovery path.

## PM Governance Notes
- Cross-agent rule SSOT remains: `agents/README.md`.
- Design/plan ownership remains: `agents/developer/docs/{design,plans}/`.
- This handoff doc is PM intake material, not rule authority.

## Acceptance
- PM management content extracted from root README and preserved.
- Root README can now be optimized for GitHub sharing without losing PM context.
