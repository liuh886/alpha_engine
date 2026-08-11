# Model optimizer compatibility review — 2026-08-11

## Decision

The 19-commit local optimization branch documented by `HANDOFF_2026-08-11.md`
is **rejected for direct merge or formal-result adoption**. Its experiment ideas
may be resubmitted through the governed optimization-campaign compiler, but its
data foundation, unified factor library and model-specific runners must not be
introduced as parallel production paths.

This decision does not reject optimizer-assisted research. It makes the current
main implementation in `src/research/optimization_campaign.py` the only accepted
optimizer ingress: agents submit bounded candidate deltas; main freezes and
hashes data, factors, windows, costs, runner code and dependencies; the existing
spec-bound runner evaluates the baseline and all challengers together; no result
can promote automatically.

## Strict compatibility findings

1. **Data identity — failed.** The local `DataFoundation` computes a Python
   process `hash(tuple(expressions))` cache key, caps available data at a
   hard-coded date, and treats reinitializing a local provider as refresh. This
   is not the governed provider rebuild/publication chain and is not reproducible
   across processes.
2. **Factor identity — failed.** `src/factors/unified_library.py` introduces a
   second `FactorRecord`/`FactorLibrary`, compatibility wrappers and registry
   aggregation beside the canonical factor backend. This conflicts with #626's
   single-identity boundary and makes training/online factor parity unverifiable.
3. **Frozen context — failed.** The local contract accepts mutable provider,
   universe, factor and sector paths but does not bind their content digests,
   model-data bundle identity, runner source or dependency lock to every trial.
4. **Window isolation — failed.** The ranker runner hard-codes training windows
   instead of consuming the current spec-bound window policy and reporting-only
   exclusions.
5. **Cost economics — failed.** Ranker stress applies
   `return * (1 - cost_rate / cadence)` rather than deducting
   `turnover * cost_bps / 10_000`. It also retrains and predicts once per cost
   level even though only the cost calculation changes.
6. **Portfolio constraint — failed.** Sector-capped selection fills remaining
   slots with names that violate the cap. A constraint silently becomes an
   unconstrained global Top-N portfolio.
7. **Computation reuse — failed.** Data may be cached, but the base runner loops
   window × candidate × cost and calls the full evaluator each time. Model fitting
   is therefore repeated for every cost stress. Current main instead compiles all
   candidates into one union-feature experiment.
8. **Formal and operational continuity — failed.** Local receipts are not bound
   to Bundle v2 identities, accepted formal evidence, prospective gates, current
   signal generation or frontend publication. Reported optimizer winners cannot
   enter model promotion or live signal refresh safely.
9. **Independent certification — failed.** The CN result inherits the invalid
   sector fallback and cost treatment already recorded in #766. The US handoff
   conclusion is superseded by the corrected governed certification in #770.
10. **Test evidence — failed.** The branch adds the new infrastructure and
    results without dedicated tests covering identity, cost reconciliation,
    constraint fail-closed behavior, window leakage or formal publication.

## Accepted salvage path

- Keep declarative candidate proposals, but translate them to the bounded
  `factor_groups` and `xgb_native` search axes accepted by the current campaign
  compiler.
- Keep the intent to reuse feature matrices, but use the existing
  `single_experiment_union_feature_load` runner path. Cost stresses must reuse
  predictions and recompute only turnover-derived net returns.
- Preserve local experimental results only as untrusted hypotheses. Re-run them
  against one exact model-data bundle and provider identity; do not import their
  scores or promotion claims.
- Add rotator and timer optimizer support only by extending the same fixed-context
  compiler contract. They must not ship separate factor, data, metric or promotion
  backends.

## Admission gates for any future optimizer

An optimizer is compatible only when all of the following are machine-verified:

- exact provider identity and evidence cutoff match the ready model-data profile;
- factor library and frozen model files are content-hashed and canonical;
- runner source and dependency lock identities are recorded and reverified;
- selection, reporting-only and prospective windows cannot be reassigned by a candidate;
- baseline and challengers share one data load and one fixed context;
- identical candidates, including a baseline clone, are rejected before execution;
- cost stress deducts turnover-derived costs without refitting the model;
- portfolio constraints fail closed rather than falling back silently;
- results remain `research_only=true`, `trade_ready=false`, and cannot promote automatically;
- formal evidence, current model-data refresh, signal publication and frontend methodology
  all consume explicit identities rather than model-id inference or compatibility fallbacks.

Until these gates pass, optimizer output is hypothesis-generation evidence only.
