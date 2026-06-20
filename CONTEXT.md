# Alpha Engine Context

This file defines the durable domain language for Alpha Engine Phase 1
architecture convergence. It is intentionally about business truth and system
boundaries, not about any specific FastAPI endpoint, MCP tool, agent prompt, or
dashboard component.

## Architecture Direction

Alpha Engine SHOULD converge into a small set of deep core modules:

- Domain Model
- Evidence Ledger
- Research Workflow
- Strategy Execution

FastAPI, MCP, Agent, Dashboard, scripts, and CLIs are Adapters. They MAY expose,
automate, or visualize core capabilities, but they MUST NOT own research
semantics, promotion rules, or source-of-truth state transitions.

## Domain Concepts

### ResearchIntent

Definition: A user or system intent that starts research work. It describes what
question is being asked, the target market or universe, constraints, and the
success criteria expected before anything can be promoted.

Key invariants:

- MUST be explicit enough to reproduce the research objective.
- MUST NOT be replaced by a prompt transcript as the only durable record.
- SHOULD include market, horizon, factor family or strategy hypothesis, risk
  limits, and evaluation criteria when known.

Relationships:

- Creates one or more ResearchRuns.
- Provides the rationale used to judge FactorCandidates and PromotionDecisions.
- SHOULD be referenced by EvidenceBundles produced for the intent.

### ResearchRun

Definition: A bounded execution of research work against a ResearchIntent. It
captures the inputs, code/config version references, data window, produced
evidence, and resulting decisions.

Key invariants:

- MUST be reproducible from durable inputs or clearly marked as exploratory.
- MUST link to the ResearchIntent that motivated it.
- MUST NOT be considered successful only because an adapter returned success.

Relationships:

- Produces or updates EvidenceBundles.
- Evaluates FactorCandidates, ModelVersions, and BacktestEvidence.
- May end with a PromotionDecision, a rejection, or an inconclusive result.

### EvidenceBundle

Definition: The canonical package of evidence used to support or reject a
research decision. It groups metrics, diagnostics, artifacts, data references,
backtest results, risk checks, and reviewer notes that belong together.

Key invariants:

- MUST be the center of promotion and rejection decisions.
- MUST identify the evaluated candidate, data window, market, configuration, and
  evaluation code/artifact references.
- MUST distinguish measured facts from interpretation.
- MUST NOT be mutated in a way that changes historical meaning without creating
  a new version or audit entry.

Relationships:

- Belongs to a ResearchRun and may satisfy a ResearchIntent.
- Contains BacktestEvidence and other diagnostics.
- Feeds PromotionGates and PromotionDecisions.
- May justify promoting a FactorCandidate or ModelVersion.

### FactorCandidate

Definition: A proposed alpha factor or feature expression before it has earned a
stable role in strategy execution.

Key invariants:

- MUST have a stable identity based on its expression, implementation, or
  declared calculation semantics.
- MUST NOT be promoted only from in-sample performance.
- SHOULD carry hypothesis, expected behavior, and known failure modes.

Relationships:

- Is evaluated inside ResearchRuns.
- Produces EvidenceBundles through factor analysis, validation, attribution, and
  backtesting.
- May be included in a ModelVersion after passing PromotionGates.

### ModelVersion

Definition: A versioned model or strategy configuration that can be evaluated,
compared, promoted, or rejected. It includes feature set, hyperparameters,
training data scope, and runtime assumptions.

Key invariants:

- MUST be immutable once used for a decision.
- MUST reference the FactorCandidates or feature definitions it depends on.
- MUST have comparable evidence before promotion.

Relationships:

- Produces BacktestEvidence.
- May be promoted or rejected by a PromotionDecision.
- May generate an ExecutionPlan when approved for strategy execution.

### BacktestEvidence

Definition: Evidence produced by simulating a FactorCandidate, ModelVersion, or
strategy configuration over historical data.

Key invariants:

- MUST include data window, universe, benchmark, costs/slippage assumptions, and
  major performance/risk metrics.
- MUST identify whether walk-forward, out-of-sample, or leakage checks were run.
- MUST NOT be treated as sufficient evidence when risk, data quality, or
  reproducibility checks are missing.

Relationships:

- Is part of an EvidenceBundle.
- Supports or blocks PromotionGates.
- Informs PortfolioRiskState and ExecutionPlan constraints.

### PromotionDecision

Definition: A recorded decision to promote, reject, demote, or hold a
FactorCandidate, ModelVersion, or strategy configuration.

Key invariants:

- MUST cite one or more EvidenceBundles.
- MUST include the decision outcome, effective scope, timestamp, and rationale.
- MUST NOT be inferred solely from current registry state.

Relationships:

- Is produced after PromotionGates evaluate EvidenceBundles.
- May change the lifecycle state of FactorCandidates or ModelVersions.
- May allow generation of an ExecutionPlan.

### PortfolioRiskState

Definition: The current risk condition of the portfolio or proposed portfolio,
including drawdown, concentration, exposure, liquidity, and circuit breaker
state.

Key invariants:

- MUST be derived from portfolio data and configured risk limits.
- MUST be checked before execution or promotion that changes live exposure.
- SHOULD explain which risk limit is active when blocking execution.

Relationships:

- Consumes BacktestEvidence and live or simulated portfolio state.
- Constrains ExecutionPlans.
- May block PromotionDecisions when risk gates fail.

### ExecutionPlan

Definition: A concrete plan for running an approved strategy or model. It
translates a PromotionDecision into operational steps, target universe,
scheduling, risk constraints, and rollback or stop conditions.

Key invariants:

- MUST reference the approved PromotionDecision or EvidenceBundle.
- MUST include risk limits and operational assumptions.
- MUST be separated from research evidence so execution changes do not rewrite
  research history.

Relationships:

- Is generated from promoted ModelVersions or strategy configurations.
- Uses PortfolioRiskState before and during execution.
- Is exposed through adapters but owned by the Strategy Execution module.

### Adapter

Definition: A boundary component that exposes core module capabilities to a
human, agent, process, or external interface. Examples include FastAPI routers,
MCP tools, Agent methods, dashboard views, scripts, and CLIs.

Key invariants:

- MUST call core module interfaces for research semantics.
- MUST NOT define independent promotion rules, evidence schemas, lifecycle
  transitions, or risk truth.
- SHOULD be thin enough that replacing the adapter does not change domain
  behavior.

Relationships:

- Presents or invokes ResearchIntents, ResearchRuns, EvidenceBundles,
  PromotionDecisions, and ExecutionPlans.
- Depends on core modules, not the other way around.
- May perform validation at the boundary, but core modules own domain
  validation.

### PromotionGate

Definition: A named decision rule that evaluates whether evidence is sufficient
to move a candidate, model, or strategy to a more trusted lifecycle state.

Key invariants:

- MUST operate on EvidenceBundles or clearly versioned evidence inputs.
- MUST be deterministic for the same evidence and gate configuration.
- MUST explain pass, fail, or inconclusive outcomes.
- SHOULD be versioned when thresholds or required checks change.

Relationships:

- Evaluates EvidenceBundles containing BacktestEvidence and diagnostics.
- Produces inputs to PromotionDecisions.
- May check PortfolioRiskState before allowing execution-facing promotion.

