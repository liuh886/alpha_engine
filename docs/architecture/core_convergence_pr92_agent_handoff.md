# PR #92 Local Agent Handoff Checklist

Date: 2026-07-09
PR: `docs(architecture): define replacement-first core convergence plan`
Scope: final review and cleanup for a docs-only architecture PR.

## 1. Mission

Bring PR #92 to merge-ready quality without expanding scope.

This PR is not the implementation PR. It defines the architecture convergence direction and the replacement/deprecation plan that later coding PRs should follow.

The local agent should verify clarity, consistency, and merge readiness. It should not implement `ResearchContract`, `PortfolioIntent`, `PromotionDecision`, or `ExperimentSpec` in this PR.

## 2. Core decision to preserve

The central decision is:

```text
ResearchContract
        ↓
SignalFrame
        ↓
PortfolioIntent
        ↓
EvaluationReport
        ↓
EvidenceBundle
        ↓
PromotionDecision
        ↓
Thin adapters
```

The architecture is replacement-first, not additive-first.

That means the PR must clearly communicate that existing scattered semantics should be replaced, demoted, or wrapped rather than surrounded by more layers.

## 3. Required final checks

### 3.1 Document consistency

Check that the main architecture document consistently uses these terms:

- `ResearchContract`
- `SignalFrame`
- `PortfolioIntent`
- `EvaluationReport`
- `EvidenceBundle`
- `PromotionDecision`
- `ExperimentSpec`
- compatibility wrapper
- adapter surface
- stable semantic core

Avoid introducing additional near-synonyms such as:

- research package
- strategy contract
- model intent
- trading intent
- execution decision
- decision pack as source of truth

Only add new terms if they are clearly defined and needed.

### 3.2 Replacement stance

Confirm the document explicitly says these are compatibility surfaces rather than long-term semantic owners:

- `ResearchSessionConfig`
- direct score-based `run_vectorized_backtest(predictions, returns)`
- specialized evidence runner scripts
- `ModelDecisionPack` as an independent decision layer
- model registry stage as implied truth
- dashboard/API/agent-specific decision rules

Do not weaken this language into vague wording such as "may evolve later". The point of the PR is to force architectural convergence.

### 3.3 Scope guardrails

Confirm the PR still says:

- no runtime behavior changes;
- no model training changes;
- no data changes;
- no dashboard/API behavior changes;
- no broker integration;
- no live trading;
- no new strategy DSL;
- no new model families before contract convergence.

### 3.4 Migration safety

Confirm each replacement path has a safe migration rule:

- keep old entry points temporarily;
- add parity tests before internal replacement;
- mark old entry points as compatibility wrappers;
- do not delete user-facing workflows in the first pass;
- move new semantics into core modules only.

### 3.5 10D research discipline

Confirm the fixed-10D contract remains explicit:

- primary horizon is 10 trading days;
- primary rebalance cadence is 10 trading days;
- processed labels are training targets only;
- economic evaluation uses raw forward returns;
- evidence must fail closed when data readiness or walk-forward coverage is insufficient.

## 4. Allowed changes in this PR

The local agent may:

- fix wording;
- improve headings;
- remove repetition;
- add cross-references to existing ADRs or docs;
- clarify the replacement/deprecation table;
- tighten acceptance gates;
- update the PR body or add a PR comment;
- run markdown or repository validation if available.

## 5. Disallowed changes in this PR

The local agent must not:

- add runtime Python modules;
- add domain dataclasses;
- modify backtest behavior;
- modify runner scripts;
- modify API routes;
- modify dashboard code;
- modify model gates;
- modify evidence calculations;
- change data alignment behavior;
- add broker, paper-trading, or live-trading code;
- add new model families;
- delete existing user-facing scripts or endpoints.

If the local agent finds code changes that seem necessary, it should open or draft the next PR instead of expanding PR #92.

## 6. Suggested local validation

Because this is docs-only, the minimum validation is:

```bash
git diff --stat main...HEAD
git diff -- docs/architecture/core_architecture_convergence_plan_20260709.md docs/architecture/core_convergence_pr92_agent_handoff.md
```

If the repository has a standard full validation command and it is cheap enough locally, run it as an optional confidence check:

```bash
./validate_all.ps1
```

If full validation is slow or environment-dependent, do not block the PR solely on it. Record that the PR is docs-only and no runtime tests were required.

## 7. Merge-ready criteria

PR #92 is merge-ready when:

- it remains docs-only;
- the main document clearly argues for replacement-first convergence;
- the handoff checklist is present;
- the PR body summarizes replacement decisions, not just additions;
- no implementation work is mixed into the architecture PR;
- the next coding PR is clearly identified as `PR A — Domain replacement contracts`.

## 8. Next PR prompt

After PR #92 is merged, use this as the first coding task:

```text
Implement PR A — Domain replacement contracts for AlphaEngine.

Goal:
Introduce the replacement vocabulary for the core architecture without changing runtime behavior.

Add a small domain-contract layer for:
- ResearchContract
- DataSnapshotRef
- UniverseSnapshotRef
- FeatureSetRef
- LabelContract
- SplitContract
- SignalFrameMetadata
- PortfolioIntentMetadata
- EvidenceRef
- PromotionDecision

Constraints:
- Do not initialize Qlib at import time.
- Do not import LightGBM, FastAPI, dashboard code, or runner scripts from the domain-contract modules.
- Do not change existing runner output.
- Do not change vectorized backtest behavior.
- Do not change model decision results.
- Do not add broker/live/paper execution.
- Keep ResearchSessionConfig working as a compatibility-facing object.

Tests:
- Add JSON-compatible round-trip tests for each contract.
- Add validation tests for empty required ids, invalid primary horizon/rebalance days where applicable, and missing symbol/universe metadata where applicable.
- Add an import-safety test proving the new domain-contract package imports without Qlib.

Deliverable:
A small, boring PR that establishes stable vocabulary only. No training, no research rerun, no dashboard/API behavior change.
```
