# Alpha Engine product readiness scorecard — review baseline

**2026-10-25 / Draft architecture assessment.** Not a production health
certificate, external usability study, audit opinion or verified SLA.

## What can be substantiated

| Axis | Direct evidence | Assessment / remaining proof |
| --- | --- | --- |
| Governed strategy identity | `configs/strategies/registry.json` lists exactly **4** accepted formal strategies | Good source-of-truth boundaries; no new formal strategies justified |
| Historical evidence | `data/research/formal_model_runs/catalog.json` has 4 current records and formal cutoffs **2026-10-23** | Formal catalog exists; independent evidence replay and full section review still required |
| Data availability | `data/research/model_data_bundle_v1/model-data-readiness.json`, evidence cutoff **2026-10-23**; **5 ready / 3 partial / 0 blocked components**, **2 blocked training profiles** | Production data plane still not globally complete; don't erase legitimate partials |
| Operating controls | Decision Ledger, Strategy Operations, release governance and existing Actions; main CI/Pages/delivery runs present 2026-10-25 | No independently reviewed cumulative **20 eligible sessions** receipt verified in this review |
| Product UI | `/app`, strategy detail, linked instrument detail and `/system` in `docs/product/strategy_console.md` / frontend | Browser UAT across failure/permission/mobile scenarios not performed during this review |
| Access | `docs/architecture/frontend_access_control.md`, Supabase RLS and public/static split | Policy exists; end-to-end adversarial entitlement/privacy release tests need explicit acceptance |
| Automation | **39** workflow YAML files under `.github/workflows` = current declared ceiling; latest CI/publish activity | Lots of coordination; new workflows/duplicate truth paths are higher cost than narrow repairs |
| Research | PIT company events, factor/library and research governance; RDI Phase 2 source coverage **blocked/unvalidated** | Research ability is broad; success of individual predictive hypotheses not established |
| Documentation | `AGENTS.md` and `docs/product/strategy_console.md` reflect 4-strategy focused product | `docs/product_vision.md`, `TASKS.md`, `docs/product/RUNTIME_CAPABILITY_MATRIX.md` contain superseded UX/connected runtime descriptions |
| Open debt signals | #1074, #1113 (historical formal-block receipt), #1227 (weekly health incident), #1272 (RDI research) | Open ticket does not prove present failure; check latest evidence before closing or re-opening |

## Non-certified heuristic maturity: 70/100

A **consultant estimate** intended to focus discussion, not a measured KPI.
Weights and grades are explicitly subjective and require owner review.

| Dimension | Estimate / max | Evidence qualification |
| --- | ---: | --- |
| Research/evidence model | 17 / 20 | Strong provenance; accepted-model full reproduction and OOS certification incomplete |
| Data quality/coverage | 14 / 20 | 5 ready + 3 partial; two training profiles blocked |
| Operating closure | 10 / 20 | Working automatic flow; 20-session eligibility/repair reliability not yet verified here |
| Product UX | 10 / 15 | Focused core screens, linked explainability; actual task-based browser UAT not performed |
| Access/trust | 8 / 10 | Server-enforced policy contract; release UAT still needed |
| Delivery/governance | 11 / 15 | Versioned contracts/CI, but documentation drift, issue hygiene and workflow complexity |
| **Total** | **70 / 100** | **Provisional Beta**; not a prediction of engineering effort |

## Acceptance scorecard: evidence, not checkboxes alone

| Gate | Verifier / retained evidence | Entry criterion | Current classification |
| --- | --- | --- | --- |
| G0 Formal fleet parity | exact strategy registry, formal catalog and immutable manifests | 4 identities match, no retained false-active model | Source contract exists; verify on release |
| G1 Data honesty | source readiness, PIT/adjustments, stale/conflict reports | All required sources at correct cutoff or explicitly scoped blocked; no substitutions | Partial accepted; training gaps remain |
| G2 Daily operating qualification | 20 **eligible** trading sessions; per-session review with provider/decision/publication/delivery receipts and manual interventions | No invisible missing/old decision; correct not-due; no false pass for blocker | **Not independently certified** |
| G3 User acceptance | scenario-based desktop/mobile/browser scripts, screenshots, counterexample evidence | All 4 active strategies understandable in changed/unchanged/blocked/denied conditions | **Not independently certified** |
| G4 Permission / static boundary | RLS assertions and published site asset inspection | No unauthorized live holdings/targets; public history stays public; denied identity fails closed | **Needs evidence review** |
| G5 Release/rollback | linked candidate PR, quality receipts, actual deployed cutoffs, revert test | Deterministic publish, no partial semantic promotion; tested recovery | Contract exists, exercise gate |
| G6 Research reproducibility | source hashes, frozen model specs, results + failed variants | At least one reproducible US and CN accepted path, OOS discipline | **Not certified in this review** |

## Current blockers versus inferred facts

- Formal cutoffs at 2026-10-23 in a committed artifact are **not**
  proof that every current runtime read for every entitlement is fresh.
- A successful backend CI or Pages run does **not** prove the 20-session
  operational SLA, UX, or result correctness.
- Open historical incident Issues #1113/#1227 should be rechecked, but an
  open issue does **not** establish current degradation.
- Existing large repository and historic docs are not evidence that all
  historical features remain supported. Read maintained contracts first.
- Without a browser/e2e session here, visual quality judgments are **hypotheses**,
  not observed defects. Local agent must attach screenshots and observed repro.

## Ratification / revision procedure

Recalculate qualitative ratings only after new referenced evidence; don't
inflate completion percentage when adding code/tests without proving that the
user's main workflow is more reliable. Keep review date, evidence cutoff,
owner decision and failing counterexamples explicit.
