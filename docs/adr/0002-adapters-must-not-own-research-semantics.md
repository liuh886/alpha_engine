# ADR-0002: Adapters Must Not Own Research Semantics

## Status

Accepted

## Date

2026-06-19

## Context

Alpha Engine exposes capabilities through several surfaces: FastAPI, MCP tools,
agent methods, dashboard pages, scripts, and CLIs. These surfaces are useful,
but they have different audiences and operational constraints. If each surface
defines its own meaning for research concepts, the system becomes hard to
reason about and difficult to refactor.

The target architecture separates core modules from adapters:

- Domain Model owns the shared language and invariants.
- Evidence Ledger owns durable evidence and decision records.
- Research Workflow owns research state transitions.
- Strategy Execution owns execution plans and risk-aware runtime behavior.
- Adapters expose those capabilities without redefining them.

## Decision

FastAPI, MCP, Agent, Dashboard, scripts, and CLIs MUST be treated as Adapters.
They MUST call core module interfaces for research semantics, evidence
interpretation, promotion gates, lifecycle transitions, and execution planning.

Adapters MAY validate transport-level input, handle authentication when needed,
format responses, orchestrate a user workflow, or render state. They MUST NOT
own independent rules for promotion, rejection, evidence sufficiency, factor
lifecycle semantics, or risk truth.

The same ResearchIntent, EvidenceBundle, PromotionGate, and PromotionDecision
SHOULD mean the same thing regardless of whether they are accessed through API,
MCP, an agent, a dashboard, or a script.

## Consequences

- Core behavior becomes testable without running every adapter surface.
- Replacing or adding adapters should not change research outcomes.
- Agent automation can become safer because agents ask core modules to make or
  validate decisions instead of encoding private prompt-level rules.
- Dashboard actions should become command/query calls into core modules, not
  hidden domain workflows in the frontend.
- Some existing adapter code may remain temporarily thicker during migration,
  but new business semantics SHOULD be added to core modules first.

## Alternatives Considered

### Keep business logic near each entry point

This is fast for small features and can reduce initial plumbing.

Rejected because Alpha Engine already has multiple entry points. Duplicating
semantics across them makes behavior inconsistent and increases maintenance
cost.

### Make the agent the semantic owner

Let ResearchAssistant interpret research state and decide what actions mean.

Rejected because prompts and conversations are not durable enough to be the
source of truth. Agents should operate through explicit module interfaces and
record their evidence.

### Make the dashboard the workflow owner

Let the dashboard define user-facing lifecycle behavior.

Rejected because the dashboard is an observation and control surface. It should
not be required for headless research, MCP operation, or scripted execution.

