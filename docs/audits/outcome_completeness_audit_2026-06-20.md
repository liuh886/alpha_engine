# Alpha Engine Outcome Completeness Audit

Date: 2026-06-20
Status: Complete - release acceptance blocked pending T46

## Audit Objective

Verify Alpha Engine from durable outcomes rather than task completion claims:

1. Market data can be updated, persisted, versioned, and reused.
2. Model training is logged, reproducible, metric-complete, comparable, and backed by efficient backtesting.
3. Models produce trading signals whose stock-level effectiveness is measured, searchable, and visible in the dashboard.
4. A trained model cannot silently become unreconstructable, incomparable, or unable to produce actionable signals.

## Acceptance Model

Each outcome requires all four forms of evidence:

- Code: a durable module owns the behavior.
- Tests: failure paths and invariants are executable.
- Artifacts: a real persisted result can be inspected and reused.
- Product: the operator can observe and act on the result through a supported interface.

## Findings

### F1 - Critical: Data snapshots are mutable markers, not reusable data versions

Evidence:

- `scripts/update_data.py:288-323` overwrites the shared CSV source and rebuilds the shared `data/watchlist` provider in place.
- `src/assistant/data_snapshot.py:31-41` derives identity only from dataset, frequency, and latest calendar day.
- `src/assistant/data_snapshot.py:52-73` explicitly writes a lightweight latest marker whose `provider_uri` points at the mutable provider.
- `src/assistant/data_snapshot_index.py:62-68` updates an existing snapshot row on ID conflict.
- `scripts/update_data.py:325-337` and `scripts/update_data.py:339-396` suppress snapshot and quality persistence failures, then `scripts/update_data.py:398` reports completion.

Impact:

- Two materially different datasets ending on the same day share one snapshot ID.
- A historical training run references a mutable directory and cannot prove which bytes it consumed.
- Update success can be reported even when provenance, snapshot, or quality records were not saved.

Required outcome:

- A content-addressed, immutable DataSnapshot must own a manifest, checksums, source/provider versions, schema, universe, calendar, quality verdict, and resolvable storage location.
- Publishing `latest` must be an atomic pointer update performed only after provider validation, snapshot persistence, and reuse verification succeed.

### F2 - Critical: The model registry is polluted and does not enforce comparable evidence

Evidence:

- `tests/test_model_registry_run_binding.py` imports the global `MODELS_DIR` and writes through `Orchestrator._update_model_list`; repeated test execution has persisted dummy entries into the real registry.
- The current `artifacts/models/model_list.yaml` contains 177 entries: 168 have empty metrics, 128 use the test run ID `run_123`, and 36 reference missing model paths. The referenced test model is a five-byte text file containing `dummy`.
- `src/research/service.py:61-83` runs training and backtesting but returns no normalized metric set.
- `src/workflows/hooks.py:429-433` registers the model without supplying metrics.
- `src/research/registry.py:33-37` accepts an empty metric set and `src/research/registry.py:71-74` appends it to the source-of-truth registry.

Impact:

- The dashboard and comparison modules can display test records, missing artifacts, and metric-empty models as if they were real model versions.
- Training completion does not imply comparability or promotion readiness.
- Tests are not hermetic and can corrupt release evidence merely by being run.

Required outcome:

- Model registration must be transactional and reject missing artifacts, missing immutable DataSnapshot identity, missing reconstruction material, and missing required metric schema.
- Tests must use injected artifact roots and prove that the real registry is unchanged.
- Existing registry data must be audited, quarantined, and rebuilt from valid run artifacts.

### F3 - Critical: A trained model is serialized, but not reproducibly reconstructable

Evidence:

- `src/research/training.py:14-40` initializes from in-memory dictionaries, pickles the fitted object, and overwrites the market alias; it does not persist a canonical training manifest.
- `src/research/service.py:61-83` does not log the resolved workflow, immutable data content identity, code revision, dependency lock hash, random seeds, feature schema, or training diagnostics to the run.
- The only snapshot logging in this module is in re-backtest (`src/research/service.py:85-101`), not initial training, and the snapshot identity is itself mutable as described in F1.
- Existing tests verify registry binding and profile preference, but no test rebuilds a model from a saved manifest and compares predictions with the saved model.

Impact:

- A pickle may remain loadable while the exact training procedure is no longer reconstructable.
- Changes in data bytes, Qlib handlers, feature expressions, package versions, or random state cannot be distinguished from model changes.
- Successful deserialization is incorrectly treated as reproducibility.

Required outcome:

- A ModelArtifact must be an immutable package containing model binary, resolved workflow/config, feature and label schema, DataSnapshot ID and checksums, code/lock identity, seeds, training log, normalized metrics, predictions/labels, and artifact checksums.
- A reconstruction gate must retrain from the package and compare predictions/metrics within declared tolerances before a model can enter the comparable registry.

### F4 - Important: Backtest optimization exists as unused implementation, not a proven fast path

Evidence:

- `src/strategies/vectorized_engine.py` and `src/strategies/vectorized_strategy.py` implement a proposed precomputed path and claim an expected speedup.
- `configs/strategy_profile_cn.json:50` and `configs/strategy_profile_us.json:50` set `vectorized` to false.
- `configs/cn_lgbm_workflow.yaml:257-259` and `configs/us_lgbm_workflow.yaml:258-260` still select `BiweeklyTrendStrategy`.
- No test or benchmark compares ordinary and vectorized order streams, portfolio curves, metrics, runtime, memory, or `D.features()` call counts.
- `TASKS.md` correctly leaves T40 incomplete despite the presence of vectorized source files.

Impact:

- Release backtests still execute the ordinary strategy path.
- The advertised speedup and behavioral equivalence are unproven.
- Enabling the alternate path could change trading semantics without detection.

Required outcome:

- Build a deterministic golden backtest corpus and require identical decisions/curves within explicit tolerances.
- Record wall time, peak memory, data fetch count, and throughput for both paths; enable the fast path only after it meets a release budget and equivalence gate.

### F5 - Critical: Dashboard signal statistics are not reliably bound to the selected model

Evidence:

- The dashboard stores `selectedModelId` as the model registry ID (`qlib-dashboard/src/App.tsx:221-238` and `qlib-dashboard/src/components/ModelSelector.tsx:44`).
- `qlib-dashboard/src/pages/StockTerminal.tsx:271-288` and `qlib-dashboard/src/pages/BacktestPage.tsx:119-126` send that model version ID as the `run_id` query parameter.
- The backend loader expects an MLflow run directory (`src/api/routers/stock_analysis.py:990-1033`). If the requested ID is not found, execution falls through to a newest-file search (`src/api/routers/stock_analysis.py:1035-1077`) instead of returning not found.
- The current-grade endpoint has no run selector and always loads latest predictions (`src/api/routers/stock_analysis.py:1112-1139`).
- The Stock Terminal screener request omits the selected model entirely (`qlib-dashboard/src/pages/StockTerminal.tsx:350-368`).

Impact:

- Selecting model A can display signals and stock-effectiveness statistics from model B.
- A stale, deleted, test, or invalid model selection can silently produce plausible results from the latest unrelated prediction artifact.
- The UI cannot prove which ModelVersion generated a displayed BUY/SELL signal.

Required outcome:

- Introduce one resolvable ModelVersion -> run -> prediction artifact relationship and reject unresolved identity; never fall back when an explicit model/run was requested.
- Every signal, statistic, ranking row, and frontend view must return and display ModelVersion ID, run ID, prediction artifact checksum, DataSnapshot ID, and evaluation window.

### F6 - Important: Stock-level signal effectiveness is descriptive, not yet decision-grade

Evidence:

- `src/strategies/signal_grade_engine.py:400-537` computes overlapping raw forward returns but no benchmark-relative return, transaction costs, confidence interval, standard error, regime split, or minimum sample gate.
- `src/strategies/signal_grade_engine.py:517-521` approximates overlapping-return aggregation by dividing a sum by holding days; this is not an independently sampled portfolio return or a statistical correction.
- `src/strategies/signal_grade_engine.py:539-580` uses `abs(mean_return)` for sell grades, which rewards a sell signal even when the stock subsequently rises. The frontend independently repeats the same calculation at `qlib-dashboard/src/pages/StockTerminal.tsx:1068-1094`.
- Universe ranking preselects only `limit * 2` stocks by signal count before effectiveness sorting (`src/api/routers/stock_analysis.py:1335-1342` and `src/strategies/signal_grade_engine.py:768-805`), despite describing the result as an all-stock ranking.
- Signal endpoint tests are placeholders (`tests/test_signal_pipeline.py:180-202`), walk-forward signal tests are skipped (`tests/test_signal_pipeline.py:250-265`), and no test covers adverse sell returns or selected-model identity.

Impact:

- A high displayed score can reflect overlap, market beta, small samples, or the sell-score sign bug rather than tradable predictive value.
- Ranking can favor data availability and omit part of the universe without telling the operator.
- The frontend can present precision that the evidence does not support.

Required outcome:

- Define a versioned SignalEvaluation schema with direction-aware hit rate, excess forward return, cost-adjusted return, sample count, confidence interval, independent/non-overlapping evaluation, coverage, and out-of-sample flag.
- Rank only models/stocks meeting minimum evidence gates; expose excluded counts and reasons; compute the score once in the core module and render it without frontend reimplementation.

### F7 - Critical: The release gate is market-best evidence selection, not release-candidate verification

Evidence:

- `scripts/release_gate.py:50-70` selects the historical walk-forward file with the highest ICIR for each market, without binding it to a ModelVersion or release candidate.
- `scripts/release_gate.py:148-221` checks those files, the test suite, TypeScript, build, and bundle size; it does not verify immutable data reuse, model reconstruction, required metric completeness, model-specific predictions, signal effectiveness, or trading backtest budgets.
- `scripts/release_gate.py:188-201` runs the entire test suite, which currently triggers the registry pollution described in F2.
- `docs/release/data_model_trust.md` contains both PASS assessments and a final `NOT READY for production release` verdict with contradictory P0 blockers.
- `docs/release/rc_signoff.md` declares `Status: complete` while listing T43.12 as pending and accepting that trading Sharpe/Return/MDD remain uncomputed.

Impact:

- `OVERALL: PASS` can be produced from unrelated best historical evidence while the selected model is incomplete, unreconstructable, metric-empty, or unable to generate valid signals.
- Running the gate can change the evidence it is supposed to validate.
- Human-facing release status is not a trustworthy source of truth.

Required outcome:

- The release candidate must be an immutable manifest naming exact DataSnapshot, ModelArtifact, BacktestEvidence, SignalEvaluation, code/lock identity, and frontend build.
- The gate must verify only those identities, run in a hermetic workspace, reject contradictory/missing evidence, and emit one signed machine-readable verdict from which documentation is generated.

## Verification Log

- Inspected data update, snapshot indexing, training, model registration, promotion, backtesting, signal evaluation, stock ranking, frontend model selection, release gates, tests, and persisted artifacts.
- Measured the current model YAML registry: 177 entries, 168 with empty metrics, 128 with test run ID `run_123`, and 36 with missing model paths.
- Confirmed the test artifact `artifacts/models/us_model_20250102_000000.pkl` contains only the text `dummy`.
- Reproduced the sell-score defect: a VVV signal followed by +10% and a VVV signal followed by -10% both return the same A+ effectiveness result.
- Targeted backend verification was inconclusive because NumPy failed to load when Windows reported insufficient page file; a reduced snapshot run completed two tests before the interrupted session stopped without a final summary.
- Frontend Vitest did not start because its worker process failed with `spawn UNKNOWN` under the same resource pressure.
- Full pytest and `scripts/release_gate.py` were deliberately not rerun after proving that the current test suite can mutate the real model registry.

## Strengthening Plan

The executable plan is tracked as T46 in `TASKS.md`. Its design rules are:

1. Contain evidence corruption before adding features.
2. Make DataSnapshot, ModelArtifact, BacktestEvidence, and SignalEvaluation immutable identities, not loose files discovered by recency.
3. Make every consumer resolve exact identities; explicit requests must never fall back to latest.
4. Reject incomplete metrics and missing reconstruction material at registration time.
5. Separate predictive quality, trading quality, and operational reproducibility; all three are required for promotion.
6. Generate the dashboard and release verdict from the same verified artifacts.
7. Treat an ineffective model as a valid research result, but never as a tradable model.
