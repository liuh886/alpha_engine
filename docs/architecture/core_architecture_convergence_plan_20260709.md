# AlphaEngine Core Architecture Convergence Plan

Date: 2026-07-09
Status: proposed
Scope: architecture and refactor plan only; no runtime, model, data, broker, or dashboard behavior changes in this PR.

## 1. Revised conclusion

The convergence target must not be additive-only.

The previous plan correctly identified the target direction, but it was still too easy to read it as: add `TargetWeightFrame`, add `PortfolioIntent`, add manifests, add dry-run ledgers, add more workflow types. That would increase surface area before reducing ambiguity.

The corrected target is:

> Replace scattered research semantics with one small evidence-first core, replace score-only backtests with a weight/intent contract, and simplify adapters into thin command/query surfaces.

The intended architecture is therefore not a larger system. It is a smaller core with clearer ownership:

```text
ResearchContract
  = DataSnapshot + UniverseSnapshot + FeatureSet + LabelContract + SplitContract
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
Adapters: Notebook / Script / API / Dashboard / Agent
```

The important change from the prior plan is that several existing concepts should be replaced or demoted, not merely surrounded by new abstractions.

## 2. External repository lessons

This plan reviewed AlphaEngine against mature open-source quantitative repositories. The lesson is not to copy any single framework, but to choose the smallest set of ideas that fits AlphaEngine's fixed-10D, evidence-first research goal.

| Repository | Strong architecture lesson | What AlphaEngine should adopt | What AlphaEngine should not copy now |
|---|---|---|---|
| `microsoft/qlib` | Full AI-oriented quant platform spanning data processing, model training, backtesting, alpha seeking, risk modeling, portfolio optimization, and execution. | Keep Qlib as lower-level market data/model infrastructure; expose a stricter AlphaEngine research contract above it. | Do not reimplement Qlib's whole platform surface. |
| `polakowo/vectorbt` | Matrix/vectorized research, large parameter sweeps, portfolio analytics, interactive exploration. | Adopt grid-manifest thinking and high-throughput experiment surfaces for feature/model grids. | Do not let speed-first parameter search override evidence gates or fixed-10D contracts. |
| `pmorissette/bt` | Reusable strategy logic blocks and composable algo stacks. | Use small composable transforms for score-to-weight, allocation, and risk overlay. | Do not build an unconstrained strategy DSL before core contracts stabilize. |
| `AI4Finance-Foundation/FinRL-Trading` | Weight-centric interface: downstream backtest/execution consumes target portfolio weights. | Adopt `PortfolioIntent` as the bridge from research scores to portfolio semantics. | Do not jump into DRL allocation or paper broker integration before evidence semantics converge. |
| `nautechsystems/nautilus_trader` | Research/live parity through one deterministic event-driven domain model. | Learn from domain-model discipline and deterministic execution semantics. | Do not attempt a Rust/live/event engine rewrite. |
| `QuantConnect/Lean` | Modular plug-in architecture, CLI research/backtest/optimize/live lifecycle, broad asset coverage. | Keep CLI/API workflows explicit and command-oriented. | Do not copy broad live-trading, brokerage, and cloud workflow scope. |
| `ricequant/rqalpha` | Extensible mod hook architecture: accounts, analyser, risk, scheduler, simulation, transaction cost. | Use modular adapters for transaction cost, risk, simulation, and reporting. | Do not let mods own research semantics; ADR-0002 still applies. |
| `freqtrade/freqtrade` | Strong dry-run, persistence, WebUI/control plane, backtesting, hyperopt, and lookahead-analysis culture. | Adopt dry-run/no-live safety framing and leakage diagnostics as first-class checks. | Do not become a retail live-trading bot. |
| `mementum/backtrader` | Rich broker simulation, order types, slippage, commission, analyzers, multi-timeframe support. | Eventually add a lightweight execution-preview ledger. | Do not prioritize order-type completeness over research reproducibility. |

## 3. Replacement-first architecture

### 3.1 Replace scattered run configuration with `ResearchContract`

Current state:

- `ResearchSessionConfig` is a good start, but date range, market, universe, label provenance, feature expressions, benchmark, alignment, and split semantics still appear across runners and artifacts.
- Data-readiness outputs, CN validation outputs, grid manifests, and decision packs are related but not yet one canonical contract.

Replacement:

```text
ResearchContract
  - market
  - benchmark
  - data_snapshot_id
  - universe_snapshot_id
  - feature_set_id
  - label_contract_id
  - split_contract_id
  - primary_horizon_days = 10
  - primary_rebalance_days = 10
  - alignment_mode
  - retained_symbols
  - dropped_symbols
```

What this simplifies:

- Runners no longer invent or partially repeat research meaning.
- Notebook, script, API, and agent calls pass the same contract.
- Every evidence artifact can cite the same canonical input.

Migration rule:

- Keep `ResearchSessionConfig` temporarily as a compatibility wrapper.
- New research workflows should accept or build `ResearchContract`.
- Once parity is proven, `ResearchSessionConfig` should become an adapter-facing convenience object, not the domain source of truth.

### 3.2 Replace score-only backtesting with `PortfolioIntent`

Current state:

- `run_vectorized_backtest(predictions, returns, topk=...)` evaluates scores directly.
- This is fast and useful, but it hides the portfolio construction step inside the backtest path.
- As a result, TOP-N equal-weight, turnover, constraints, risk overlay, and order preview cannot be reasoned about as separate concepts.

Replacement:

```text
SignalFrame
  -> score_to_equal_weight_intent(...)
  -> PortfolioIntent
  -> evaluate_portfolio_intent(...)
  -> EvaluationReport
```

`PortfolioIntent` is not a broker order. It is a dated target-weight statement:

```text
PortfolioIntent
  - research_contract_id
  - strategy_id
  - benchmark
  - rebalance_days
  - target_weights[datetime, instrument]
  - constraints
  - provenance
```

What this simplifies:

- TOP-N equal-weight becomes one adapter, not the hidden default semantics of the whole backtest engine.
- Long-only, long-short, sector-neutral, capped-weight, and risk-overlay variants can share one evaluation path.
- Dashboard holdings/signals can load the same object the backtest consumed.

Migration rule:

- Keep score-based `run_vectorized_backtest(...)` during migration.
- Add a parity wrapper: old score path and new intent path must produce identical results for TOP-N equal-weight fixtures.
- After parity, new research code should use intent-based evaluation internally.

### 3.3 Replace parallel decision systems with `PromotionDecision`

Current state:

- `walk_forward_stability.py`, `ten_day_model_gates.py`, `model_decision_pack.py`, `EvidenceLedger`, model registry stages, and dashboard status can all imply a decision.
- ADR-0001 says evidence should be the decision anchor, but implementation still has multiple decision-adjacent outputs.

Replacement:

```text
EvidenceBundle
  -> PromotionGate
  -> PromotionDecision
```

`ModelDecisionPack` should become a rendered view or derivative of `PromotionDecision`, not an independent decision layer.

What this simplifies:

- One object answers: rejected, research_candidate, stronger_research_candidate, trade_guidance_candidate, or missing_evidence.
- Dashboard/API/Agent do not recalculate decision meaning.
- Model registry stores lifecycle state only after a decision cites evidence.

Migration rule:

- Keep `ModelDecisionPack` JSON/Markdown output for compatibility.
- Add `promotion_decision` inside it.
- Later deprecate direct decision use from `ModelDecisionPack.decision` when consumers read `PromotionDecision`.

### 3.4 Replace specialized evidence runners with a small `ExperimentSpec` pattern

Current state:

Many recent scripts are useful but increasingly specialized:

- `run_rolling_daily_ranker_evidence.py`
- `run_ranker_calibration_grid_evidence.py`
- `run_stable_signal_blend_evidence.py`
- `run_best_blend_universe_robustness.py`
- `run_cn_10d_validation.py`
- `run_cn_feature_quality_validation.py`

They should not all become permanent workflow owners.

Replacement:

```text
ExperimentSpec
  - research_contract
  - candidate_grid
  - evaluation_plan
  - output_manifest

run_experiment_spec(spec) -> EvidenceBundle-compatible outputs
```

What this simplifies:

- One execution contract replaces many runner-specific semantics.
- Specialized scripts become thin presets around `ExperimentSpec`.
- Agent automation can choose presets without owning research meaning.

Migration rule:

- Do not delete current scripts immediately.
- Mark them as compatibility entry points once `ExperimentSpec` exists.
- New scripts should be presets, not independent workflow implementations.

### 3.5 Replace broad release surface with a smaller stable core

Current release docs classify many API endpoints and strategy surfaces as release/experimental. That is useful for product tracking, but architecture convergence should narrow the stable semantic core.

Replacement:

```text
Stable semantic core:
  - data readiness
  - fixed-10D research contract
  - signal evaluation
  - portfolio intent evaluation
  - evidence bundle
  - promotion decision

Adapter/product surfaces:
  - dashboard pages
  - API routes
  - notebooks
  - scripts
  - agents
  - reports
```

What this simplifies:

- API endpoint count stops being confused with architecture maturity.
- Experimental UI/agent surfaces can evolve without changing research semantics.
- Release confidence depends on core contracts, not number of exposed routes.

Migration rule:

- Do not remove existing endpoints in the first pass.
- Update release docs later to distinguish `stable semantic core` from `release adapter surface`.
- New endpoint behavior should be backed by core contracts.

## 4. Simplification and deprecation table

| Current component/pattern | Keep | Replace with | Simplification rule |
|---|---:|---|---|
| `ResearchSessionConfig` as primary research contract | Temporarily | `ResearchContract` | Compatibility wrapper only after parity. |
| Score-only `run_vectorized_backtest(predictions, returns)` as canonical path | Temporarily | `PortfolioIntent -> EvaluationReport` | Keep old function; new internals move to intent path. |
| Multiple evidence-specific runner scripts | Temporarily | `ExperimentSpec` presets | Scripts become thin wrappers, not semantic owners. |
| `ModelDecisionPack` as independent decision layer | Temporarily | `PromotionDecision` derived from `EvidenceBundle` | Decision pack becomes a report view. |
| Model registry stage as implied truth | No | `PromotionDecision` citing evidence | Registry records outcome, not justification. |
| Dashboard/API/Agent-specific decision rules | No | Core PromotionGate | Adapters render decisions only. |
| Broad strategy DSL expansion | No | Small transforms: score-to-weight, allocation, risk overlay | No unconstrained DSL before contracts are stable. |
| Broker/live execution scope | No | Broker-free order preview/dry-run ledger | No credentials, no real orders. |
| More model families before contract convergence | No | Feature/universe/data diagnostics under fixed-10D contract | Avoid complexity without better reproducibility. |

## 5. Non-negotiable invariants

1. Fewer core concepts are better than more adapters.
2. Every lifecycle decision must cite durable evidence.
3. Processed labels remain training targets only; economic evaluation uses raw forward returns.
4. Fixed 10D remains the primary contract until the core is stable.
5. Backtests should consume portfolio intent, not silently construct portfolios inside score evaluation.
6. Scripts, notebooks, dashboard, API, and agents are adapters.
7. Live trading remains out of scope.
8. Compatibility wrappers are allowed, but new semantics must go into core modules.

## 6. Revised PR sequence

### PR A — Domain replacement contracts

Purpose: introduce the replacement vocabulary without changing behavior.

Add:

- `ResearchContract`
- `DataSnapshotRef`
- `UniverseSnapshotRef`
- `FeatureSetRef`
- `LabelContract`
- `SplitContract`
- `SignalFrameMetadata`
- `PortfolioIntentMetadata`
- `EvidenceRef`
- `PromotionDecision`

Also add a short compatibility note that `ResearchSessionConfig` remains supported but is no longer the long-term semantic owner.

Acceptance gates:

- JSON-compatible round-trip tests;
- no import-time Qlib dependency;
- no runtime output changes;
- no dashboard/API behavior change.

### PR B — Score-to-intent parity

Purpose: replace hidden score-to-portfolio semantics with explicit intent semantics.

Add:

- `score_to_equal_weight_intent(...)`;
- `evaluate_portfolio_intent(...)`;
- parity tests showing old TOP-N score backtest equals new intent path.

Acceptance gates:

- old API remains available;
- new internal path is intent-based;
- identical deterministic results for TOP-N equal-weight fixture;
- no model decision changes.

### PR C — Decision unification

Purpose: replace parallel decision outputs with one promotion decision.

Add:

- `PromotionGate` operating on `EvidenceBundle`;
- `promotion_decision` inside model decision pack output;
- tests that missing evidence fails closed.

Acceptance gates:

- decision pack still renders Markdown/JSON;
- dashboard/API/agent consumers can read one decision object;
- no adapter-specific promotion logic.

### PR D — Runner simplification

Purpose: replace specialized runner semantics with `ExperimentSpec` presets.

Add:

- `ExperimentSpec`;
- one common runner interface;
- migrate one existing runner as a proof of pattern.

Acceptance gates:

- migrated runner output remains schema-compatible;
- other scripts remain available;
- new code path is tested with fixture data.

### PR E — Release-surface simplification

Purpose: separate stable semantic core from product/adapter surface.

Update:

- release docs;
- architecture docs;
- dashboard/API notes if needed.

Acceptance gates:

- endpoint behavior is not removed;
- docs clearly identify which surfaces are semantic core vs adapter;
- future PRs know where new business meaning must live.

### PR F — Broker-free execution preview

Purpose: add limited portfolio-intent operational visibility without live trading.

Add:

- `PortfolioIntent -> RebalancePlan`;
- `RebalancePlan -> OrderPreview`;
- dry-run ledger only.

Acceptance gates:

- no broker integration;
- no credentials;
- no real order placement;
- all outputs marked preview/dry_run.

## 7. What should be simplified immediately

The next coding PR should not add another research runner.

It should implement PR A and explicitly mark the following as compatibility surfaces:

- `ResearchSessionConfig`;
- existing evidence runner scripts;
- direct score-based vectorized backtest entry point;
- model decision pack as a report view.

This does not break users. It stops future work from treating these compatibility surfaces as the place to add new semantics.

## 8. Success definition

Architecture convergence succeeds when AlphaEngine can trace a candidate through this single path:

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
Adapter rendering
```

and the old entry points are either:

- thin wrappers around this path; or
- explicitly marked internal/compatibility; or
- removed after a documented migration window.

The goal is not to grow AlphaEngine into a larger framework. The goal is to make the system smaller, more reproducible, and harder for agents, notebooks, scripts, or dashboard code to accidentally reinterpret.
