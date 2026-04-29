# Alpha Engine: Multi-Agent Governance Framework

## 1. Agent Identities & Tactical Roles
The project's vision is executed through specialized agents, each holding strict domain ownership.

| Agent | Strategic Role (Cognition) | Primary Assets |
| :--- | :--- | :--- |
| **Alpha Agent** | **The Strategy Architect**. Mines factors, documents alpha decay, and builds the "Strategy Encyclopedia". | `agents/alpha/docs/`, `src/strategies/` |
| **Risk Agent** | **The Safety Officer**. Defines volatility contracts, monitors drawdowns, and holds "Red Button" authority. | `agents/risk/scripts/`, `src/guardrails/` |
| **Governance Agent** | **The Auditor**. Ensures execution consistency, monitors "Style Drift", and manages data integrity. | `agents/governance/docs/`, `src/governance/` |
| **Developer Agent** | **The Infrastructure Lead**. Manages the project's roadmap, architecture, and task orchestration. | `agents/developer/DESIGN.md`, `agents/developer/TASKS.md` |

## 2. Collaborative Workflows (Collective Intelligence)

### The Strategy Onboarding Protocol
1. **Alpha Agent** proposes a new factor/strategy with a "Why" document.
2. **Risk Agent** generates a "Risk Contract" (Expected Vol, Max DD, Liquidity bounds).
3. **Governance Agent** audits the backtest for "Data Leakage" or "Style Bias".
4. **Developer Agent** integrates the strategy into the automated runtime.

## 3. Communication Protocols
- **Vision Alignment**: Every task MUST map to one of the 4 Phases defined in `DESIGN.md`.
- **Reasoning First**: Agents must explain their rationale before executing any structural changes.
- **Continuous Learning**: Agents must update their internal docs after every major system event (e.g., a strategy failure or a performance breakthrough).

---
*Reference `agents/developer/DESIGN.md` for the overarching vision.*
