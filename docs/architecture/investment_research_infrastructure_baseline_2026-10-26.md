# Investment Research Infrastructure — audited baseline and reusable assets

**Review date:** 2026-10-26. **Baseline:** `main` commit `58a56c14c18197f700ab00b526513a571aff35be`; accepted US/CN common formal cutoff `2026-10-23`. The live production environment, unmerged branches and provider entitlements are **not** proven by reading GitHub manifests. Status labels below describe *verified repository contracts and recorded receipts*, not independently completed platform UAT.

## One-page assessment

**Keep and converge the existing data plane.** This is already a meaningful foundation: candidate identity and source gates, governed selected-pool prices, fundamental/corporate-action event contracts, factor catalog, readiness profiles, research execution and formal/negative evidence. It is not yet an independently demonstrated, researcher-friendly general-purpose PIT query/slice facility for many hypothesis families.

**Do not change the active v1 strategy surface while planning the long-term platform.** The four current strategy identities live in `configs/strategies/registry.json`, and the Console contract in `docs/product/strategy_console.md`. A website status view is not a general research API.

## A. Source of truth inventory and precise evidence

| Area | Existing authority or proof | Status and missing review |
| --- | --- | --- |
| Candidate / benchmark identity | `configs/research_universes/us_selected_equities_v2.yaml` (US87), `configs/research_universes/cn_selected_equities_v3.yaml` (CN130); `configs/pools/selected_pool_registry_v1.yaml` and `reference_instrument_registry_v1.yaml` | Existing *selected-pool* roles; general historical index membership and broader instruments are not implied |
| Data intake | Existing provider router, cutoff-aware fallback and cross-source overlap gates in `docs/architecture/repository_data_convergence.md` | Controlled within declared recipes; need data-family/source/rights and history audit before extending |
| PIT fundamentals | `configs/data_contracts/fundamental_event_store_v1.yaml`; `docs/research/fundamental_event_store_v1_2026-08-01.md` | Released/available/retrieved/revision distinctions are defined; real cross-domain vintage coverage and historical first availability require independent study-specific proof |
| Corporate actions | `configs/data_contracts/corporate_action_store_v1.yaml`; `docs/research/corporate_action_store_v1_2026-08-01.md` | Raw/adjusted price role and revision rules exist; lifecycle/pool coverage must be checked at actual required cutoffs |
| Dataset readiness | `configs/data_contracts/model_data_bundle_v1.yaml`; `data/research/model_data_bundle_v1/model-data-readiness.json` | 8 components: **5 ready, 3 partial, 0 blocked components** at published bundle; **2 blocked training profiles**. This is profile-specific, not global research completeness |
| Factors | `docs/research/factor_catalog_alpha158_v1_2026-08-01.md`; factor definitions/panels | Versioned Alpha158 exists; recorded factor validity ≠ economically validated signal; US Alpha158 profile still blocked |
| Research execution | `alpha research`, frozen study specs, `docs/research/model_optimization_campaigns.md`, `docs/research/static_to_pit_decomposition_results_2026-07-30.md` | Reproducibility and negative-result governance exist; audit how to launch and compare *different* question types without one-off orchestration |
| Formal operations | Strategy Decision Ledger; immutable Formal Model Run Bundle v2; Strategy Operations; Strategy Console | **Existing v1 application** — not a substitute for research-ready data slicing |
| RDI/event evidence | `configs/research_experiments/ashare_rdi_phase2_sources.yaml`, #1272, merged #1271/#1274/#1275 | Historical source families **not PIT-certified**. Some partial adapters, others not integrated; no validated predictive index or trade signal |

### Actual published `model_data_bundle_v1` component snapshot

The following **component-contract** statuses were read from the committed `data-components.json` (source cutoff per row; *not* a statement that all historical vintages or end-to-end studies pass):

| Component | Contract state | Ready / expected | Evidence cutoff |
| --- | --- | ---: | --- |
| CN selected prices | ready | 130 / 130 | 2026-10-23 |
| US selected prices | ready | 87 / 87 | 2026-10-23 |
| CN corporate actions | ready | 130 / 130 | 2026-09-04 |
| US corporate actions | ready | 87 / 87 | 2026-09-30 |
| QQQI/QQQ/TQQQ references | ready | 3 / 3 | 2026-10-14 |
| CN fundamentals | partial | 127 / 130 | 2026-09-04 |
| US fundamentals | partial | 86 / 87 | 2026-09-30 |
| CN Alpha158 panel | partial | 129 / 130 | 2026-09-04 |

The summary reports `us_selected_alpha158_v1` and `us_small_pool_price_plus_fundamentals_v1` as **blocked training profiles**. A ready price component dated 2026-10-23 does not upgrade 2026-09-04 company events or prove events were historically observable when needed. Partial/absent study inputs remain explicit; no universal “100% ready” claim.

## B. Review of the latest PRs (do not merge them through this plan)

All statuses below were checked as of this review against GitHub. Key pending PRs remain **open**, not accepted code/current main:

| PR / issue | Observed evidence | Relationship to this planning PR |
| --- | --- | --- |
| #1276 (draft) | Direction A v1, A0–A7 gates, W0–W4 plan | **Compatible but different horizon.** Keep v1’s single-user CLI + four-strategy Console and owner gate authority; ask owner to ratify long-term umbrella separately |
| #1283 | Reconcile obsolete docs with Console contract | Preserve the consolidation; do not add an unsanctioned second authoritative product document |
| #1284 / #1277 | 211 operating captures, 27 formal attempts, only 7 observed sessions per market / 0 independently qualified per audit | A1 remains BLOCKED; the data-platform vision does not waive 20-session real operational proof |
| #1287 / #1279 | 8 real desktop/mobile four-strategy navigation journeys, privacy and error-path gaps | Journey subchecks are not full v1 UAT/entitlement proof |
| #1291 (draft) / #1288 | Public current-operating-data exposure documented from Git/Pages; review proposes distinct historical projection identity without altering sealed records | **P0 safety**; do not propagate current/entitled signal payloads into “research data” or new static indexes |
| #1289 / #1293 | CN frozen reference replay; QQQ CLI reuse of accepted hash-bound Yahoo research verifier produces repeatable results in #1293 branch | Favor reuse of one authoritative runner/verifier. Claims remain branch evidence until review/merge; not a trade-ready claim |
| #1290 / #1281 | Owner runbook and A0–A7 **NO-GO** release packet | Maintain current release gates independently of infrastructure discovery work |
| #1295 / #1294 | Corrects stale tests demanding retired CN x1.2 active; CI-style composed 3,938 pass / 8 policy skips, while original monolithic memory failure retained | Preserve actual failure record; do not infer integrated current main quality certificate |
| #1274, #1275 (merged) / #1272 | RDI PIT/source/censoring scaffolding and explanatory research view | Ideal **readiness/blocked** case study, not a certified historical event dataset or strategy |

Additional existing work: #324 selected-pool PIT event population/coverage, #325 canonical VWAP/Alpha158 panels, #826 reproducible trainable-model execution, #1074 overall simplification. Do not create duplicate parent programs for them.

## C. Where the actual infrastructure gap lies

1. **Discovery fragmentation:** a trained developer can locate contracts, manifests and scripts; a researcher cannot yet rely on one proven “what datasets support this question?” journey. Audit existing `alpha data list` and component profiles first. The data registry is not automatically a research catalogue.
2. **Cross-domain PIT join semantics:** fundamentals have explicit `available_at`; corporate actions have event/revision dates; RDI narratives need first *historically provable* announcement or source visibility. No evidence yet of one independently tested, cross-domain “knowledge available as-of T” read over price + event + fundamental + membership. Do not invent it as already implemented.
3. **Readiness ≠ hypothesis eligibility:** a selected-pool training profile reports model-input coverage. It does not necessarily certify event sampling completeness, historical media coverage, region-specific identifiers, pre-event disclosure, or scientific suitability for RDI.
4. **Research path variation:** model-bound run/evaluation work is mature; prove what is reusable for non-ML, event-based, conditional-risk and market-timing hypotheses before designing adapters.
5. **Historical persistence and access:** large archives, Actions retention, immutable Git objects and protected current signals have different rights and operational boundaries. New catalogue or download endpoint could re-expose current allocations. Source licensing/redistribution policy requires per-family review.
6. **Researcher's time cost unmeasured:** no established measured baseline for minutes and bespoke operations from a new question to a valid manifest-bound research artifact; do not use PR counts or code size as proxy.

## D. Baseline audit work that must precede schema/code changes

For *each* data family used by cross-sectional ranking and RDI, capture the following in a **reviewed evidence matrix** (not a guessed checklist result):

- Exact currently active source/adapter, canonical contract, data path, manifest hash and storage/retention class.
- Symbol/entity identifiers and market calendars; universe event dates, permitted references, listing/lifecycle boundaries.
- Source observation start/end, missingness numerator/denominator, latest data cutoff, provider lag, historical point-in-time proof (separate from retrieval today).
- Event families: observed “zero”, source missing, not integrated, ambiguous duplicate event and revision correctness.
- Raw/adjusted vs historical execution price; timezone and currency; benchmark identity.
- Provider redistribution/legal status: `public_history`, `local_research_only`, `authorized_current_private`, or `unknown_requires_review`; this is **proposed classification**, not a new live entitlement policy.
- Existing callers, CLI/runner/CI/workflow consumers, cost to reuse, proof link and witnessed positive + negative read path.
- Classification: `usable_for_declared_study` / `usable_with_constraints` / `blocked` / `not_tested` with one precise reason per not-ready case.

**Audit outputs:** a source-linked family matrix, two minimal walkthroughs (ranking and RDI) marking which *existing* steps actually work, a measured reuse/time baseline and a scoped technical-gap list. The output may conclude no new platform abstraction is required.

## E. Non-negotiable acceptance for this draft planning PR

- No code, model identity, strategy weighting, signal, CI policy, security/RLS, dataset file, workflow schedule, accepted historical evidence or public frontend changed.
- Correctly distinguishes merged vs open PR evidence and `ready` component vs research eligibility.
- Explicit links to #1276, #324, #325, #826, #1074, #1272 and #1288; no task duplication.
- Cross-domain/PIT, security, licensing, storage, experiment repeatability and negative-result cases are in the roadmap.
- All suggested follow-up work remains **PROPOSED** pending user review; no presumed deadlines or performance promises.

See [product thesis](../product/investment_research_infrastructure_charter_2026-10-26.md) and [staged roadmap](../product/investment_research_infrastructure_roadmap_2026-10-26.md).
