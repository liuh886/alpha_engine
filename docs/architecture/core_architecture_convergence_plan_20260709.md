# AlphaEngine Core Architecture Convergence Plan

Date: 2026-07-09
Status: proposed
Scope: architecture plan only; no runtime, model, data, broker, or dashboard behavior changes in this PR.

## 1. Conclusion

The previous convergence direction is directionally correct but not sufficient as a complete architecture target.

AlphaEngine should not converge into a general-purpose live-trading engine, and it should not converge into a pure vectorized backtest library. The better target is:

> Evidence-first quantitative research kernel + weight/intent-centric portfolio semantics + thin adapters for notebook, API, dashboard, scripts, and agents.

This keeps AlphaEngine's current advantage — conservative 10D evidence, fail-closed validation, and model/factor decision discipline — while adding the missing architecture bridge between research scores and portfolio/execution semantics.

The core convergence objective is therefore:

```text
DataSnapshot / UniverseSnapshot / FeatureSet / LabelContract
        ↓
SignalFrame
        ↓
TargetWeightFrame / PortfolioIntent
        ↓
BacktestReport / RiskReport / OrderPreview / SignalSnapshot
        ↓
EvidenceBundle
        ↓
PromotionDecision
        ↓
Dashboard / Notebook / API / Agent responses
```

## 2. External repository lessons

This plan reviewed the current AlphaEngine architecture against several mature open-source quantitative repositories. The goal is not to copy any one framework, but to extract the architectural lesson relevant to AlphaEngine's current stage.

| Repository | Strong architecture lesson | What AlphaEngine should adopt | What AlphaEngine should not copy now |
|---|---|---|---|
| `microsoft/qlib` | Full AI-oriented quant platform spanning data processing, model training, backtesting, alpha seeking, risk modeling, portfolio optimization, and execution. | Keep Qlib as the lower-level market data/model infrastructure; expose a stricter AlphaEngine research contract above it. | Do not reimplement Qlib's whole platform surface. |
| `polakowo/vectorbt` | Matrix/vectorized research, large parameter sweeps, portfolio analytics, interactive exploration. | Adopt grid-manifest thinking and high-throughput experiment surfaces for feature/model grids. | Do not let speed-first parameter search override evidence gates or fixed 10D contracts. |
| `pmorissette/bt` | Reusable strategy logic blocks and composable algo stacks. | Add composable score-to-weight, allocation, timing, and risk-overlay blocks. | Do not build an unconstrained strategy DSL before core contracts stabilize. |
| `AI4Finance-Foundation/FinRL-Trading` | Weight-centric interface: downstream backtest/execution consumes target portfolio weights. | Adopt `TargetWeightFrame` / `PortfolioIntent` as the central bridge from research scores to portfolio semantics. | Do not jump into DRL allocation or paper broker integration before evidence semantics converge. |
| `nautechsystems/nautilus_trader` | Research-to-live parity through one deterministic event-driven architecture and unified domain model. | Learn from the domain-model discipline and deterministic execution semantics. | Do not attempt a Rust/live/event engine rewrite; AlphaEngine is not ready for live parity scope. |
| `QuantConnect/Lean` | Modular plug-in architecture, CLI research/backtest/optimize/live lifecycle, broad asset coverage. | Keep CLI/API workflows explicit and command-oriented. | Do not copy broad live-trading, brokerage, and cloud workflow scope. |
| `ricequant/rqalpha` | Extensible mod hook architecture: accounts, analyser, risk, scheduler, simulation, transaction cost. | Use modular adapters for risk, transaction cost, simulation, and reporting. | Do not let mods own research semantics; AlphaEngine ADR-0002 still applies. |
| `freqtrade/freqtrade` | Strong dry-run, persistence, WebUI/control plane, backtesting, hyperopt, and lookahead-analysis culture. | Adopt explicit dry-run / no-live safety framing and add lookahead/leakage diagnostics as first-class checks. | Do not become a retail live-trading bot. |
| `mementum/backtrader` | Rich broker simulation, order types, slippage, commission, analyzers, multi-timeframe support. | Eventually add a lightweight execution-simulation ledger. | Do not prioritize order-type completeness over research reproducibility. |

## 3. Corrected target architecture

The strongest architecture for AlphaEngine is a two-kernel system with one shared domain language.

### 3.1 Research kernel

The research kernel owns the meaning of factor/model evidence.

It should include:

- `ResearchSessionConfig`
- `DataSnapshot`
- `UniverseSnapshot`
- `FeatureSetManifest`
- `LabelContract`
- `SignalFrame`
- `WalkForwardSummary`
- `ModelDecisionPack`
- `EvidenceBundle`
- `PromotionDecision`

The research kernel must preserve the current fixed-10D discipline:

- primary horizon: 10 trading days;
- primary rebalance cadence: 10 trading days;
- canonical raw return expression: `Ref($close, -10) / $close - 1`;
- processed labels are training targets only;
- economic evaluation must use raw forward returns;
- data-readiness failures must fail closed;
- fewer than three OOS windows cannot promote a candidate;
- research evidence is not trade authorization.

### 3.2 Portfolio semantics kernel

The portfolio semantics kernel owns the meaning of portfolio intent.

It should include:

- `TargetWeightFrame`: dated target weights by instrument;
- `PortfolioIntent`: market, benchmark, strategy id, target weights, constraints, and provenance;
- `PortfolioConstraintSet`: max single-name weight, max turnover, cash floor, market/sector limits when available;
- `RebalancePlan`: dated weight changes derived from a `PortfolioIntent`;
- `OrderPreview`: simulated orders, not broker orders;
- `ExecutionLedger`: dry-run fills, holdings, cash, NAV, costs, and skipped instruments;
- `RiskReport`: drawdown, exposure, turnover, concentration, and benchmark-relative metrics.

This layer should be broker-free in the first convergence cycle.

## 4. Non-negotiable architectural invariants

1. Adapters must not own research semantics.
   - FastAPI, dashboard, scripts, notebooks, MCP tools, and agents can render or trigger workflows.
   - They cannot define promotion rules, evidence sufficiency, or trade-readiness logic.

2. Every decision must cite durable evidence.
   - Factor/model/strategy lifecycle changes must depend on `EvidenceBundle` or a versioned derivative.
   - Model registry stage alone is not sufficient evidence.

3. Backtests must consume portfolio intent, not only scores.
   - `score -> top-k equal weight` should remain as a convenience adapter.
   - The durable backtest contract should be `TargetWeightFrame -> BacktestReport`.

4. Data and universe coverage must be versioned.
   - Every evidence artifact should identify the data snapshot, universe snapshot, calendar, benchmark, feature set, and label contract.

5. Live trading remains out of scope.
   - The next convergence cycle may generate order previews and dry-run ledgers.
   - It must not connect to broker APIs or create real orders.

## 5. Planned convergence PR sequence

### PR A — Domain contracts only

Add core dataclasses and serialization tests, with no behavior changes:

- `DataSnapshot`
- `UniverseSnapshot`
- `FeatureSetManifest`
- `LabelContract`
- `SignalFrameMetadata`
- `TargetWeightFrameMetadata`
- `PortfolioIntent`
- `EvidenceRef`
- `PromotionDecision`

Acceptance gates:

- all contracts round-trip through JSON-compatible dictionaries;
- no import-time Qlib dependency;
- no change to existing runner output;
- no dashboard/API behavior change.

### PR B — Score-to-weight adapter and backtest parity

Introduce a weight-centric wrapper while preserving current results:

- `score_to_equal_weight_topk(...)`;
- `target_weights_to_vectorized_backtest(...)`;
- parity test proving current `run_vectorized_backtest(score, return)` equals the new score-to-weight path for TOP N equal weight;
- explicit transaction-cost and turnover fields carried forward.

Acceptance gates:

- old score-based API remains available;
- new weight-based API is canonical internally;
- parity test passes for deterministic fixtures;
- no model metric claims change.

### PR C — EvidenceBundle unification

Make `ModelDecisionPack` a consumer or derivative of `EvidenceBundle`, not a parallel decision system.

Acceptance gates:

- a decision pack cites evidence sources;
- missing data-readiness, missing walk-forward summary, or missing model evidence produces fail-closed warnings;
- dashboard/API/agent surfaces read decision status from one core path.

### PR D — Snapshot manifests

Add versioned manifests for:

- market data coverage;
- retained/dropped universe;
- feature expressions;
- label contract;
- benchmark series;
- run configuration.

Acceptance gates:

- every new evidence artifact includes manifest ids;
- CN leading-zero symbols are preserved;
- auto-alignment never shifts start earlier than requested;
- skipped runs emit explicit reasons.

### PR E — Execution-preview simulation

Add broker-free order preview and dry-run ledger:

- `PortfolioIntent -> RebalancePlan`;
- `RebalancePlan -> OrderPreview`;
- `OrderPreview + returns -> ExecutionLedger`;
- skipped-instrument ledger for missing prices, non-tradable days, or constraint failures.

Acceptance gates:

- no live broker code;
- no credentials;
- no real order placement;
- all generated orders are explicitly marked `preview` or `dry_run`.

### PR F — Adapter thinning

Refactor scripts/API/dashboard/agent entry points so they only call core workflows.

Acceptance gates:

- no adapter-specific promotion rules;
- no dashboard-only lifecycle state;
- no agent prompt-level decision logic;
- common tests prove CLI/API/notebook paths produce the same decision for the same evidence.

## 6. What should not be done next

Do not start by adding more model families.

Do not start by connecting brokers.

Do not start by building a general-purpose strategy DSL.

Do not continue small blend-weight tuning before universe/data/weight/evidence contracts converge.

Do not let notebooks, scripts, or agents keep accumulating one-off research semantics.

## 7. Immediate next implementation recommendation

The next coding PR should be PR A: domain contracts only.

Suggested file layout:

```text
src/domain/
  __init__.py
  snapshots.py
  signals.py
  portfolio.py
  evidence_refs.py
  decisions.py

tests/
  test_domain_contracts.py
```

The implementation should be deliberately boring:

- dataclasses only;
- no Qlib initialization;
- no LightGBM import;
- no FastAPI dependency;
- no dashboard changes;
- JSON-compatible `to_dict()` / `from_dict()` where needed;
- strict validation for empty ids, empty symbols, non-10D primary horizon, and invalid weight sums only where the contract requires it.

The purpose of PR A is to create the stable language for later refactors, not to change research results.

## 8. Success definition for the convergence effort

Architecture convergence is successful when the same candidate can be traced as:

```text
universe + features + label + model scores
        ↓
SignalFrame
        ↓
TargetWeightFrame / PortfolioIntent
        ↓
BacktestReport + RiskReport + SignalSnapshot
        ↓
EvidenceBundle
        ↓
PromotionDecision
        ↓
Dashboard / Notebook / API / Agent
```

and every layer can be re-run, audited, and explained without relying on private agent memory, notebook-local assumptions, or dashboard-only state.
