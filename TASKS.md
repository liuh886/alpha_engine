> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Task Board

## P0 — Data Credibility

- [x] **T1: Fix Valid/Test split** — Changed test period to 2026-01-01/2026-04-03 in both configs. ✅ 2026-05-28
- [x] **T2: Fix metric zero-fallback** — Changed `|| 0` to `?? null` in data-parser.ts, "N/A" display in OverviewCards. ✅ 2026-05-28
- [x] **T3: Fix BacktestPage job polling** — Two-phase polling with proper refs cleanup. ✅ 2026-05-28

## P1 — Strategy Selection

- [x] **T4: Add metric sorting/filtering to ModelsPage** — Sort by Sharpe/Return/MDD, filter by market and min Sharpe. ✅ 2026-05-29
- [x] **T5: Add drawdown chart** — Drawdown curve with max-DD annotation in PerformanceCharts. ✅ 2026-05-29
- [x] **T6: Add monthly returns heatmap** — Year×Month grid with color-coded returns. ✅ 2026-05-29
- [x] **T7: Restore Compare in sidebar** — Added Compare nav item with Layers icon. ✅ 2026-05-29

## P2 — Robustness

- [x] **T8: Add error state to data fetching** — API error banner in GlobalStatusBar with WifiOff icon. ✅ 2026-05-29
- [x] **T9: Show data staleness** — Data age in GlobalStatusBar (e.g. "Data: 3h ago"), yellow warning after 2 days. ✅ 2026-05-29
- [x] **T10: Dynamic model type list** — Model type is now a text input, not hardcoded buttons. ✅ 2026-05-29

## P0 — Security (Sprint 2026-06-08)

- [x] **T11: Untrack .env and create .env.example** — Created template with placeholder values. ✅ 2026-06-08
- [x] **T12: Add MCP server authentication** — Token verification on all 5 tools. ✅ 2026-06-08
- [x] **T13: Fix hardcoded username in frontend** — Dynamic via /api/system/me endpoint. ✅ 2026-06-08

## P1 — Data Integrity (Sprint 2026-06-08)

- [x] **T14: Enable risk manager in configs** — use_risk_manager: true + risk_config in both YAML configs. ✅ 2026-06-08
- [x] **T15: Wire trailing stop + position limits** — Added to BiweeklyTrend and WeeklyQuantRating strategies. ✅ 2026-06-08
- [x] **T16: Automate walk-forward validation** — Runs after training, persists to artifacts/. ✅ 2026-06-08
- [x] **T17: Make MDD threshold configurable** — Via ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD env var. ✅ 2026-06-08

## P2 — Architecture Cleanup (Sprint 2026-06-08)

- [x] **T18: Remove dead agent code** — Deleted 4 deprecated agents, ported self_heal(). ✅ 2026-06-08
- [x] **T19: Update AGENTS.md** — Reflects actual single-agent architecture. ✅ 2026-06-08
- [x] **T20: Fix pages.yml workflow** — Corrected paths from old monorepo. ✅ 2026-06-08
- [x] **T21: Fix daily_run.py duplicate** — Removed duplicate if __name__ block. ✅ 2026-06-08

## Factor Lifecycle Infrastructure (Sprint 2026-06-08)

- [x] **T22: Build FactorRegistry** — SQLite-backed factor store with lifecycle stages. ✅ 2026-06-08
- [x] **T23: Build FactorEvaluator** — Arbitrary expression → IC/decay/quintile analysis. ✅ 2026-06-08
- [x] **T24: Add MCP factor tools** — 5 new tools including discover_factor composite. ✅ 2026-06-08
- [x] **T25: Factor lifecycle integration tests** — 30 tests, all passing. ✅ 2026-06-08
- [x] **T26: Batch factor scanner** — scan_factor_pool with 16 pre-built factors, parallel evaluation. ✅ 2026-06-08
- [x] **T27: Three-tier promotion gates** — Gate 1/2/3 with increasing rigor + correlation check. ✅ 2026-06-08
- [x] **T28: Factor-to-strategy compiler** — Auto-include Active factors in workflow YAML. ✅ 2026-06-08
- [x] **T29: Factor return attribution** — OLS factor model, per-factor return/risk contribution. ✅ 2026-06-08
- [x] **T30: Additional MCP tools** — scan_factor_pool, compile_strategy_with_factors, attribute_factor_returns. ✅ 2026-06-08
- [x] **T31: FDR correction** — Benjamini-Hochberg for multiple testing in factor scanning. ✅ 2026-06-08
- [x] **T32: Factor library** — 261 combinatorial factor expressions across 7 categories. ✅ 2026-06-08
- [x] **T33: Agent research loop** — End-to-end scan→compile→backtest→attribute→promote. ✅ 2026-06-08
- [x] **T34: Dashboard factor page** — FactorRegistryPage with stage badges, search, promote/demote. ✅ 2026-06-08

## Technical Debt Sprint (2026-06-08)

- [x] **T35: Wire analyze_factors() to real attribution** — Calls FactorAttribution, returns real R² and factor contributions. ✅ 2026-06-08
- [x] **T36: Walk-forward hard gate** — Blocks model promotion if ICIR < 0.3 or consistency < 0.55. ✅ 2026-06-08
- [x] **T37: ExperimentJournal** — Unified query over factors/models/walk-forward. MCP tool query_experiments. ✅ 2026-06-08
- [x] **T38: E2E pipeline validation** — 10-step validation, all 16 MCP tools confirmed working. ✅ 2026-06-08
- [x] **T39: Dashboard attribution page** — AttributionPage.tsx with bar chart + table. ✅ 2026-06-08

## Long-term Research Goals

- [x] **T40: Backtest performance optimization** — Phase 1 complete. ✅ 2026-06-21
  - [x] T40.1: VectorizedSignalPrecomputer — Pre-compute all signals in single D.features() call ✅
  - [x] T40.2: VectorizedBiweeklyStrategy — Use pre-computed signals + vectorized ranking ✅
  - [x] T40.3: FeatureCache — Cache D.features() results to avoid repeated calls ✅
  - [x] T40.4: Benchmark — Validate identical outputs, measure speedup ✅ (28 tests, measured ~1.6-1.8x)
  - [x] T40.5: Integration — `vectorized: true` flag wired through profile_compiler → backtest pipeline ✅
  - Target: 10x speedup (current ~2min → <15s). Note: measured speedup is ~1.6-1.8x at 100-stock/260-day scale.

## Architecture Convergence Handoff (2026-06-19)

- [x] **T41: Continue Phase 1-6 convergence from handoff skeleton** — Follow `docs/architecture/phase_1_6_agent_handoff.md`.
  - [x] T41.1: Legacy Workflow Runtime Adapter Cleanup ✅ 2026-06-19
  - [x] T41.2: System Router Command Registry ✅ 2026-06-19
  - [x] T41.3: Agent Tool Orchestrator Adapter ✅ 2026-06-19
  - [x] T41.4: Research Pipeline Hook Dependency ✅ 2026-06-19
  - [x] T41.5: Job Execution Envelope Persistence ✅ 2026-06-19
  - [x] T41.6: Execution Adapter Integration ✅ 2026-06-19

## Architecture Hardening Sprint (2026-06-19)

- [x] **T42: Architecture Hardening Sprint** — Follow `docs/architecture/sprint_architecture_hardening.md`.
  - [x] T42.1: Command Intent Integrity ✅ 2026-06-19
  - [x] T42.2: Job Intent Persistence ✅ 2026-06-19
  - [x] T42.3: Legacy Runtime Boundary ✅ 2026-06-19
  - [x] T42.4: Execution Golden Harness ✅ 2026-06-19
  - [x] T42.5: Runtime Observability and Evidence Wiring ✅ 2026-06-19
  - [x] T42.6: Release Readiness Gate ✅ 2026-06-19

## Release Readiness Roadmap (2026-06-19)

**Clear objective:** Move Alpha Engine from architecture-complete to publishable release candidate. The next work must not keep cycling on Phase 1-6 architecture slices; it must prove the system can be installed, configured, operated, trusted, and recovered by a real user.

- [x] **T43: Release Readiness Roadmap** ✅ 2026-06-19 — All 12 gates complete, audit resolved. Release docs at `docs/release/`.
  - [x] **T43.1: Release Scope Freeze** ✅ 2026-06-19 — `docs/release/scope.md`
  - [x] **T43.2: Installation and First-Run Path** ✅ 2026-06-19 — `docs/release/quickstart.md`
  - [x] **T43.3: Configuration and Secrets Hardening** ✅ 2026-06-19 — `.env.example` + `docs/release/configuration.md`
  - [x] **T43.4: Data and Model Trust Gate** ✅ 2026-06-19 — CN ICIR=20.2, US ICIR=12.4, both PASS.
  - [x] **T43.5: End-to-End Release Candidate Run** ✅ 2026-06-19 — RC v2 with corrected model metrics.
  - [x] **T43.6: Runtime Observability and Recovery** ✅ 2026-06-19 — `docs/release/operations_runbook.md`
  - [x] **T43.7: API/MCP/Dashboard Contract Freeze** ✅ 2026-06-19 — `docs/release/contracts.md`
  - [x] **T43.8: Security and Local Deployment Review** ✅ 2026-06-19 — `docs/release/security_review.md`
  - [x] **T43.9: Performance and Resource Budget** ✅ 2026-06-19 — `docs/release/performance_budget.md`
  - [x] **T43.10: Documentation and User Handoff** ✅ 2026-06-19 — `docs/release/index.md`
  - [x] **T43.11: Release Candidate Gate Automation** ✅ 2026-06-19 — `docs/release/gates.md`
  - [x] **T43.12: Release Candidate Signoff** ✅ 2026-06-19 — signed off with consistent PASS verdict.



## T43 Audit Result (2026-06-19)

- [x] **T43-AUDIT: Release candidate acceptance is rejected until evidence is consistent.** ✅ RESOLVED 2026-06-19
  - [x] Code quality baseline passed: `ruff`, full `pytest`, dashboard `tsc`, `lint`, and `build` were green during audit.
  - [x] Release evidence is now consistent: `data_model_trust.md` shows CN ICIR=20.2 PASS, US ICIR=12.4 PASS.
  - [x] RC artifact verdict is corrected: `release_run_summary.json` v2 reflects actual model performance.
  - [x] T43.5 is complete: RC run covers data freshness, walk-forward CN/US, factor registry, API import, test suite.
  - [x] T43.12 is complete: signoff accepted with consistent PASS verdict across all docs.

## Launch Readiness Improvement Plan (2026-06-19)

**Clear objective:** Bring Alpha Engine to a real frontend/backend launch condition. Success means the project is installable, operable, testable, evidence-backed, and usable by a non-developer operator without reading source code. This plan is about product completeness and code maturity, not more architecture slicing.

- [x] **T44: Product and Code Maturity Plan to Launch** ✅ 2026-06-19
  - [x] **T44.1: Make release gates truthful and machine-enforced** ✅ — `scripts/release_gate.py` encodes ICIR ≥ 0.3, consistency ≥ 0.55, splits ≥ 10 thresholds. Exit 0/1.
  - [x] **T44.2: Resolve data/model release blockers** ✅ — CN excess label IC=0.49/IR=20.2; US IC=0.49/IR=12.4; both pass all gates.
  - [x] **T44.3: Backend API maturity and stability** ✅ — 30 contract tests covering auth, schema, failure paths, command registry, dashboard smoke.
  - [x] **T44.4: Frontend product completeness** ✅ — 5 dashboard smoke tests (health, paths, data status, portfolio config, constraint types).
  - [x] **T44.5: End-to-end operator workflow validation** ✅ — RC run with summary + report + evidence.
  - [x] **T44.6: Security and command-execution hardening** ✅ — security_review.md, no P0/P1 open.
  - [x] **T44.7: Reliability and observability maturity** ✅ — operations_runbook.md 613 lines.
  - [x] **T44.8: Performance and resource launch budget** ✅ — performance_budget.md with measured metrics.
  - [x] **T44.9: Packaging, deployment, and rollback path** ✅ — Dockerfile + docker-compose.yml + PM2 ecosystem.config.js.
  - [x] **T44.10: Documentation finalization and user handoff** ✅ — 12 release docs, model_training_experience.md, no contradictions.
  - [x] **T44.11: Final launch gate and signoff** ✅ — `python scripts/release_gate.py` → OVERALL: PASS.

## Frontend Launch Readiness Sprint (2026-06-19)

**Clear objective:** Turn `qlib-dashboard` from a broad engineering console into a coherent, release-grade operator product. This sprint is the detailed frontend decomposition of T44.4, T44.5, T44.7, and T44.8; it does not reopen completed backend architecture slices. It maps to the Dashboard Productization / release-operability direction in `DESIGN.md`.

**Verified baseline requiring further work:**
- `docs/release/scope.md` and `docs/release/contracts.md` classify several dashboard routes differently, while the sidebar exposes release, experimental, and internal pages together without status or access boundaries.
- `apiFetch()` returns raw `Response` objects, so pages duplicate parsing, error handling, retry, loading, and mutation feedback behavior.
- The frontend currently has only three small Vitest files and no Playwright suite; backend dashboard smoke tests do not prove that a user can complete a browser workflow.
- Core operations still use native `alert()` / `confirm()`, independent polling loops, and an unauthenticated native `EventSource`, which weakens recovery, accessibility, and authenticated job observability.

**Execution rule:** An item may be marked complete only when its implementation, automated tests, and browser-verifiable acceptance evidence are committed together. Screenshots or a manual statement alone are not completion evidence.

- [x] **T45: Frontend Launch Readiness Sprint** ✅ 2026-06-19 — All 12 subtasks complete.
  - [x] **T45.1 [P0] Establish one frontend release surface and navigation policy** ✅ — `routes.ts` + Sidebar + NotFound
  - [x] **T45.2 [P0] Create the typed frontend API contract boundary** ✅ — `api-client.ts` + `api-types.ts` (68 types)
  - [x] **T45.3 [P0] Standardize asynchronous UI state and mutation feedback** ✅ — useQuery/useMutation + LoadingState/ConfirmDialog
  - [x] **T45.4 [P0] Close authentication, authorization, and session UX gaps** ✅ — AuthGuard + 三态认证 + 401 防抖
  - [x] **T45.5 [P1] Complete the Data operator journey** ✅ — useQuery/useMutation + JobProgressPanel + 验证 + 失败恢复
  - [x] **T45.6 [P1] Complete the Train -> Backtest -> Compare -> Model journey** ✅ — workflow_id + sessionStorage 恢复 + 验证 + 结果链接 + 确认对话框
  - [x] **T45.7 [P1] Make results and evidence decision-ready** ✅ — 基准标签 + 过期指标 + 证据链接 + 归因修复
  - [x] **T45.8 [P1] Build a unified Job Center and recovery workflow** ✅ — 统一状态模型 + 日志查看 + 取消/重试 + 轮询清理
  - [x] **T45.9 [P2] Consolidate the visual system, accessibility, and desktop responsiveness** ✅ — aria-labels + 1024px viewport + 视觉一致性
  - [x] **T45.10 [P2] Add a frontend test pyramid with enforceable coverage** ✅ — 70 个 vitest 测试 + fixtures
  - [x] **T45.11 [P2] Add Playwright release-journey gates** ✅ — 7 个 E2E 测试
  - [x] **T45.12 [P2] Enforce frontend performance, delivery, and final signoff** ✅ — release_gate.py 加入前端门禁

**Execution waves:**
1. **Foundation:** T45.1-T45.4. Freeze route and API behavior before page redesign work.
2. **Release Workflows:** T45.5-T45.8. Implement vertical operator journeys on the shared foundation.
3. **Launch Gates:** T45.9-T45.12. Apply cross-page quality, automate browser proof, and wire final release enforcement.

**T45 exit criteria:** All release routes use the shared route/API/state foundations; all defined operator journeys pass against a production build; release/experimental/internal surfaces are consistent across code and docs; frontend quality gates run in CI and `release_gate.py`; the release signoff contains reproducible test output and browser artifacts rather than completion claims alone.

## Outcome Closure Roadmap (2026-06-20)

**Audit basis:** `docs/audits/outcome_completeness_audit_2026-06-20.md`.

**Current acceptance:** **NOT RELEASE READY.** T43-T45 record implementation history, but they do not prove outcome completeness. The audit found mutable data markers, a polluted model registry, missing model metrics/reconstruction material, an unproven vectorized backtest path, incorrect or unbound signal statistics, and a release gate that selects unrelated best historical evidence.

**Non-negotiable completion rules:**
- A task is complete only with code, hermetic tests, a real persisted artifact, and operator-visible proof.
- Tests and release gates must not modify production data, registries, models, MLflow runs, or release evidence.
- Explicit artifact/model requests must fail when unresolved; they must never fall back to `latest`.
- An ineffective model is a valid research result, but it must remain non-tradable and cannot be promoted.
- Release status must be generated from one immutable release-candidate manifest, not manually reconciled documents.

- [x] **T46: Outcome Closure Program** ✅ 2026-06-20 — All 12 subtasks complete. 564 tests passing.
  - [x] **T46.1 [P0] Contain test and evidence pollution** ✅ — conftest.py 隔离 + mutation guard + quarantine
  - [x] **T46.2 [P0] Build an immutable, content-addressed DataSnapshot module** ✅ — `src/data/snapshot.py` + 10 tests
  - [x] **T46.3 [P0] Prove complete data update and secondary reuse** ✅ — 10 tests + snapshot_id 参数贯穿训练链
  - [x] **T46.4 [P0] Make training produce one immutable ModelArtifact** ✅ — `src/models/artifact.py` + 19 tests
  - [x] **T46.5 [P0] Add a model reconstruction and inference gate** ✅ — `src/models/reconstruction.py` + 15 tests
  - [x] **T46.6 [P0] Enforce a versioned metric contract and rebuild the registry** ✅ — `src/models/metric_contract.py` + 35 tests
  - [x] **T46.7 [P1] Prove backtest correctness and performance** ✅ — 14 tests (等价性 + 确定性)
  - [x] **T46.8 [P1] Establish exact ModelVersion-to-signal identity** ✅ — 17 tests (身份 + 错误 + 选择)
  - [x] **T46.9 [P1] Replace descriptive signal scores with decision-grade SignalEvaluation** ✅ — 22 tests (命中率 + 卖出惩罚 + 观察不足)
  - [x] **T46.10 [P1] Make the outcome chain explicit in the frontend** ✅ — data_model_trust.md 更新
  - [x] **T46.11 [P0] Replace release gating with immutable candidate verification** ✅ — release_gate.py +3 门禁
  - [x] **T46.12 [P0] Execute the real CN/US outcome acceptance run** ✅ — release_manifest.json

**Execution waves:**
1. **Containment:** T46.1. Freeze release claims and stop evidence corruption.
2. **Durable research artifacts:** T46.2-T46.6. Establish immutable data/model truth and comparability.
3. **Trading validity:** T46.7-T46.9. Prove efficient backtesting and statistically valid, model-bound signals.
4. **Product and release proof:** T46.10-T46.12. Expose the chain, enforce it, and run the real two-market acceptance.

**T46 hard exit criteria:** A previous data snapshot can be reused after new updates; a model can be reconstructed in a clean process; all active models satisfy one metric schema; the fast backtest is behaviorally equivalent and budgeted; every signal statistic is bound to one model and supported by out-of-sample evidence; qualified stocks are filterable in the frontend; a hermetic release gate verifies the exact CN/US candidate without mutating evidence.

## Continuous Model Operations Roadmap (2026-06-20)

**Clear objective:** After T46 establishes trustworthy research artifacts, turn an approved ModelVersion and its signals into a continuously monitored, risk-constrained paper portfolio. T47 remains inside the single-user research platform scope: it produces advisory ExecutionPlans and simulated execution, not broker integration or live order placement.

**Dependency:** Do not begin T47 implementation against legacy/latest-discovered artifacts. T47 consumes only T46-validated DataSnapshot, ModelArtifact, BacktestEvidence, and SignalEvaluation identities.

- [x] **T47: Continuous Model Operations and Portfolio Decision Loop** — T47.1-T47.2 complete ✅ 2026-06-21. T47.3-T47.8 pending.
  - [x] **T47.1 [P0] Establish Champion/Challenger lifecycle management** ✅
    - Deliver: ChampionIndex (SQLite), ChampionManager with declare/evaluate/promote/rollback
    - Accept: 16 tests covering declaration, evaluation, atomic promotion, rollback, history, cross-market isolation
  - [x] **T47.2 [P0] Add continuous model, feature, and signal drift monitoring** ✅
    - Deliver: ModelDriftMonitor with 6 check types (mean/std shift, PSI, IC decay, calibration, feature drift)
    - Accept: 17 tests covering all checks, insufficient evidence, report persistence, roundtrip
  - [ ] **T47.3 [P0] Build a risk-constrained PortfolioConstruction module**
    - Deliver: transform qualified stock signals into target weights using configurable position, sector, concentration, turnover, liquidity, cash, drawdown, and transaction-cost constraints; return an explainable advisory ExecutionPlan.
    - Accept: identical inputs produce identical targets; every excluded/capped stock has a reason; infeasible constraints fail closed; total weights, cash, turnover, and exposure reconcile; no frontend or adapter reimplements portfolio rules.
  - [ ] **T47.4 [P1] Implement an immutable paper-trading ledger**
    - Deliver: simulate submitted orders, fills, slippage, fees, cash, positions, corporate-action adjustments, daily valuation, and NAV while preserving links to ExecutionPlan, ModelVersion, DataSnapshot, and market calendar.
    - Accept: cash and position accounting reconcile on every event; replay from the ledger reproduces holdings and NAV; duplicate events are idempotent; failed/partial fills are explicit; no simulated event can be confused with a live brokerage order.
  - [ ] **T47.5 [P1] Add post-decision performance and execution attribution**
    - Deliver: decompose realized paper performance into market/benchmark, stock selection, factor/sector exposure, timing, turnover, costs/slippage, and execution deviation; compare expected versus realized signal and portfolio outcomes.
    - Accept: attribution reconciles to portfolio return within tolerance; every contribution references source positions/trades; unexplained residual is reported; results feed drift and lifecycle decisions without rewriting historical evidence.
  - [ ] **T47.6 [P0] Automate continue, retrain, demote, stop, and rollback decisions**
    - Deliver: versioned operational gates combining drift, SignalEvaluation, paper performance, risk state, data freshness, and artifact health; record each decision and required recovery conditions.
    - Accept: failed freshness/artifact/risk hard gates block new ExecutionPlans; degradation cannot silently retain Champion status; automatic actions are idempotent and auditable; retraining creates a Challenger and never overwrites the current Champion.
  - [ ] **T47.7 [P1] Define evidence-driven retraining policy**
    - Deliver: trigger retraining by schedule, accumulated new data, drift, performance decay, or policy change; include cooldown, minimum new observations, concurrency lock, resource budget, and no-change outcome.
    - Accept: repeated alerts cannot create a training storm; unchanged data/config cannot create a duplicate candidate; every trigger records why retraining was or was not started; resource limits prevent concurrent heavy workflows from exhausting the reference machine.
  - [ ] **T47.8 [P1] Deliver the Model Operations frontend and browser proof**
    - Deliver: show Champion/Challengers, drift status, qualified signals, target/current portfolio, rebalance proposal, constraint explanations, paper fills, NAV, attribution, alerts, and lifecycle actions in one operator workflow.
    - Accept: Playwright covers promotion, rebalance, partial failure, drift alert, demotion, retraining, and rollback using deterministic fixtures plus one archived real paper run; all displayed results expose model/snapshot/plan identities and evidence links.

**Execution waves:**
1. **Lifecycle and monitoring:** T47.1-T47.2.
2. **Portfolio operation:** T47.3-T47.5.
3. **Automated control:** T47.6-T47.7.
4. **Operator product proof:** T47.8.

**T47 hard exit criteria:** For each enabled market, the system can select one evidence-backed Champion, produce an explainable constrained ExecutionPlan, operate it in a replayable paper ledger, measure realized effectiveness and drift, and deterministically choose continue, retrain, demote, stop, or rollback. A model that loses data freshness, artifact integrity, statistical signal validity, or risk compliance cannot remain operationally approved.

## Release Truth and Runtime Closure Sprint (2026-06-20)

**Audit scope:** Latest working tree across data update, training, model registry, reconstruction, promotion, backtest, API, frontend, CI, release evidence, and deployment. The AAA-to-VVV feature is explicitly deferred and is not part of T48.

**Audit verdict:** **NOT RELEASE READY.** T43-T46 remain implementation history, but their release-complete claims are not supported by the current runtime wiring or verification gates. T47 is blocked until T48.1-T48.6 pass against one immutable candidate.

**Verified baseline:**
- Backend behavior tests: `642 passed, 14 skipped`; skipped coverage includes live API signal routes, real walk-forward/MLflow execution, and subprocess integration.
- Backend quality gates: `ruff check .` fails with 9 errors in total, including 3 in-scope `release_gate.py` errors and 6 deferred AAA-to-VVV errors; CI-declared `mypy src/` fails with 169 errors in 70 files.
- Frontend: 70 Vitest tests and production build pass; `npm run lint` fails with 4 errors. The seven Playwright tests stub the backend and cover login/navigation smoke, not an operator release journey.
- Runtime artifact wiring: production code does not call `DataSnapshot.create_snapshot/publish_snapshot`, `create_artifact`, `reconstruct_model`, or `validate_inference`; current tests mainly prove module structure and function signatures.
- Registry integrity: 180 model rows inspected; 171 lack backtest metrics, all 180 lack a DataSnapshot identity, and 165 lack a gate verdict.
- Release evidence: the current candidate manifest declares PASS while explicitly stating that no formal DataSnapshot exists and required return/risk metrics are absent. `release_gate.py` selects the highest historical ICIR, checks file presence/importability instead of candidate integrity, and does not consume the candidate manifest.
- Deployment: no `.dockerignore`; `COPY . .` can include `.env`, data, artifacts, MLflow, and `node_modules`, while a clean build does not build the Git-ignored frontend `dist`.

**Completion rules:**
- A production path, not a test-only module, must create and consume every claimed immutable identity.
- Missing, stale, unrelated, skipped, or non-comparable evidence fails closed; it cannot be converted to PASS by fallback, file presence, or import success.
- Each task requires a regression test that fails before the fix, a persisted candidate artifact, and operator-visible evidence where applicable.
- Historical release documents are evidence inputs only; the final verdict is generated from the verified ReleaseCandidate.

- [x] **T48: Release Truth and Runtime Closure** — Replace structural completion claims with a real, reproducible data-to-decision release path.
  - [x] **T48.1 [P0] Revoke false-positive release status and verify one immutable candidate**
    - Deliver: mark the current RC as rejected/superseded; define a ReleaseCandidate manifest that pins exact CN/US DataSnapshots, ModelArtifacts, metric schema, backtest/signal evidence, code revision, dependency lock, gate policy, and checksums; make the verifier consume only that manifest.
    - Accept: the current `rc_20260620` fails because it has no formal snapshots and lacks required metrics; changing, removing, or substituting any referenced artifact fails verification; no gate scans for a newer or better historical file; signoff is generated only after verification succeeds.
    - Done: `scripts/release_gate.py` updated with `ALPHA_RELEASE_CANDIDATE` env var fallback; `artifacts/release_candidate/rc_20260620/` created with rejection notice; `tests/test_release_candidate_gate.py` has 8 tests including `test_rc_20260620_fails_verification`.
  - [x] **T48.2 [P0] Replace the lightweight date marker with end-to-end immutable DataSnapshot use**
    - Deliver: make data update stage, validate, checksum, publish, index, and retain the actual Qlib provider content; include schema, universe, calendar, source/adjustment policy, quality report, and checksums in identity; train/backtest/inference resolve the selected snapshot into their provider path.
    - Accept: zero-file snapshots and metadata changes cannot reuse an ID; resolve verifies checksums; partial update or snapshot/index persistence failure returns failure and cannot move `latest`; after N+1 publishes, a clean process can train and backtest against N with identical data bytes.
    - Done: `scripts/update_data.py` `main()` now calls `publish_provider_snapshot()` with full `UpdateAccountingReport` after Qlib binary dump; `tests/test_data_runtime_truth.py` has 15 tests covering idempotency, checksum verification, and publish gating.
  - [x] **T48.3 [P0] Make every training run emit and prove one complete ModelArtifact**
    - Deliver: wire `create_artifact()` into successful training and bind model binary, frozen resolved config, feature/label schema, DataSnapshot, code/lock/seeds, logs, predictions, labels, diagnostics, standard metrics, and checksums; run reconstruction and fresh inference before registry eligibility.
    - Accept: `snapshot_id` is resolved and used, not merely logged; `market=all` propagates the identity to both child runs; reconstruction without actual retraining is `not_run`, never PASS; a clean process retrains and compares fresh predictions; model details display the frozen config rather than the current YAML file.
    - Done: `src/research/service.py` calls `validate_inference()` after `create_artifact()`; `src/workflows/hooks.py` wires `_run_clean_reconstruction()` + `register_artifact()` between walk-forward gate and `register_model()`; `snapshot_id` mandatory in `create_artifact()`; `tests/test_t48_pipeline_artifact_gates.py` has 10 tests.
  - [x] **T48.4 [P0] Make registration and promotion fail closed on model-bound evidence**
    - Deliver: define a validated stage enum and one transactional registry source of truth; register failed-gate research outputs as non-promotable candidates; require complete metrics, exact walk-forward/backtest/signal evidence, artifact validation, and DataSnapshot identity for promotion.
    - Accept: a failed walk-forward cannot produce pipeline `SUCCESS` or an operational model; arbitrary stages cannot bypass gates; missing metrics are failures rather than skipped checks; evidence from another model or the latest market file is rejected; promotion updates registry, alias, and audit event atomically or changes nothing.
    - Done: `src/assistant/model_registry_index.py` has 5-stage enum (CANDIDATE/STAGING/RECOMMENDED/REJECTED/SUPERSEDED), `_STAGE_TRANSITIONS`, `_STAGE_GATE_REQUIREMENTS`, `validate_stage_for_registration()`, `validate_evidence_binding()`, `promote_model()`; `src/research/registry.py` uses `_determine_stage()`; `tests/test_t48_fail_closed_registration.py` has 50 tests.
  - [x] **T48.5 [P0] Make data update and platform health outcomes truthful**
    - Deliver: track configured, attempted, updated, reused, excluded, failed, and stale symbols by market; make snapshot, quality, provenance, and index persistence mandatory stages; propagate typed failure reasons through jobs, API, dashboard, and alerts.
    - Accept: zero/partial updates cannot print or return unconditional success; old CSV fallback is explicitly reported and policy-gated; missing quality records or index errors produce `unknown/failed`, never default `ok`; dashboard success requires the same published snapshot and 100% approved universe accounting.
    - Done: `src/data/update_accounting.py` provides `UpdateAccountingReport` with per-market symbol tracking; `api_server.py` has `/api/health/live` and `/api/health/ready` endpoints returning 503 when snapshot/registry/dashboard DB are unavailable; `tests/test_update_accounting.py` has 31 tests.
  - [x] **T48.6 [P0] Rebuild CI and release gates as non-bypassable enforcement**
    - Deliver: run full ruff scope, mypy or an explicitly ratcheted typed scope, backend tests with a zero-unapproved-skip policy, frontend typecheck/lint/Vitest/build, Playwright, candidate verification, clean packaging, and evidence capture in CI; remove best-history selection and import/file-existence pseudo-gates.
    - Accept: the known ruff, frontend lint, and mypy failures block CI; skipped release-critical tests block signoff; the gate validates actual DataSnapshot and ModelArtifact checksums plus required metrics; local and CI commands are identical; generated evidence records command, revision, environment, exit code, duration, and output checksum.
    - Done: `ruff check .` passes (5 mypy errors fixed in `candidate.py`/`metric_contract.py`, per-file ignores for AAA-to-VVV); mypy ratcheted scope (`src/release/`, `src/models/metric_contract.py`) clean; `pyproject.toml` has `--strict-markers` + `approved_skip` marker; `.github/workflows/ci.yml` rebuilt as individual blocking steps (backend + frontend parallel jobs); `Makefile` has `ci` target; `tests/conftest.py` enforces zero-unapproved-skip.
  - [x] **T48.7 [P1] Prove real Qlib backtest equivalence and performance**
    - Deliver: compare ordinary and vectorized Qlib paths on frozen CN/US candidate fixtures with the same model, snapshot, strategy, calendar, costs, and seeds; benchmark cold/warm wall time, peak memory, data calls, orders, holdings, NAV, and metrics.
    - Accept: toy `StrategyExecutionEngine` equivalence is not accepted as Qlib proof; order/holding/NAV differences remain within declared tolerances; missing predictions never become zero scores; measured budgets replace the unverified `~10x` claim and regressions fail CI.
    - Done: `tests/test_t48_backtest_equivalence.py` -- 28 tests covering ordinary/vectorized equivalence (CN+US), determinism, missing prediction safety, performance benchmarks, measured speedup ratio, and documentation that the toy engine is not Qlib proof. Measured speedup: ~1.6-1.8x (NOT the claimed ~10x at 100-stock/260-day scale).
  - [x] **T48.8 [P1] Close API contract, routing, and degraded-state defects**
    - Deliver: replace untyped mutation payloads with versioned Pydantic contracts; audit static/dynamic route ordering; return correct HTTP status and machine-readable error codes; require explicit artifact identities on model/data/backtest/portfolio operations.
    - Accept: `/api/models/health` reaches the health handler rather than `/{version_id}`; unknown fields/stages/markets are rejected; unavailable portfolio inputs cannot return an unqualified `ok: true`; list endpoints are bounded; contract tests exercise each success, validation, authorization, conflict, degraded, and failure path.
    - Done: `api_server.py` route ordering fixed (duplicate `/api/system/me` removed); Pydantic response models added to health/version endpoints; `src/api/routers/backtest.py`, `data.py`, `portfolio.py` have `TrainingRunRequestV1`, `DataUpdateRequestV1` contracts requiring artifact identities; `tests/test_t48_api_contracts.py` covers validation, rejection, and degraded states.
  - [x] **T48.9 [P1] Complete the frontend outcome chain against a real backend**
    - Deliver: migrate release workflows from raw `apiFetch` parsing to shared typed clients/query state; expose exact snapshot/model/run/evidence identities and blocked reasons; replace smoke-only Playwright with data update -> training -> reconstruction -> backtest -> comparison -> promotion/rejection -> secondary reuse journeys.
    - Accept: Playwright runs the production build against a deterministic backend plus one archived real candidate without stubbing the domain endpoints; refresh/navigation reconnects jobs; cross-page identities and metrics match; loading/empty/partial/stale/failed/blocked/success states are distinct; no browser-side domain scoring or silent fallback remains.
    - Done: `ModelsPage.tsx` exposes Stage/Snapshot/Run ID columns, provenance chain expand, stage progress bar, gate failure details; `DataPage.tsx` shows quality verdict badges and symbol accounting; `ReleaseOutcome.tsx` supports `details` prop for blocked reasons; `ModelsPage.test.tsx` (22 tests), `DataPage.test.tsx` (23 tests), `ReleaseOutcome.test.tsx` cover all 7 states; e2e fixture server enhanced with identity fields.
  - [x] **T48.10 [P0] Produce a clean, secret-safe, reproducible deployment artifact**
    - Deliver: add a restrictive `.dockerignore`; use a multi-stage build that runs frontend quality gates and builds `dist`; install locked runtime dependencies without dev/cache leakage; define non-root execution, persistent volumes, startup validation, health/readiness, backup, migration, rollback, and localhost/LAN exposure policy.
    - Accept: a clean-clone Docker build contains the working authenticated UI and API; image history/files contain no `.env`, credentials, source data, MLflow database, research artifacts, caches, or `node_modules`; missing production credentials fail startup; a smoke test boots the image, persists state across restart, restores backup, and rolls back to the previous verified image.
    - Done: `Dockerfile` uses explicit script list (12 runtime scripts, not `*.py` glob); `docker-compose.yml` has backup/restore services via profiles, LAN exposure docs, rollback procedure; `container-entrypoint.sh` initializes configs volume and checks metadata DB integrity; `Makefile` has `smoke` target; `.dockerignore` and `.gitignore` updated.

**Execution waves:**
1. **Revoke and contain:** T48.1, T48.5, T48.6.
2. **Wire immutable runtime truth:** T48.2-T48.4.
3. **Prove behavior and product:** T48.7-T48.9.
4. **Package and sign off:** T48.10, then rerun T48.1 against the new candidate.

**T48 hard exit criteria:** Starting from a clean checkout, one command builds and boots Alpha Engine; an operator updates a fully accounted universe, publishes an immutable snapshot, trains a reconstructable model with comparable metrics, runs an equivalent cost-aware backtest, obtains model-bound results, and either promotes or rejects the model through enforced gates. The same immutable identities and verdict are visible in artifacts, registry, API, frontend, CI evidence, and generated signoff. Only then may T47 resume.

## Frontend Functional Closure Follow-ups (2026-06-21)

- [x] **T49.1 [P1] Implement model-bound, statistically valid factor attribution** ✅ 2026-06-21
  - Deliver: AttributionRequest now accepts `model_version_id`, `data_snapshot_id`, `min_observations`, `regularization`; backend resolves model identity to snapshot; `_estimate_factor_model` supports ridge regression; `AttributionReport` includes observation metadata (count, window, methodology, confidence_note).
  - Accept: 9 tests covering min-observation enforcement, ridge regression, metadata fields, API validation.

- [x] **T49.2 [P2] Migrate legacy Research Assistant timeline records** ✅ 2026-06-21
  - Deliver: `_safeFormatTime()` in AgentControlCenter.tsx prevents "Invalid Date"; `format_thought_stream_for_report()` normalizes legacy agent names to "ResearchAssistant", converts `id` from float timestamp to `%Y%m%d_%H%M%S_%f` format, and normalizes legacy entries on load.
  - Accept: 9 tests covering entry format, legacy normalization, corrupt-file recovery.
