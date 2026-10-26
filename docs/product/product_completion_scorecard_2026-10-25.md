# Alpha Engine product readiness scorecard — review baseline

**2026-10-25 / Initial evidence review, calibrated to owner-ratified
Direction A (personal quant workstation).** Not a production health
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
**70/100 is the pre-ratification baseline; selecting Direction A does not
increase it. v1 acceptance is a strict gate decision, NOT a target score.**
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

## Baseline diagnostic dimensions (historical; NOT the Direction A v1 release gates)

The following G0–G6 table documents the **original October 25 assessment**
only. Direction A has since selected **A0–A7** (below) as the authoritative
owner-acceptance contract. The legacy diagnostic labels are not a second
set of release gates.

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

## Direction A v1.0 release acceptance: hard gates, not an inflated score

Every gate has `PASS | FAIL | BLOCKED | NOT_TESTED` plus exact branch/main SHA,
market/evidence cutoff, responsible reviewer and retained evidence link.
A real source outage may be honestly `BLOCKED` and explained, but cannot be
relabeled a completed refresh. **No v1 release signoff while A0–A6 are
unproved**; the owner alone decides A7.

| Gate | Evidence of DONE (one-operator workstation) | Target |
| --- | --- | --- |
| A0 Identity/authority | Formal catalog, 4-strategy registry, sealed run and model identities agree | 100% active identity parity; no stale model presented as current |
| A1 Daily reliability | Per-market **20 eligible completed exchange sessions** of source/decision/publication/delivery evidence, including blockers and manual recovery; real due-cycle evidence beyond 20 sessions where necessary | 100% expected sessions explicitly classified; zero silent stale or unexplained P0 failures at release |
| A2 Data integrity | Market/PIT provider readiness, adjustments and source/cutoff manifests for all active strategy dependencies | Zero invented bars/fills, future-data leakage, unannounced substitution; independent research profiles may remain explicitly blocked |
| A3 User journeys | Four accepted strategies, desktop/mobile, change/unchanged-or-not-due/delayed-or-blocked/denied scenarios across Overview→Detail→Instrument→Status | Every applicable case has expected/observed receipt; zero critical factual mistake; missing fixtures = NOT_TESTED |
| A4 Security | Public formal asset audit; protected current-operation RLS/entitlement revocation/expiry and negative-read tests | Zero confirmed unauthorized protected allocations/targets, private no-cache leakage; maintain existing Pro/RLS controls |
| A5 Local research | One **accepted US and one accepted CN** repeatable local reference study, pinned dependencies/data/evaluator and cost/benchmark/PIT rules | Reproduced immutable evidence or explicitly BLOCKED; alpha returns and all archived factor models are not acceptance criteria |
| A6 Release/recovery | Pinned release SHA, existing CI/release gates, Pages/operations post-release read, operator runbook, rollback rehearsal | Reproducible publication/recovery without rewriting sealed evidence or installing another workflow/service |
| A7 Owner decision | A0–A6 evidence packet, residual risk list and dated review | Explicit single-operator owner GO/NO-GO; no PR/CI may silently declare v1 complete |

**Denominators:** count 20 eligible market sessions **separately** for CN and US;
holidays and not-due model evaluations are not failures. Check strategy cadence
from the current registry (e.g. CN_27 30 completed CN sessions, US x1.3
10 provider sessions), not assumed daily rebalance. If a due cycle is absent
within 20 sessions, attach separately verified actual due evidence or a
negative-path due contract test; do not fabricate in-window execution.
Maintain a complete incident log. Runtime latency targets are calibrated from
real observed stage durations, not selected post hoc to create PASS.

**Interpretation:** Architecture/CI tests can show a feature exists but cannot
certify 20-session production reliability, real entitled end-user UX or
reproducible return claims. Deferred RDI research #1272 is never a prerequisite
for A0–A7; its unvalidated 7/14/28-day evidence remains separate. A blocked
training profile unrelated to an active strategy does not invalidate that
strategy's valid retained formal history, but required local research
reproduction cannot claim PASS without its necessary source data.

**Execution ownership:** #1278 product truth; #1277 operating evidence;
#1279 privacy and UAT; #1282 accepted US/CN local replay (using
#324/#325/#826 only if evidence gaps require them); #1281 release/rollback.
Detailed waves: [Direction A local Agent roadmap](v1_direction_a_agent_roadmap_2026-10-25.md).

## Local implementation evidence addendum — 2026-10-25

Reviewed baseline: main/deployed `58a56c14c18197f700ab00b526513a571aff35be`,
formal/operating cutoff 2026-10-23. The original 70/100 heuristic and historical
review above remain unchanged. These are local Agent findings and reviewable
PRs, **not owner acceptance, automatic merge or a v1 release declaration**.

| Gate | Latest evidence classification | Review packet / exact remaining work |
| --- | --- | --- |
| A0 | PASS for current identity parity | Four registry/catalog identities and sealed sections agree; W0 authority reconciliation [#1283](https://github.com/liuh886/alpha_engine/pull/1283) awaits review |
| A1 | BLOCKED | [#1284](https://github.com/liuh886/alpha_engine/pull/1284): 211 captures / 27 formal attempts, only 7 observed / 0 independently qualified sessions per market; manual counts and actual due/recovery remain unqualified |
| A2 | BLOCKED | Doctor verifies all four current provider/formal/factor/decision cutoffs; independent complete required-source/PIT acceptance remains unproved; 2 unrelated blocked training profiles stay scoped |
| A3 | BLOCKED, ordinary journey subcheck PASS | [#1287](https://github.com/liuh886/alpha_engine/pull/1287): 8 real desktop/mobile four-strategy journeys, 2 existing live tests and 60 fixture tests pass; actual per-strategy changed/not-due/blocked/expired-account coverage remains incomplete |
| A4 | **FAIL** | Anonymous public CN_27 lineage contains `operating_state` current weights/targets/factor evidence: observed defect [#1288](https://github.com/liuh886/alpha_engine/issues/1288). Snapshot-only public-shell verifier misses this path. Owner must review integrity-preserving publication design and intended live tiers; real account expiry/revocation untested |
| A5 | BLOCKED, bounded CN/QQQ replay PASS | [#1289](https://github.com/liuh886/alpha_engine/pull/1289): CN frozen history repeats; missing source fails closed. [#1293](https://github.com/liuh886/alpha_engine/pull/1293) reuses the existing QQQ authoritative verifier, three identical successful CLI receipts and 34 affected tests. No paid provider required for this accepted research contract. Review/merge and owner acceptance pending; historical economic prefix integrity is distinct from recomputed decision-path evidence |
| A6 | BLOCKED | [#1290](https://github.com/liuh886/alpha_engine/pull/1290): exercised runbook/doctor/setup, actual deployment verification and local prior Pages artifact restore with 36 sections verified. No privacy-approved rollback target, new approved candidate, complete candidate quality report or private-current-state recovery |
| A7 | NOT_TESTED | Owner has not signed GO/NO-GO. **Agent recommendation: NO-GO** |

An independently observed operating defect was fixed narrowly in
[#1286](https://github.com/liuh886/alpha_engine/pull/1286): `jq -e` previously
aborted on a legitimate latest-main `publication_required=false` before its
semantic-no-change branch. 71 local tests and affected CI passed; actual
post-merge recovery is not claimed. Original failed run 40169478271:1 remains
failure evidence. This fix does not satisfy A1 or authorize publication.

Current live Supabase strategy policies declare public access; anonymous rows
are policy-authorized, not proof of unauthorized Pro access. That observation
is separate from the unconditional static lineage defect. No RLS/entitlement,
model, source, sealed evidence, workflow budget or production deployment was
changed. W1–W4 remain open where their real acceptance evidence is incomplete;
RDI remains independent. Review the linked PRs before deciding next actions.

## Delivery hardening follow-up — 2026-10-26

- Public Git is also a current-data bypass: five anonymous pinned-source reads
  succeeded. [Draft #1291](https://github.com/liuh886/alpha_engine/pull/1291)
  binds the whole publication boundary to existing private archives and explicit
  public historical projections. #1279 requires owner review before privacy
  implementation; A4 remains FAIL. Publicly disclosed Git history cannot be
  made confidential by a Pages-only repair.
- The full quality-only command ran: 12 of 13 commands passed; backend collection
  failed under local memory pressure. Subsequent existing-CI-style file shards
  exposed two stale active-CN-x1.2 assertions.
  [#1295](https://github.com/liuh886/alpha_engine/pull/1295) preserves historical
  package evidence and requires retired materialization to fail closed. Across
  all 500 files, unchanged passing shards plus the completely rerun fixed shard
  total **3938 passed, 8 approved skips, 0 failures**. The original FAIL stays
  retained. This composed backend result excludes the separate QQQ code change
  and is not a pinned integrated-candidate certificate.
- The original US professional-source blocker assessment was too broad: the
  accepted Yahoo research contract is already supported by the authoritative
  verifier. The generic CLI duplication is corrected in #1293 without changing
  models, pools, costs, source contracts or sealed evidence. Owner A5 acceptance
  remains pending. Reviewable progress does not satisfy A1, A4, A6 or A7.
