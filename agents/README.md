# Agents Layer

This project uses two stable layers:
- Runtime layer: traditional GitHub structure, independently executable.
- Agent layer: identity-based workflows and skills for decision support, governance, and planning.

## Rule Authority (SSOT)
This file is the single source of truth for cross-agent rules.
Do not duplicate global rules in other rule documents.
Agent skill/workflow files should reference this file for shared rules.

### Global Rules
- Keep traditional runtime entrypoints runnable (`api_server.py`, `scripts/`, `qlib-dashboard/`).
- Agent layer extends runtime behavior; it must not replace core runtime executability.
- Domain ownership is strict:
  - `alpha_agent`: factor mining docs and alpha-domain knowledge.
  - `risk_agent`: risk-domain scripts and risk-domain knowledge.
  - `governance_agent`: governance scripts and execution governance knowledge.
  - `developer_agent`: architecture/design/planning docs.
- High-value learning is mandatory for every agent:
  - After each meaningful cycle, distill reusable lessons.
  - Store lessons in the agent-owned domain path.
  - Prefer durable patterns/checklists over one-off notes.
- For new changes, follow SSOT-first updates:
  - Update this file first when changing cross-agent rules.
  - Other files should only reference this authority for shared policy.

## Agent Skills
- `agents/skills/alpha_agent.skill.md`
- `agents/skills/risk_agent.skill.md`
- `agents/skills/governance_agent.skill.md`
- `agents/skills/developer_agent.skill.md`

## Agent Workflows
- `agents/alpha/workflows/alpha_execution.workflow.md`
- `agents/risk/workflows/risk_execution.workflow.md`
- `agents/governance/workflows/governance_execution.workflow.md`
- `agents/developer/workflows/developer_execution.workflow.md`

## Agent Entry
Use the unified entrypoint to start management with an explicit agent identity:
- `python scripts/agent_entry.py --agent governance --market all`
- `python scripts/agent_entry.py --agent alpha --market us`
- `python scripts/agent_entry.py --agent risk --market us`
- `python scripts/agent_entry.py --agent developer --topic "architecture planning"`

## Developer Agent Ownership
All project design and planning documents are owned by `developer_agent`:
- `agents/developer/docs/design/`
- `agents/developer/docs/plans/`

## Domain Ownership
- `alpha_agent`: factor mining docs under `agents/alpha/docs/factor-mining/`
- `risk_agent`: risk domain scripts under `agents/risk/scripts/`
- `governance_agent`: governance scripts under `agents/governance/scripts/`
