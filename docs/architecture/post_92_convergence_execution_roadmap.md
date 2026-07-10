# Post-#92 Architecture Convergence Roadmap

Date: 2026-07-11
Status: active

## 1. Purpose

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

## 2. Current position

### Completed: architecture decision (#92)

- replacement-first direction documented;
- adapter ownership boundaries documented;
- `ResearchSessionConfig`, score-only backtests, specialized runners, and
  `ModelDecisionPack` identified as compatibility surfaces rather than future
  semantic owners.

### Completed: structured preparation contract (#93)

- fixed-10D CN/US YAML contracts;
- structured factor libraries;
- Qlib-free contract validation and dry-run preparation;
- stable preparation artifact profile;
- no fake execution or copied evidence;
- corrected CN factor semantics versioned with `:v2` ids.

### In progress: spec-bound execution identity gate

This PR adds the rule:

```text
declared execution contract == effective runtime contract
```

Evidence cannot be accepted unless the identity gate passes.

## 3. Dependency graph

```text
#92 architecture decision
        |
        v
#93 preparation contract
        |
        v
A. execution identity gate  <--- current PR
        |
        v
B. CN Qlib execution adapter
        |
        +------> C. US Qlib execution adapter
        |
        v
D. SignalFrame + PortfolioIntent parity
        |
        v
E. EvidenceBundle + PromotionDecision unification
        |
        v
F. adapter thinning and compatibility deprecation
```

Each stage must preserve the fixed-10D contract and must reduce or replace old
semantic ownership. A stage should not add another permanent runner layer.

## 4. Stage A — Execution identity gate

### Objective

Create one core gate that accepts execution evidence only when the runtime proves
that it used the exact declared contract.

### Contract-bound fields

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

### Acceptance criteria

- canonical contract hash is deterministic;
- effective contract mismatch fails closed;
- mismatch report identifies field paths;
- evidence paths are accepted only when files exist;
- run status remains `research_only=true` and `trade_ready=false`;
- no Qlib import is required by the identity-gate tests.

## 5. Stage B — CN Qlib execution adapter

### Objective

Replace hard-coded CN evidence runners with a thin adapter that consumes a
`SpecBoundExecutionPlan`.

### Required refactor

Extract execution logic from `scripts/run_cn_feature_quality_validation.py` into a
core adapter. The script should become a CLI wrapper only.

The adapter must consume, not recreate:

- requested universe and min-symbol policy;
- alignment mode;
- requested train start and test end;
- first/last test years and minimum windows;
- candidate feature groups and calibrations;
- factor baselines;
- Top-N/Bottom-N settings;
- canonical raw 10D return contract.

### Runtime additions

The effective execution result may add non-contract runtime evidence such as:

- available-symbol snapshot;
- retained and dropped symbols;
- aligned train start;
- generated walk-forward windows;
- data-provider identity;
- Qlib calendar range;
- evidence artifact paths.

These runtime fields do not change the bound contract.

### Acceptance criteria

- no module-level frozen candidate grid in the execution path;
- no hidden `topk=min(3, ...)` override;
- no hard-coded benchmark or dates;
- adapter effective contract is constructed from values actually passed to Qlib;
- declared/effective identity passes before stability or decision evidence is
  exposed;
- one local CN run produces real readiness, windows, stability, and decision
  artifacts or an explicit skipped result.

## 6. Stage C — US Qlib execution adapter

Implement only after the CN adapter proves the pattern.

The US adapter should share the same core execution interface. Market-specific
logic should be limited to symbol normalization, data readiness, and configured
factor libraries. It must not introduce a second execution contract.

## 7. Stage D — SignalFrame and PortfolioIntent parity

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

### Acceptance criteria

- old score-based API remains as a compatibility wrapper;
- deterministic TOP-N equal-weight fixtures produce identical NAV, turnover,
  costs, and metrics through old and new paths;
- portfolio construction is no longer hidden inside evaluation;
- dashboard signal/holding payloads can derive from the same intent object.

## 8. Stage E — Evidence and decision unification

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
EvidenceBundle -> PromotionGate -> PromotionDecision
```

`ModelDecisionPack` remains a compatibility report view until all consumers move
to `PromotionDecision`.

### Acceptance criteria

- one promotion status for notebook, API, dashboard, CLI, and agents;
- missing data, execution identity, walk-forward, or risk evidence fails closed;
- registry stage records a decision but does not justify it;
- trade-ready cannot be set by frontend payloads or adapter metadata.

## 9. Stage F — Adapter thinning and removal plan

After parity and consumer migration:

- specialized runner scripts become presets or are removed;
- `ResearchSessionConfig` becomes a compatibility constructor for
  `ResearchContract`;
- direct score-based backtest entry points become wrappers;
- agent prompts submit typed commands instead of owning workflow logic;
- API/dashboard code reads core artifacts and decisions only.

Every removal should have:

- a named replacement;
- a parity test or schema-compatibility test;
- a documented migration window;
- repository search proving no semantic consumer remains.

## 10. Work that should remain deferred

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
