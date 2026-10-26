# Investment Research Infrastructure — phased transition and local Agent work orders

**Draft planning sequence:** 2026-10-26. **No implementation approved.** Owner review of [product thesis](investment_research_infrastructure_charter_2026-10-26.md) and [baseline](../architecture/investment_research_infrastructure_baseline_2026-10-26.md) precedes task activation.

## The north star

A researcher can freeze a **new falsifiable investment hypothesis**, enumerate available and missing PIT-safe inputs, construct an eligible historical dataset, run a reproducible evaluation with an honest baseline, and preserve results — **without re-implementing provider, identity, experiment or evidence plumbing**. This does not presuppose useful alpha or any automatic orders.

A *research-ready* dataset is not synonymous with “fetched” and a *valid experiment* is not synonymous with “profitable”. The long-term transformation builds **reusability**, not more models or UI pages.

## Dual-track sequencing

### Track A — existing v1 release / security obligations (continues immediately; not swallowed by this roadmap)

- **A-P0 publication confidentiality:** #1288 / draft #1291. Owner must decide the historical-public vs current-private boundary; repair/negative-test both public Git and Pages paths, preserve canonical hashes, verify permitted accounts, expiry and revocation. Do **not** copy current private decision/weight fields into a new research catalogue. A4 remains FAIL until independently proven fixed.
- **A-P0 operating truth:** #1277 / PR #1284 and #1285/#1286. 20 eligible sessions for each market, model cadence, genuine no-change and blocked evidence; pending real acceptance.
- **A-P1 delivery:** #1279/#1287 user/permission UAT, #1282/#1289/#1293 local reproducibility, #1281/#1290 release/rollback and #1294/#1295 full-suite retirement tests.
- **A-contract:** owner-selected Direction A draft #1276 and `AGENTS.md` remain binding. No new feature work should break existing 4-strategy Console.

**Do not call Track A “completed” just because the new infrastructure planning PR is merged.**

### Track B — reusable research infrastructure (new proposed work, without live runtime changes here)

| Wave | Priority | Objective | Proposed deliverable | Exit / negative path |
| --- | --- | --- | --- | --- |
| B0 — source and consumer audit | P0 design | Know what already exists and is usable | One machine-checkable or reviewed **source inventory**, reuse map and two end-to-end walkthroughs against current commands | Demonstrate accurate source/cutoff/permission blockers; **do not** claim inferred PIT or silently mark unavailable provider as ready |
| B1 — data-product contract convergence | P1 architecture | Make every dataset request comparable and explicit | Gap proposal mapping existing `model_data_bundle_v1`, selected-pool/reference IDs, PIT fundamentals, corporate-action events, factor panels and RDI event sources to a minimal common *query/receipt* vocabulary | No second authority; incompatible timing or raw/adjusted roles rejected; frozen artifacts unchanged |
| B2 — PIT slice prototype | P1 implementation only after B0/B1 | Reuse existing data to assemble an exact as-of research input | **One smallest local read/adapter vertical slice** for declared cutoff and frozen identities; if existing API suffices, merely document/test it | Revisions arriving later, unknown first availability, cross-market symbols, future membership, missing bars/events, provider conflict, private publication all **fail closed / remain explicit** |
| B3 — reusable experiment entry | P1 implementation only after B2 | Connect a research question to governed data and canonical evaluator | **One cross-sectional research path and one event/RDI readiness path** proving reuse of metadata, source/PIT gate and immutable evidence; RDI may correctly block until history certified | Exact source/experiment/benchmark identity and repeatable receipts; independent OOS; blocked studies cannot claim model performance |
| B4 — researcher usability | P2 after real friction evidence | Reduce effort to start/evaluate a new idea | Local CLI help/inspect or notebook demonstration using *existing* `alpha data` / `alpha research`; only add minimal interface if B0 measures a genuine gap | Measured lower manual steps/time; no browser research IDE, new database, scheduler, duplicate state or renamed strategy Console |
| B5 — maintenance / cost convergence | P2 continuous | Make reuse cheaper as data families expand | Provider/backfill and cache lifecycle audit, provenance/rights checks, explicit retirement opportunities, source availability observability | A verified reduction of duplicate work or bytes; changed source semantics and negative evidence preserved |

Waves are **dependency-driven**, not arbitrary dates. B0 and parts of B1 can proceed while Track A runs. No production rollout or new source ingestion is authorized by these proposals.

## Proposed ready-to-scope work packages after owner signoff

### RI-01 — current data assets, lineage and rights matrix (B0; docs + observed local proof)

**Owner outcome:** “Given a proposed hypothesis, I can see which data exists and whether it can legally and historically be used.”

- Inspect current provider adapters, selected-universe and reference registries; source/event/lifecycle contracts; `data/research/model_data_bundle_v1`. Link each family to *its existing authority*, retention class and actual source cutoff.
- Collect *real* recorded status for US87/CN130, benchmark/ETF, company events and RDI event families; preserve per-family missingness and zero-vs-unknown.
- Enumerate actual caller flow and source access restrictions; separate public historical research evidence from current entitled decision records.
- Test an unavailable, out-of-cutoff, amended and unauthorized request against current interfaces (or mark `not_tested` with exact gap).
- **DoD:** reviewable inventory with source anchors, verified vs partial vs absent/unknown; two reproducible walkthroughs, no new schema or ingestion, all sensitive values excluded.
- **Reuse/dependencies:** #324, #325, #1272; do not open duplicate population tasks.

### RI-02 — historical information-state semantics review (B1; ADR proposal, not code)

**Owner outcome:** “At date T, show what an investor could have *known*, not what the provider reports now.”

- Compare price bars and provider cutoff, universe historical membership, fundamental `reported_at`/`available_at`/`retrieved_at`/`revision_sequence`, corporate actions announced/ex/effective/revisions and RDI story events’ first verifiable release.
- Specify family-specific `as_of` and knowledge/availability rules, historical correction replay, timezone calendar, adjusted-price anchors, late/restated filings and missingness classification.
- Explicitly distinguish **event_date**, **released_at**, **first_known_at** (only if externally verifiable), **retrieved_at**, and **revision/vintage**. A contemporary scrape timestamp is never proof of first publication in an old market episode.
- Produce **contract-to-contract mapping** to existing files. New representation only if a concrete consumer cannot use the current ones.
- **DoD:** examples for one US filing, one CN corporate action and one RDI story; negative PIT test matrix; zero contract “readiness inflation”; architecture owner approval before schema code.

### RI-03 — minimal cross-domain research slice and coverage gate (B2; narrow implementation)

**Owner outcome:** “I can reuse a verified market universe, bars and a date-bound fact/event without stitching bespoke scripts.”

- Reuse current canonical readers and manifests; choose one tiny fixed US or CN sample with documented source availability, frozen decision time and an existing comparator.
- If B0 discovers existing slicing already meets the requirement, implement *tests/docs only* rather than a second API.
- Store a *receipt* referencing source and transformation versions; avoid copying full raw datasets. Ineligible missing events/first-known-time should return a structured BLOCKED reason, not an empty zero series.
- **Negative cases:** after-cutoff revision, adjusted/raw mismatch, symbol alias or delisting, unavailable PIT timestamp, invalid hash, wrong market, restricted current weights leak, benchmark-as-candidate.
- **DoD:** determinism, byte/tolerance evidence, original source unchanged, exact contract tests and no new permanent workflow.

### RI-04 — research mission reference experiments (B3; after RI-03)

**Owner outcome:** “Two different hypotheses can share a valid data-to-evidence protocol without sharing model logic.”

- **Case 1:** a *frozen* selected-universe/cross-sectional study, using existing canonical research executor and one declared evaluation period. No re-optimization of the terminated OHLCV ranker family, no ‘alpha recovered’ claim.
- **Case 2:** the RDI hypothesis and 7/14/28-day evidence *readiness* at a fixed cutoff. Use #1272’s coverage limits. If historical first-time publication or CSI300 date range is missing, output `blocked`, not a synthetic prediction/backtest.
- Shared minimum: source receipts, PIT and lookahead barriers, benchmark/label/horizon definitions, risk/return outcomes if eligible, negative results and owner-readable reason for block. No automatic formal strategy promotion.
- **DoD:** evidence of *shared plumbing* and explicit unique model logic, as well as a verified blocked case; research correctness evaluated independently from investment profitability.
- **Reuse:** #826 for trainable execution; do not fork the model-training pipeline.

### RI-05 — research entrypoint experience and economics (B4/B5; only after measured trial)

**Owner outcome:** “Starting a legitimate new research question becomes cheaper and more predictable.”

- Have one operator run a frozen research request and measure number of manual scripts, duplicated data downloads, elapsed human effort, stored duplicate bytes, source errors and time to interpretable evidence.
- Fix the single highest documented workflow friction, **preferably by enhancing an existing interface** rather than restoring retired Research Studio or adding a general-purpose web product.
- **DoD:** before/after journey with verified SHA + dataset cutoff, dependency and rollback, one failure injection; measurable net decrease in work without expanding permanent complexity.
- Scope one small issue per actual defect.

## Acceptance examples: not predictions or model features

| Scenario | Expected platform result |
| --- | --- |
| Historical price/fundamental sample with fully certified source and information cutoff | Return exact PIT-eligible data or named existing artifacts + hashes, roles, quality and cutoff |
| An earnings datum revised *after* the research decision date | Original known-at-cutoff value only (if provable), not hindsight revision |
| Risk-event count requested for a period with unavailable archives | Mark **unknown/blocked**, not zero |
| Index member not yet listed or admitted at historical decision date | Exclude or fail under declared membership contract; never silently substitute |
| Source unavailable, conflicting raw/adjusted base, licence restricts export | Scoped blocker with reusable valid unaffected evidence, no unauthorized public asset |
| Experiment tested against a known failed ranker or an unsupported RDI study | Preserve negative/blocked result and exact reason; never auto-promote a strategy |
| Run repeated against pinned data, code, evaluator and costs | Same result or justified declared tolerance with a frozen receipt |
| Public source/index generation | No current protected strategy targets/weights, even from ledger/lineage or CI artifacts |

## Proposed task and PR governance

- This parent PR: **docs only**, draft discussion, no implementation/issue creation yet. After owner ratifies D1–D5 in the charter, create RI-01 and RI-02 scoped issues first; RI-03/04/05 are *candidate* future tasks, not preapproved coding tickets.
- Each agent issue must specify **observed problem, user outcome, current SHA and source cutoffs, touched authority, reuse map, positive/negative tests, frozen research and confidentiality boundaries, DoD, rollback and remaining blockers**. One issue → one branch → one narrow PR.
- No new permanent workflow beyond the declared 39 ceiling, second canonical manifest/db, read-write browser research route, automatic trades, broad rerun of historical model selection, external subscription purchase or SaaS features without a separate approved decision.
- Required change management: accept/reject architecture proposal; compare touched paths with ongoing #1276/#1283/#1291 before implementing; keep original negative research and operational incident evidence; never merge two different authority contracts by accident.

## Review checklist for the owner and architect

- [ ] Ratify long-term “Investment Research Infrastructure” umbrella *without* unfreezing Direction A v1 delivery.
- [ ] Confirm first-pass scope (US87/CN130 + current ETF/reference + existing RDI source inventory).
- [ ] Accept local research interface first, not resurrected browser IDE.
- [ ] Confirm B0 source-rights/information-cutoff evidence is mandatory before new data provider procurement.
- [ ] Decide whether RI-01/RI-02 may be handed to local Agent as separate issues.
- [ ] Confirm #1288/#1291 security remains release-blocking and separate from research expansion.
- [ ] Reject any unsolicited new model, factor, score, scheduled ingestion or automatic execution in infrastructure work.

**Milestone A (current):** trustworthy four-strategy read-only v1 + local reproduction. **Milestone B (next):** audited reusable data product catalogue and PIT semantics. **Milestone C (later):** two heterogeneous research questions using the same governed input/evidence path. This sequencing prevents “infrastructure work” from becoming another open-ended feature expansion.
