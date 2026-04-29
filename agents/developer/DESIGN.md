# Alpha Engine: Vision & Architectural Blueprint

## 1. The North Star (Mission)
Alpha Engine is an **AI-Native Quantitative Investment Collective**. Our mission is to transform raw market data into actionable high-alpha strategies through a synergistic collaboration between Human Intuition and Machine Intelligence.

We do not just build "bots"; we build a **Multi-Agent Decision Engine** where each agent represents a specialized domain of investment excellence.

## 2. Core Architectural Pillars

### A. The Bionic Loop (Human-in-the-Loop)
- **Machine Responsibility**: Exhaustive factor mining, statistical backtesting, and real-time risk monitoring.
- **Human Responsibility**: Defining "Intent", qualitative strategy attribution, and defining the "Ethical & Risk Guardrails".

### B. Runtime vs. Cognition
- **Runtime Layer (Execution)**: High-performance Qlib-based backtesting, MLflow experiment tracking, and FastAPI delivery.
- **Cognition Layer (Agents)**: LLM-driven reasoning, document-based knowledge management, and collaborative task orchestration.

## 3. The Roadmap (Evolutionary Path)

### Phase 1: The Robust Foundation (Current)
- **Objective**: Zero-friction deployment and deterministic reporting.
- **Key Milestones**: Cross-environment parity (Win/Linux), Automated HTML report generation, and multi-market (CN/US) data routing.

### Phase 2: The Collective Intelligence (Next)
- **Objective**: Agent Knowledge Synthesis.
- **Key Milestones**: 
    - **Strategy Encyclopedia**: Alpha Agent records findings into a searchable knowledge graph.
    - **Risk Guardrails**: Risk Agent dynamically generates "Safety Contracts" for each strategy.

### Phase 3: Autonomous Adaptation
- **Objective**: Self-Healing Portfolio.
- **Key Milestones**: 
    - **Style Drift Detection**: Governance Agent monitors alpha decay and triggers model re-training.
    - **Dynamic Weighting**: Real-time allocation based on agent-consensus and market regime detection.

### Phase 4: The Sovereign Fund
- **Objective**: Fully autonomous Alpha generation across Global Markets.
- **Key Milestones**: Multi-currency arbitrage, cross-market hedging, and Agent-led capital allocation.

## 4. Governance Principles
1. **Design Before Code**: No logic enters the system without a documented "Why" in the Agent layer.
2. **Attribution Over Prediction**: We prioritize understanding *why* a strategy made money over pure black-box performance.
3. **Safety First**: The Risk Agent has the "Red Button" authority to halt any execution that violates the volatility/drawdown contracts.

## 5. Current Architectural Gaps (2026-04 Audit)

The current codebase has crossed the line from isolated implementation debt into structural architectural drift. The main issue is not lack of features, but lack of a single authoritative shape for the system.

### A. Dual Runtime Truth
- The project currently exposes two competing server shapes: `api_server.py` and `scripts/dashboard_server.py`.
- This violates the intended Runtime Layer principle because API behavior, static asset serving, and tests are not anchored to one production runtime.
- Architectural correction: define one canonical runtime, and downgrade the other entrypoint to either a compatibility shim or a test fixture.

### B. API Contract Drift
- API prefixes are currently split across application mounting and router-local declarations.
- This creates accidental routes instead of an intentional interface contract.
- Architectural correction: the application shell owns global prefixes; routers own only resource-local paths.

### C. UI Boundary Drift
- The system currently carries two UI stacks: `qlib-dashboard/` and `site/`.
- Their relationship is undefined, but both encode product behavior and API assumptions.
- Architectural correction: establish one primary product UI. Any secondary UI must be explicitly categorized as `legacy`, `static export`, or `support surface`.

### D. Application Logic Leaking into Transport Layer
- API routers currently perform orchestration and artifact lookup duties that belong in application services.
- This weakens the separation between transport, use-case orchestration, and domain/runtime concerns.
- Architectural correction: routers validate input and shape responses only; workflow, artifact, and run-state orchestration belong in explicit service/use-case modules.

### E. Agent Layer Not Yet Production-Bound
- The intended Cognition Layer is strategically important, but parts of the current implementation still depend on simulated or stubbed behavior.
- This is acceptable for research prototypes, but not inside formal production paths governed by `EVALUATE.md`.
- Architectural correction: split agent capabilities into two classes:
  - Research agents: experimental, allowed to use mocks, never part of production-critical flows.
  - Production agents: real tools, real state, real audit trail, no placeholder reasoning.

### F. Configuration Model Fragmentation
- Port binding, auth defaults, runtime paths, artifact directories, and Docker behavior are distributed across multiple files and entrypoints.
- The current path model also mixes static constants with dynamic attribute lookup, making environment behavior harder to reason about.
- Architectural correction: centralize runtime configuration into one explicit configuration layer with separate `dev`, `test`, and `prod` semantics.

## 6. Architecture Recovery Principles

The next stage of the project is not feature expansion first. It is architecture recovery.

1. **One Runtime**: There must be one production server shape and one authoritative deployment path.
2. **One Contract**: Frontend, tests, scripts, and docs must all target the same API contract.
3. **One Primary UI**: Product behavior can only have one primary interaction surface.
4. **Strict Layering**: Transport, orchestration, domain logic, and cognition must have clear ownership boundaries.
5. **Production Means Real**: Any production-visible path must use real execution, real data, and real traceability.
6. **Config Is a System**: Runtime configuration must be explicit, validated, and environment-aware.
7. **Docs Must Describe Reality**: This design document must evolve with the real architecture, not the aspirational one alone.

---
*This document is the Single Source of Truth for the project's destiny.*
