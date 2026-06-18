# Alpha Engine: Agent Architecture

## 1. Architecture Overview

The agent system uses a single unified **ResearchAssistant** that consolidates all
capabilities formerly split across Alpha, Risk, Governance, and Developer agents.
An **AgentRouter** provides a thin facade for task dispatch, and **BaseAgent**
offers shared utility methods.

| Component | Role | Location |
| :--- | :--- | :--- |
| **ResearchAssistant** | Unified agent handling research, risk, governance, and architecture tasks | `src/agents/research_assistant.py` |
| **AgentRouter** | Thin facade that routes incoming tasks to ResearchAssistant methods | `src/agents/agent_router.py` |
| **BaseAgent** | Utility base class (context compression, chain-of-thought prompts) | `src/agents/core/base_agent.py` |

## 2. ResearchAssistant Capabilities

The ResearchAssistant exposes tool methods that map to the former agent roles:

| Capability Domain | Method | Origin |
| :--- | :--- | :--- |
| Factor Analysis | `analyze_factors(market)` | Alpha Agent |
| Hyperparameter Tuning | `suggest_hyperparams()` | Alpha Agent |
| Data Quality | `check_data_quality(market)` | Alpha Agent |
| Risk Assessment | `assess_risk()` | Risk Agent |
| Drawdown Monitoring | `check_drawdown(run_id)` | Risk Agent |
| Run Auditing | `audit_run(run_id)` | Governance Agent |
| Consistency Checks | `check_consistency(run_id)` | Governance Agent |
| Self-Healing | `self_heal(event_data)` | Governance Agent |
| Architecture Docs | `describe_architecture()` | Developer Agent |
| Chat Interface | `chat(message)` | Unified |

## 3. Collaborative Workflows

These workflows describe conceptual roles within the single ResearchAssistant,
not separate runtime agents.

### The Strategy Onboarding Protocol
1. **Research (Alpha role)**: Propose a new factor/strategy with a hypothesis.
2. **Risk Assessment (Risk role)**: Generate a risk contract (expected vol, max drawdown, liquidity bounds).
3. **Governance Audit (Governance role)**: Audit the backtest for data leakage or style bias.
4. **Integration (Developer role)**: Integrate the strategy into the automated runtime.

## 4. Communication Protocols
- **Vision Alignment**: Every task must map to one of the 4 Phases defined in `DESIGN.md`.
- **Reasoning First**: The agent explains its rationale before executing structural changes.
- **Continuous Learning**: Internal docs are updated after every major system event.

---
*Reference `DESIGN.md` for the overarching vision.*
