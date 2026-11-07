# P2 · Colab-first Research Compute Plane

> Owner direction, 2026-11-06. **Architecture and implementation backlog**, not a claim of an executed Colab training job. Authoritative work item: [#1373](https://github.com/liuh886/alpha_engine/issues/1373). E1-A real local/Colab acceptance: [#1369](https://github.com/liuh886/alpha_engine/issues/1369). Data: [#1370](https://github.com/liuh886/alpha_engine/issues/1370).

## Decision

**Strategy authoring and evidence authority stay local; compute-intensive training, exploration and optimization should normally run in Colab when cloud data rights and execution resources allow.** An owner-run, ephemeral Colab kernel is a replaceable batch worker. It is not an always-on inference service, unattended broker, market data master, web-exposed compute API or permanent experiment scheduler. The Pages frontend remains read-only.

Reconcile the original P2 local-only policy: *local-owned research definitions and governance* does **not** require all heavy computation to execute on the local workstation. Local baselines remain important for determinism and independent validation. The approved compute boundary is **daily or slower**, with current US87/CN130 pools and explicit data/rights qualifications.

## Actual reusable code (do not reinvent)

| Existing authority | Portable compute use |
| --- | --- |
| `src/data/research_slice.py`, selected pool registry | Exact governed daily history, source/cutoff and basis; no silent missing-bar fill or pool substitution |
| `src/research/study_workspace.py`, `src/cli/main.py` | Existing `alpha research study init/run/show/compare`, frozen specs and immutable receipts |
| `src/research/studies/xgb_study.py`, `src/research/xgb_native_calibration.py` | Existing US cross-sectional XGBoost daily ranker; initial model-training baseline |
| `src/research/cross_sectional_experiment_runner.py` | Spec-driven cross-sectional research, fold-aware training and comparisons |
| `src/research/experiment_harness.py` and walk-forward/replay modules | Development/selection/holdout separation, costs and governance |
| `src/research/study_review.py` | Local counterevidence, source acceptance and human-reviewed decisions |
| P2-D0 v5 / `src/research/e1a_price_preflight.py` | Immutable physical US/CN snapshots; v5-specific verification (legacy `cloud_exchange.stage` is *not* compatible with v5) |

Four existing research-study templates are **not** an arbitrary multi-model search service. Model comparison normalization, portable batch execution, resume, and selection-adjusted inference still require implementation. First reuse existing XGBoost and a simple baseline before introducing LightGBM and later neural models.

## Compute / evidence protocol

```text
Operator + local Agent
  hypothesis → frozen batch_spec.json → Git revision / exact pool-data manifest
                |
                | per-provider cloud-compute rights + owner initiation
                v
Private Google Drive (exchange only, not authority)
  approved input files / input manifest → incoming_unreviewed / checkpoints
                |
                v
Google Colab (ephemeral notebook launcher, identical Python CLI)
  verify SHA and pool → local scratch copy → feature prep / train / HPO
  → time-ordered walk-forward → stress tests → checkpoint → run receipt
                |
                v
Local Agent
  verify returned hashes and source lineage → independent metrics/robustness review
  → Study Workspace / Study Review → optional reviewed read-only frontend summary
```

The **job spec** is a thin versioned wrapper around the existing research study/experiment specs, not a second research registry:

| Group | Required fields or behavior |
| --- | --- |
| Identity | `job_id`, hypothesis/study ID, complete experiment-spec SHA, exact Git SHA, Python/uv lock SHA |
| Data/rights | selected pool ID and hash, source family/archive sha, cutoff, adjustment/price/volume semantics, explicit per-recipe cloud rights approval |
| Evaluation | chronological train/validation/untouched-test windows, purge/embargo if labels overlap, benchmark and cost policy, missingness and survivorship limitations |
| Search | predefined model candidates, feature sets, hyperparameter distributions, seeds, trial/fold budgets, metric and tie-breaking selection rule |
| Compute | CPU default, optional GPU only if measured useful; max trials, duration, memory, checkpoint frequency; no live provider fallback |
| Artifacts | deterministic run identity; immutable per-trial metrics, failed trials, OOS/holdout metrics, checkpoint hashes, hardware/runtime trace, bundle of **unreviewed** outputs |
| Status | `research_only=true`, `trade_ready=false`, `pit_certified=false` until separate, specific governance acceptance |

**Critical distinction:** a full-US87 price-profile READY is an ingestion/coverage gate, **not** authorization to train an unrestricted predictive model, certify multi-vintage PIT, or claim trading profitability. Use truthful experiment-specific caveats. Source archive *producer* SHA and *experiment runner* SHA may differ, both must be pinned. The frozen v5 `owner_approved_private_cloud_copy=false` flag is **not** edited; provider-cloud rights reside in a separately reviewed, exact-SHA-bound operator record. Current vendor-source Colab processing rights are not independently established.

## Recommended staged experiments

**E2-0 — One actual portable research job.** Complete E1-A only as a narrow real-bytes/path/rights/CLI parity gate. Stage the v5 US87 price package under an isolated **read-only** research root. Use the existing `cross_sectional_xgb_v1` study or corresponding governed XGBoost runner; do not create a new model/CLI before it is proven runnable. Its current default is eight US technology names: scaling to all 87 requires checking individual start dates, fold support and benchmark alignment. Provide an actual US87/QQQ study receipt (or precise `BLOCKED` reason). Pin experiment SHA independently of frozen producer SHA.

**E2-1 — Train and compare multiple models.** First XGBoost plus a naive rank/momentum baseline on the same data/folds/costs; optionally LightGBM once common input/output identity works. Validate meaningful OOS evidence against QQQ and equal-weight selected-pool baseline. Compare available features and ablations without target leakage. CN Alpha158 is a separate factor family with older cutoff and declared short-history/NaN partitions; do not mix US/CN data families just to enlarge training.

**E2-2 — Bounded HPO.** Add only a small search adapter, e.g., Optuna if introduced as an optional dependency, reuse existing model trainers. Initial controlled budget: configurable **20–50 trials**, `3` chronological folds, `3` seeds. Reserve a final untouched test; selection on validation only. Record every trial, including pruned and failed runs; include multiple-testing and sensitivity caveats. These are experimental budget suggestions, **not** a guarantee of compute availability.

**E2-3 — Robustness / higher-complexity candidates.** Cost/slippage stress, market regime, cross-window stability, universe selection/survivorship sensitivity, feature importance and perturbation checks. Consider sequence networks/Transformers/GPU only when sample size, forecast horizon, out-of-sample benefit and **measured** CPU bottleneck justify them. For a single US87 daily snapshot of ~2021–2026, increasing model capacity can easily amplify overfitting rather than alpha.

**E2-4 — Resume and local review.** Checkpoint fold/trial boundaries to Drive after explicit private-path verification. Colab runtime is ephemeral; a restart must validate exact spec/code/data hashes and skip completed trial IDs. Training outputs return to `incoming_unreviewed`, never auto-promote to formal strategy, Q ledger, public GitHub Pages or execution. One local review stage accepts or rejects evidence with source limitations retained.

## Colab capacity constraints

Google's official [Colab FAQ](https://research.google.com/colaboratory/faq.html) documents **variable GPU/TPU availability, usage limits, VM lifetime and idle termination**; free managed runtimes also restrict remote/headless/distributed-worker patterns. Do not build a 24×7 orchestrator around a free interactive notebook or promise a guaranteed GPU. Develop bounded, owner-triggered runs, restartable artifact-first experiments, CPU fallbacks and resource budgets. Colab Pro is not a substitute for provider data licensing. If the intended workload requires guaranteed long unattended jobs, that is a *separate future compute-backend decision* (e.g. dedicated authorized cloud runtime), not a hidden assumption of this P2 slice.

## Handoff and acceptance

- **Current state:** v5 physically delivered, six profiles 5 READY / 1 US Alpha158 BLOCKED; cloud root/history SHA verified. No real Colab study run; producer's local-only flags preserved.
- **Local Agent first:** complete E1-A local v5 isolated-root adapter and a repeatable real US price-only study; freeze one narrow spec; run minimal same-command local baseline; verify vendor rights for cloud execution before owner starts Colab. Do not expand #1368 into multi-model code.
- **Next implementation PR:** E2-0 portable job/batch contract plus first working Colab multi-experiment runner; code changes constrained to existing research modules, tests and notebook, not frontend/GitHub Actions scheduler. Track in [#1373](https://github.com/liuh886/alpha_engine/issues/1373).
- **Success metric:** at least one real model/baseline multi-fold, multi-seed training batch under approved input terms, with hashed result receipts, restartable trials, local/Colab parity and honest OOS interpretation. No profitability/trade-readiness claim.

This architecture amends **execution location**, not product scope, source truth, or release gates.
