# ADR-0001: Domain and Evidence First Architecture

## Status

Accepted

## Date

2026-06-19

## Context

Alpha Engine has accumulated research capabilities across agents, MCP tools,
FastAPI endpoints, dashboard pages, scripts, registries, and workflow code. This
made it easy to add features, but it also creates a risk that promotion logic,
research meaning, and evidence interpretation drift across entry points.

Phase 1 architecture convergence sets a clearer target: the durable system
should be organized around a small number of core modules:

- Domain Model
- Evidence Ledger
- Research Workflow
- Strategy Execution

Research decisions are only useful when they can be traced back to evidence.
Backtests, factor diagnostics, risk checks, attribution, walk-forward results,
data quality findings, and reviewer notes need to be grouped into a coherent
record before they can support promotion.

## Decision

All promotion and research decisions MUST be centered on EvidenceBundle.

An EvidenceBundle is the canonical decision input for promoting, rejecting,
demoting, or holding a FactorCandidate, ModelVersion, or strategy configuration.
PromotionGate implementations MUST evaluate EvidenceBundles or clearly versioned
evidence inputs derived from them. PromotionDecision records MUST cite the
EvidenceBundle or bundles that justify the outcome.

Core modules SHOULD treat evidence as durable domain state. Adapters MAY render,
trigger, summarize, or query evidence, but they MUST NOT be the source of truth
for whether evidence is sufficient.

## Consequences

- Promotion logic has a single conceptual anchor instead of being scattered
  across UI actions, MCP tools, agent responses, and scripts.
- Research history becomes easier to audit because decisions point to evidence
  instead of transient execution logs.
- Exploratory work can still exist, but it SHOULD be marked as exploratory until
  sufficient evidence is bundled.
- Existing code may need incremental refactoring where registry state,
  dashboard state, or agent output currently implies a decision without an
  explicit evidence record.
- Evidence schemas and gate versions become long-lived contracts and SHOULD be
  changed deliberately.

## Alternatives Considered

### Registry-first lifecycle

Use the current lifecycle state in registries as the main source of truth.

Rejected because lifecycle state describes an outcome, not the evidence and
rationale that made the outcome defensible.

### Adapter-driven promotion

Allow FastAPI, MCP tools, agent methods, or dashboard actions to each implement
their own promotion checks.

Rejected because it creates semantic drift and makes the same candidate behave
differently depending on the entry point.

### Backtest-only decision records

Use backtest result artifacts as the promotion input.

Rejected because backtests are necessary but not sufficient. Promotion also
depends on data quality, leakage checks, risk state, reproducibility,
attribution, and research intent.

