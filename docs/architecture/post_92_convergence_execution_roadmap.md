# Post-#92 Architecture Convergence Roadmap

Date: 2026-07-11
Status: active execution tracker

## 1. Target architecture

PR #92 established the replacement-first target:

```text
ResearchContract
    -> SignalFrame
    -> PortfolioIntent
    -> EvaluationReport
    -> EvidenceBundle
    -> PromotionDecision
    -> thin adapters
```

The goal is not to add a second framework beside the existing research code. The
goal is to move semantics into a small core and progressively turn old entry
points into compatibility wrappers or presets.

## 2. Execution status

| Stage | Deliverable | Status | Tracking |
|---|---|---|---|
| Foundation | Replacement-first architecture decision | merged | PR #92 |
| Foundation | Structured fixed-10D preparation contract | merged | PR #93 |
| A | Spec-bound execution identity gate | merged | PR #94 |
| B | CN spec-bound Qlib execution adapter | in progress | PR #99 |
| C | US spec-bound Qlib execution adapter | queued after Stage B | Issue #95 |
| D | SignalFrame and PortfolioIntent parity | queued after execution adapters | Issue #96 |
| E | EvidenceBundle and PromotionDecision unification | queued after Stage D | Issue #97 |
| F | Adapter thinning and compatibility deprecation | final convergence stage | Issue #98 |

## 3. Dependency graph

```text
#92 architecture decision
        |
        v
#93 preparation contract
        |
        v
#94 execution identity gate
        |
        v
#99 CN Qlib execution adapter
        |
        +------> #95 US Qlib execution adapter
        |
        v
#96 SignalFrame + PortfolioIntent parity
        |
        v
#97 EvidenceBundle + PromotionDecision unification
        |
        v
#98 adapter thinning and compatibility deprecation
```

Each stage must preserve the fixed-10D contract and must reduce or replace old
semantic ownership. A stage must not add another permanent runner layer.

## 4. Completed foundations

### PR #92 — Architecture decision

- replacement-first direction documented;
- adapter ownership boundaries documented;
- `ResearchSessionConfig`, score-only backtests, specialized runners, and
  `ModelDecisionPack` identified as compatibility surfaces rather than future
  semantic owners.

### PR #93 — Structured preparation contract

- fixed-10D CN/US YAML contracts;
- structured factor libraries;
- Qlib-free contract validation and dry-run preparation;
- stable preparation artifact profile;
- no fake execution or copied evidence;
- corrected CN factor semantics versioned with `:v2` ids.

### PR #94 — Execution identity gate

The following invariant is now enforced before evidence is accepted:

```text
declared execution contract == effective runtime contract
```

Contract-bound fields include:

- market and benchmark;
- universe source hash and requested symbols;
- minimum-symbol and alignment policy;
- factor-library source hash;
- selected factor groups and expressions;
- ranker candidate grid and calibrations;
- factor baselines;
- 10D strategy settings;
- walk-forward dates and embargo;
- evaluation metrics and gate profile;
- artifact profile.

Completed acceptance criteria:

- canonical contract hash is deterministic;
- effective-contract mismatch fails closed;
- mismatch report identifies field paths;
- evidence paths are accepted only when files exist;
- run status remains `research_only=true` and `trade_ready=false`;
- identity-gate tests require no Qlib import.

## 5. Stage B — CN Qlib execution adapter (#99)

### Objective

Replace hard-coded CN evidence-runner semantics with a thin adapter that consumes
`SpecBoundExecutionPlan`.

### Implementation boundary

`src/research/cn_qlib_execution_adapter.py` owns the provider-facing execution
mechanics. `scripts/run_cn_feature_quality_validation.py` becomes a CLI wrapper
that loads a YAML spec, materializes preparation artifacts, and invokes the core
identity gate.

The adapter must consume, not recreate:

- requested universe and minimum-symbol policy;
- alignment mode;
- requested train start and test end;
- first/last test years and minimum windows;
- candidate feature groups and calibrations;
- factor baselines;
- Top-N/Bottom-N settings;
- canonical raw 10D return contract.

Runtime-only evidence may include:

- available-symbol snapshot;
- normalization map;
- retained and dropped symbols;
- aligned train start;
- generated walk-forward windows;
- data-provider identity;
- Qlib calendar range;
- evidence artifact paths.

These runtime fields do not alter the bound contract.

### Merge acceptance checklist

- [x] no module-level frozen candidate grid in the new execution path;
- [x] no hidden `topk=min(3, ...)` override;
- [x] no hard-coded benchmark, train dates, test dates, calibration grid or factor baselines;
- [x] Qlib imports remain lazy and Qlib-free adapter tests exist;
- [x] asymmetric Top/Bottom N fails closed rather than being approximated;
- [x] adapter returns an effective contract reconstructed from consumed values;
- [x] declared/effective identity is checked before evidence paths are accepted;
- [ ] GitHub CI passes on the final PR head;
- [ ] one local CN run produces readiness, windows, stability and decision artifacts, or an explicit auditable skipped result;
- [ ] local run confirms the final `execution_identity.json` has `matched: true`.

The local real-data run is the only Stage B task that cannot be proven by GitHub's
Qlib-free PR test environment.

## 6. Stage C — US Qlib execution adapter (#95)

Implement only after Stage B proves the pattern.

The US adapter must share the same `SpecBoundExecutionPlan` and identity gate.
Market-specific logic is limited to:

- symbol normalization;
- configured data-provider/readiness behavior;
- benchmark and factor library selected by the contract.

It must not introduce a second execution contract, another decision path, or a
new permanent runner framework.

Acceptance criteria:

- declared/effective identity passes;
- no hard-coded dates, benchmark, candidate grid or Top-N override;
- real readiness/windows/stability/decision evidence, or explicit skipped result;
- previous US entry points become wrappers or presets.

## 7. Stage D — SignalFrame and PortfolioIntent parity (#96)

### Replacement target

```text
predictions -> hidden Top-N equal weight -> backtest
```

becomes:

```text
SignalFrame
    -> score_to_equal_weight_intent
    -> PortfolioIntent
    -> EvaluationReport
```

Acceptance criteria:

- old score-based API remains temporarily as a compatibility wrapper;
- deterministic TOP-N equal-weight fixtures produce identical holdings, NAV,
  turnover, costs and metrics through old and new paths;
- portfolio construction is no longer hidden inside evaluation;
- dashboard signal/holding payloads can derive from the same intent object.

Do not add broker orders, live execution, or a broad strategy DSL in this stage.

## 8. Stage E — Evidence and decision unification (#97)

### Replacement target

```text
walk_forward_stability
model gates
ModelDecisionPack
registry stage
adapter status logic
```

converge into:

```text
EvaluationReport -> EvidenceBundle -> PromotionGate -> PromotionDecision
```

`ModelDecisionPack` remains a compatibility report view until all consumers move
to `PromotionDecision`.

Acceptance criteria:

- one promotion status for notebook, API, dashboard, CLI and agents;
- missing data, execution identity, walk-forward or risk evidence fails closed;
- registry stage records a decision but does not justify it;
- trade-ready cannot be set by frontend payloads or adapter metadata;
- decisions contain durable evidence and execution-contract references.

## 9. Stage F — Adapter thinning and deprecation (#98)

After parity and consumer migration:

- specialized runner scripts become presets or are removed;
- `ResearchSessionConfig` becomes a compatibility constructor for
  `ResearchContract`;
- direct score-based backtest entry points become wrappers;
- `ModelDecisionPack` becomes a rendered compatibility view;
- agent prompts submit typed commands instead of owning workflow logic;
- API/dashboard code reads core artifacts and decisions only.

Every removal requires:

- a named replacement;
- a parity test or schema-compatibility test;
- a documented migration window;
- repository search proving no semantic consumer remains.

## 10. Operating rules for every roadmap PR

Every PR must answer these questions in its description:

1. Which existing semantic owner is being replaced or demoted?
2. Which core contract becomes authoritative?
3. Which compatibility entry point remains, and for how long?
4. Which parity, identity or schema test prevents behavioral drift?
5. Which work is explicitly deferred to avoid scope expansion?

A PR should not be merged merely because CI is green. It must also reduce or
consolidate semantic ownership.

## 11. Deferred scope

Do not prioritize these before Stages A-E are stable:

- new model families;
- broad blend-weight searches;
- strategy DSL expansion;
- broker integration;
- paper/live execution;
- order-type completeness;
- additional horizons as primary research contracts.

The primary horizon remains fixed at 10 trading days. Other horizons may later be
used only as robustness diagnostics.
