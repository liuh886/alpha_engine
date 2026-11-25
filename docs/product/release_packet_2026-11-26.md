# Direction A v1 — Owner release-acceptance packet

- **Repository:** `liuh886/alpha_engine`
- **Packet date:** 2026-11-26
- **Evidence base:** `main` / `1b073bcb2e06101a73795dfcaac9c15ba161bab4`
- **Live Pages deployment:** `6d8f08dbeb6722dd49b74974c706d5ab372f5bcc` (deploy run `45616159405`)
- **Boundary:** `research_only=true`, `trade_ready=false`
- **Document status:** documentation only. This packet is **not** a release authorization, **not** a GO, and **not** a substitute for the Owner A7 decision. It changes no code, data, evidence, permission or workflow.

**Current recommendation: NO-GO.** The technical baseline is green, but the release gates that require real elapsed sessions, real entitled and denied identities, a production rollback rehearsal and the Owner signature are still open. Do not describe this packet as A1/A4/A6/A7 acceptance.

---

## 0. Gate summary (current)

Status vocabulary: `PASS | FAIL | BLOCKED | NOT_TESTED`. A sub-result may be `PASS` or `verified` while the gate itself stays `BLOCKED` or `FAIL`.

| Gate | Status | One-line basis | Primary evidence |
| --- | --- | --- | --- |
| **A0** Identity / authority | **PASS** | Four active registry identities equal four accepted formal catalog records; doctor verifies manifests and sections. | `configs/strategies/registry.json`; `data/research/formal_model_runs/catalog.json`; [W4 review](../evidence/product_v1/w4_release_review_2026-10-25.json) |
| **A1** Daily operating reliability | **BLOCKED** | Owner-disclosed 2026-11-16: US 1/20 and CN 1/20 qualified, 20/21 observed. 20 qualified sessions per market are required. | [A1 runbook](a1_operating_review_runbook.md); [A1 reconciliation](../evidence/product_v1/a1_operating_reconciliation_2026-11-02.md); §13 of [execution plan](next_stage_execution_plan.md) |
| **A2** Data integrity | **BLOCKED** (Ops PASS / training SCOPED_BLOCKED) | Four-strategy operational dependencies reconcile; six profiles ready and two training profiles remain blocked by name. | `data/research/model_data_bundle_v1/model-data-readiness.json`; §13.2 / §13.9 of [execution plan](next_stage_execution_plan.md) |
| **A3** User journeys | **BLOCKED** (baseline PASS / restricted NOT_TESTED) | Eight real anonymous journeys (four strategies × desktop/mobile) passed; restricted/denied/expired/revoked journeys not tested. | [W2 UAT/privacy 2026-11-16](../evidence/product_v1/w2_uat_privacy_2026-11-16.json); scorecard [#1287/#1350 addendum](product_completion_scorecard_2026-10-25.md) |
| **A4** Access / privacy | **FAIL** | Anonymous/static boundary verified; real Owner/Pro/denied/expired/revoked sessions and historical-disclosure disposition are not closed. | [W2 UAT/privacy 2026-11-16](../evidence/product_v1/w2_uat_privacy_2026-11-16.json); [A4 permission resolution](../evidence/product_v1/a4_permission_resolution_2026-11-02.md); [accountless observation](../evidence/product_v1/accountless_access_observation_2026-10-31.json) |
| **A5** Local research | **PASS** | Owner accepted the bounded CN_27 and QQQ exact replays on 2026-11-16. | [A5 receipt](../evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json); Issue [#1282](https://github.com/liuh886/alpha_engine/issues/1282) (closed) |
| **A6** Release / recovery | **BLOCKED** | Runbook delivered; rollback rehearsal `NOT_EXECUTED`; no frozen Direction A release candidate; production recovery not Owner-exercised. | [Owner release runbook 2026-11-16](owner_release_runbook_2026-11-16.md); [A6 rehearsal receipt](../evidence/product_v1/a6_release_recovery_rehearsal_2026-11-01.json) |
| **A7** Owner decision | **NOT_TESTED** | Owner has not signed GO/NO-GO; the recorded recommendation is NO-GO and `owner_decision` is `null`. | [W4 review](../evidence/product_v1/w4_release_review_2026-10-25.json); §9.6 / §10.3 of [Owner release runbook](owner_release_runbook_2026-11-16.md) |

**No gate above is inferred from CI, a merge, a document update or a Pages deployment.** Those facts are recorded separately in §1.

---

## 1. What is already green (technical facts, not release gates)

These facts are verified as of 2026-11-26. They are necessary but not sufficient for a v1 GO.

| Fact | Verified value | Evidence |
| --- | --- | --- |
| Full health gate | Run `45616820407`, head `1b073bcb2e`, conclusion `success`; artifacts parsed: **4,693 tests / 0 failures / 0 errors / 8 skipped**; jobs `backend`, `repository-health (0..3)`, `repository-health-report` all success. | GitHub Actions run `45616820407`; JUnit artifacts `repository-health-shard-0..3-45616820407` |
| Merged fixes on `main` | #1486 `e5665c5401` (CN ETF volume lot basis); #1487 `6d8f08dbeb` (health-gate tests track governed evidence); #1488 `1b073bcb2e` (sealed historical RDI decoder identity). | `gh pr view 1486/1487/1488` |
| Weekly health issue | #1483 (`weekly repository health gate is failing`) closed 2026-11-25T12:50:57Z. | `gh issue view 1483` |
| Published Pages | Live `deployment.json` `commit_sha` = `6d8f08dbeb6722dd49b74974c706d5ab372f5bcc`; deploy run `45616159405` conclusion `success`, event `workflow_dispatch`. | `https://liuh886.github.io/alpha_engine/deployment.json`; run `45616159405` |
| Formal catalog | Exactly four accepted records; US cutoffs **2026-11-19** (`qqqi_qqq_tqqq_v4_3`, `us_x1_3`), CN cutoffs **2026-11-24** (`cn_27_v1_3`, `byd_v1_3_recovery_event_low_vol_confirmation_v1`). | `data/research/formal_model_runs/catalog.json` (`generated_at` 2026-11-24T19:38:09Z) |
| Registry identity | Exactly four active strategies: `qqq_rotation`, `us_x`, `cn_27`, `byd`; `research_only=true`, `trade_ready=false`. | `configs/strategies/registry.json` |
| Data readiness file | 8 components: **6 ready / 2 partial / 0 blocked**; 6 ready training profiles; 2 blocked profiles named below. `evidence_cutoff` 2026-11-24. | `data/research/model_data_bundle_v1/model-data-readiness.json` |
| Local research replay | CN_27 and QQQ v4.3 `exact_replay`, three repetitions each, exit 0; CN within `1e-6`, QQQ at `1e-12`; Owner `ACCEPTED` 2026-11-16. | [A5 receipt](../evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json) |
| Anonymous public journeys | Eight real anonymous journeys (four strategies × desktop/mobile), four stages each, all PASS; 64 screenshots; zero page/console errors and zero failed requests. | [W2 UAT/privacy 2026-11-16](../evidence/product_v1/w2_uat_privacy_2026-11-16.json) |

**Do not convert this section into a GO.** The health run, merges, docs and Pages deploy do not certify A1, A4, A6 or A7.

---

## 2. Gate-by-gate acceptance record

### A0 — Identity and authority: **PASS**

- `configs/strategies/registry.json` lists exactly four `accepted_formal_baseline` strategies: `qqqi_qqq_tqqq_v4_3`, `us_x1_3`, `cn_27_v1_3`, `byd_v1_3_recovery_event_low_vol_confirmation_v1`.
- `data/research/formal_model_runs/catalog.json` contains exactly those four `model_version_id` values, each with an accepted-formal `bundle_id`, manifest path and manifest SHA-256.
- The W4 review recorded A0 `PASS`: “Exact four active identities equal accepted formal catalog; doctor verifies manifests/sections.”
- Current evidence cutoffs advanced (US 2026-11-19, CN 2026-11-24) without changing identity. Cutoff advance is not a new identity and does not authorize a fifth strategy.

**Claim boundary:** A0 PASS certifies identity parity only. It does not certify A1–A7.

### A1 — Daily operating reliability: **BLOCKED**

**Required:** 20 eligible completed exchange sessions per market (CN and US counted separately), each reviewed, with source/decision/publication/delivery evidence, blockers, manual recovery and the Owner-supplied manual-intervention count.

**Current disclosed counts (Owner disclosure dated 2026-11-16):**

| Market | Qualified sessions | Required | Observed sessions |
| --- | ---: | ---: | ---: |
| US | 1 | 20 | 20 / 21 |
| CN | 1 | 20 | 20 / 21 |

**Verification note (evidence gap):** no committed public receipt in this worktree contains the `20/21 observed` figure as of 2026-11-26. The last committed audits are:

- 2026-11-08 independent re-audit: US/CN **17 observed / 0 qualified** of 20 requested; `manual_interventions: null`; `on_time_daily_collection_claimed: false`; `collected_retroactively_today: true` — `docs/evidence/product_v1/launch_2026-11-08/a1-independent-reaudit.json`.
- 2026-11-12 acceptance `--through 2026-11-11`: US/CN **20/20 observed / 0 qualified**, window 2026-10-15–2026-11-11, `twenty_session_evidence_complete=false`, `missing_due_cycle_strategy_ids=[]` — §13.9 of `docs/product/next_stage_execution_plan.md`.
- 2026-11-12 four-strategy green packets `43240496998:2` and `43246160984:1`: `mechanically_ready=true`, `blockers=[]`, `qualification_status=awaiting_independent_review`, `manual_interventions=null`, `reviewed_by=null`.

Treat the 2026-11-16 counts as the Owner-disclosed current count, not as a new public acceptance receipt.

**On-time collection gap:**

- The 2026-11-08 archive re-audit covered 535 fixed captures: 525 with observation, 10 without; 72 attempts selected; 2 attempts blocked for insufficient capture time/evidence.
- The 2026-11-08 re-audit explicitly records retroactive collection and does **not** claim on-time daily collection.
- By 2026-11-12 the rolling window had 20/20 observed captures, but observed is not qualified: no independent reviewer declaration and no manual-intervention value existed.
- The A1 runbook records that the declaration store is empty and that an Agent cannot sign for the Owner.
- The on-time question therefore remains open: capture coverage is not proof that each due cycle was collected on time, and a retroactive capture cannot be relabeled as on-time.

**Exact commands to record declarations and rerun acceptance** (from `docs/product/a1_operating_review_runbook.md`):

```powershell
# 1. Record one Owner review declaration for one exact observation.
uv run --frozen python -m scripts.record_operating_review record `
  --observation-root artifacts/product-v1-1277/latest/source `
  --run-id <run_id> --run-attempt <run_attempt> `
  --draft artifacts/product-v1-1277/latest/review-draft.json `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json `
  --manual-interventions <owner_count> `
  --reviewed-by <owner_name> `
  --cadence-and-freshness-verified

# 2. Verify that every declaration and bound file still hashes exactly.
uv run --frozen python -m scripts.record_operating_review verify `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json

# 3. Re-run the authoritative acceptance count through the latest completed session.
uv run --frozen alpha ops acceptance `
  --input-root artifacts/product-v1-1277/latest `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json `
  --through <completed_session>
```

Rules:

- `--manual-interventions` is the Owner's real non-negative integer. There is no default; `0` is only a syntax example.
- The declaration store is append-only. Re-recording different content under the same `<run_id>:<run_attempt>` is refused.
- Acceptance re-verifies every declaration binding before counting a session.
- Do not add a scheduler, daemon, database or new workflow for A1.

**Owner actions for A1:**

1. Review the exact observation packets for each session, including `expected_cutoffs`/`actual_cutoffs`, collection blockers, final Actions metadata, sealed decision/delivery evidence and the operating inputs.
2. Supply the real manual-intervention count and reviewer name; record one declaration per reviewed observation.
3. Re-run `alpha ops acceptance` through the latest completed session.
4. Repeat until 20 eligible sessions per market are collected **on time** and valid declarations exist for each reviewed observation.
5. Keep missing, failed and retained sessions explicit. Do not fabricate or backfill observations.

### A2 — Data integrity: **BLOCKED** (Ops PASS / training SCOPED_BLOCKED)

**Ops PASS:** the four active strategy operating dependencies reconcile. `scripts/doctor.py` verifies the formal catalog, each manifest and available sections, and reports per-strategy provider/formal/factor/decision cutoffs. The 2026-11-12 review records the four-strategy operational data plane as reconciled.

**Training SCOPED_BLOCKED:** the current readiness file (`built_at` 2026-11-24T19:49:55Z, `evidence_cutoff` 2026-11-24) reports:

- components: **6 ready / 2 partial / 0 blocked**;
- ready training profiles: `cn_selected_alpha158_v1`, `cn_selected_price_only_v1`, `cn_selected_price_plus_fundamentals_v1`, `qqqi_qqq_tqqq_rotation_v1`, `us_selected_price_only_v1`, `us_selected_price_plus_fundamentals_v1`;
- blocked training profiles: **`us_selected_alpha158_v1`**, **`us_small_pool_price_plus_fundamentals_v1`**.

**Interpretation:** the two blocked profiles are unrelated to the active four-strategy operating read. They block model-ready training claims, not the validity of retained formal strategy history. Do not silently substitute a security, forward-fill unavailable statements, mix raw and adjusted prices, or relabel a blocked profile as ready.

**Owner action:** either accept the two training profiles as explicitly scoped out of v1, or fund the missing US entitlement/source work separately. Do not make active-strategy acceptance depend on an unrelated training profile.

### A3 — User journeys: **BLOCKED** (baseline PASS / restricted NOT_TESTED)

**Baseline PASS:** the 2026-11-16 W2 receipt records eight real anonymous journeys — `qqq_rotation`, `us_x`, `cn_27`, `byd` × desktop (1600×1000) and mobile (390×844) — each completing Overview → exact Strategy Detail → linked Instrument → Operating Status with zero page errors, zero console errors, zero failed requests and 0 px horizontal overflow. 64 screenshots were captured with SHA-256.

Earlier baseline (#1287 / #1350) recorded eight four-strategy desktop/mobile journeys and 375 px mobile coverage. The W2 receipt is the current live-origin evidence.

**NOT_TESTED:** restricted, denied, expired and revoked account journeys. The receipt’s own scenario matrix marks `real_expired_or_revoked_account`, `rls_unauthorized_expired_revoked` and `owner_authenticated_journey` as `NOT_TESTED` because no isolated credentials were supplied and none were created.

**Owner action:** supply isolated identities (see A4) and complete the restricted/denied/expired/revoked journey matrix. Fixtures and green CI do not substitute.

### A4 — Access and privacy: **FAIL**

**Anonymous/static boundary — verified, not a gate PASS:**

- 2026-11-12 production anonymous GET of `strategy_operation_snapshots` returned **HTTP 401, 0 rows, no sensitive keys**; `product_access_policies` returned 200; the static shell had 4 rows with no sensitive keys; signal-ledger raw/Pages probes returned 404; the private archive returned 403/404 (§13.9 of the execution plan).
- 2026-11-16 W2 privacy receipt: `verify_pages_release` `status=verified`, 4 formal models, 36 formal sections, `public_operations_verified=true`; `protected_current_holdings_or_targets_exposed=false`; static operations probe shows `allocations=[]`, `as_of=null`, `read_state=protected`, no forbidden operational/lineage keys.
- Historical 2026-11-08 baseline (`a4-anonymous.json`) recorded 5 anonymous allocation rows before the production fix. That failure is retained as pre-fix evidence and is not erased.

**Why A4 remains FAIL:** real entitled, denied, expired and revoked sessions have never been exercised; the historical Git disclosure is irreversible and its disposition is an Owner decision; client cache isolation and Edge OIDC end-to-end are not verified.

**Exact test matrix — isolated identities required.** Owner must provide dedicated non-production identities. Do not mutate production policies to create a pass sample. Do not substitute SQL role fixtures or unit tests for real HTTP/session evidence.

| Identity | Request | Expected HTTP | Expected rows | Expected sensitive keys | Current status |
| --- | --- | ---: | ---: | --- | --- |
| Anonymous | `GET /rest/v1/strategy_operation_snapshots` | **401** | **0** | none | Observed 2026-11-12: 401 / 0 |
| Authenticated, no entitlement (denied) | same, valid JWT without Pro/Owner entitlement | **200** (RLS-filtered; record if 403) | **0** | none | NOT_TESTED real HTTP; local SQL fixture 0 |
| Pro, valid | same, valid Pro JWT | **200** | **4** active strategies | only allowed protected fields for the active four | NOT_TESTED real HTTP; local SQL fixture 4 |
| Pro, expired | same, expired entitlement | **200** (RLS-filtered; record if 403) | **0** | none | NOT_TESTED |
| Pro, revoked | same, revoked entitlement | **200** (RLS-filtered; record if 403) | **0** | none | NOT_TESTED |
| Owner | same, Owner JWT | **200** | **4** active strategies | allowed protected fields | NOT_TESTED real HTTP; local SQL fixture 4 |
| Anonymous | `GET /rest/v1/product_access_policies` | **200** | policy rows | no holdings/targets | Observed 2026-11-12: 200 |
| Anonymous | static `data/strategy-operations/snapshots.json` | **200** | **4** | `allocations=[]`, `as_of=null`, `read_state=protected` | Verified 2026-11-16 |
| Anonymous | raw Git / Pages signal-ledger path | **404** | **0** | none | Observed 404 |
| Anonymous | private `alpha-engine-data-archive` | **403/404** | **0** | none | Observed 403/404 |

Request template (replace placeholders; never paste a real JWT or key into the repository):

```powershell
$headers = @{
  apikey        = $env:SUPABASE_ANON_KEY
  Authorization = "Bearer $env:TEST_JWT"
}
Invoke-WebRequest `
  "https://blgwlycfcwvsupmqyqwn.supabase.co/rest/v1/strategy_operation_snapshots?select=*" `
  -Headers $headers |
  Select-Object StatusCode, @{n='Rows';e={ ($_.Content | ConvertFrom-Json).Count }}
```

Record for every identity: exact HTTP status, returned row count, whether any forbidden operational/lineage key appears, the route type, the deployed Pages SHA / project ref, timestamp and JWT class (never the token).

**Owner actions for A4:**

1. Provide isolated Owner, Pro, denied, expired and revoked identities (or explicitly accept the residual risk as NOT_TESTED).
2. Run the matrix above and retain the receipts outside the repository.
3. Decide the disposition of the historical Git disclosure; a Pages-only repair cannot make public history confidential.
4. Do not delete retained rows or change live tiers to manufacture a pass.

### A5 — Local research: **PASS**

Owner accepted the bounded replay on 2026-11-16. The #1282 receipt records:

- `owner_A5_acceptance: "ACCEPTED"`, accepted 2026-11-16;
- CN_27 v1.3 `exact_replay`, three repetitions, exit 0, within `1e-6`;
- QQQ v4.3 `exact_replay`, three repetitions, exit 0, at `1e-12`, after PR #1446 re-sealed the accepted bundle so positions and report labels agree;
- no model, pool, benchmark, cost or lockfile change; `promotion_authorized=false`.

**Caveats that remain in force:**

- CN_27 reproduces the frozen trace boundary 2026-09-04; appended economics are not part of the audit.
- The US replay depends on live Yahoo/yfinance availability; provider-vintage reproducibility is not claimed.
- No prospective or out-of-sample validation, new model, training, promotion or trade readiness is implied.

**Claim boundary:** A5 PASS is the bounded replay acceptance only. It does not advance A6 or A7.

### A6 — Release and recovery: **BLOCKED**

**Delivered:** the Owner release and rollback runbook (`docs/product/owner_release_runbook_2026-11-16.md`) documents clean-checkout setup, provider/secret handling, daily read, manual replay, formal publication review, failure diagnosis, restore/rollback, rehearsal plan and RC freeze.

**Verified rehearsal artifacts (not production acceptance):** `a6_release_recovery_rehearsal_2026-11-01.json` records 46 release/checkpoint tests passing, tamper rejection, static-console recovery protocol and private-ledger CAS recovery protocol. The A6 gate status remains `BLOCKED` because live production rollback and Owner execution are not performed.

**Not executed:**

- **Rollback rehearsal: `NOT_EXECUTED`.** No dispatch, deployment, rollback or live verification was run for §9 of the runbook.
- **Release candidate freeze: `PENDING`.** No Direction A SHA, cutoff, candidate id or deployment target is frozen. `release_gate.py` requires an explicit candidate; the tracked `artifacts/release_candidate/20260620/release_manifest.json` (`rc_20260620`) is not identified as the Direction A candidate.
- **Production recovery:** Owner-exercised private-ledger restore and Pages rollback are not done.

**RC freeze checklist** — every field must come from an actual run; unknown stays `PENDING`:

| Field | Value / source |
| --- | --- |
| Release candidate id | `PENDING` — Owner-named |
| Source `main` SHA | `PENDING` — `gh api repos/liuh886/alpha_engine/git/ref/heads/main --jq .object.sha` |
| Deployed Pages SHA | `PENDING` — `deployment.json.commit_sha` |
| US cutoff | `PENDING` — `data/research/formal_model_runs/freshness.json` `markets.us` |
| CN cutoff | `PENDING` — same, `markets.cn` |
| Formal catalog SHA-256 | `PENDING` — `Get-FileHash -Algorithm SHA256 data/research/formal_model_runs/catalog.json` |
| Formal bundle ids (4) | `PENDING` — `catalog.json` records |
| `uv.lock` SHA-256 | `PENDING` |
| `package-lock.json` SHA-256 | `PENDING` |
| Python / uv / Node versions | `PENDING` — record exact installed versions; CI pins uv 0.12.7 |
| Private archive commit | `PENDING` — private-ledger restore receipt |
| Private checkpoint SHA-256 / bytes | `PENDING` — checkpoint receipt |
| Quality gate verdict | `PENDING` — `uv run --frozen python scripts/release_gate.py --candidate <explicit-id> --run-quality-gates --evidence-dir artifacts/release_gates` |
| Deployment acceptance | `PENDING` — deploy run id, `deployment.json`, verifier receipt, Playwright artifact |
| Privacy/static check | `PENDING` — see command set below |
| Post-release evidence | `PENDING` — refresh `operating-observation.json`, operations receipt |
| Rollback target SHA | `PENDING` — Owner-reviewed, post-privacy-fix, ancestor of `main` |
| Owner A6/A7 decision | `PENDING` — §6 template |

Privacy/static check set:

```powershell
uv run --frozen python scripts/check_legacy_web_boundary.py
uv run --frozen python -m pytest tests/test_public_source_boundary.py -q
cd qlib-dashboard
npm run check:formal-evidence
npm run check:account
npm run build
```

**Production rollback steps** (Owner-authorized; do not mutate sealed evidence):

1. Record current release: `deployment.json.commit_sha`, deploy run id and verifier receipt.
2. Record `catalog.json` SHA-256.
3. Name `<TARGET_SHA>`: an ancestor of `origin/main`, post-privacy-fix, previously verified.
4. Confirm ancestry and privacy fix:
   `git merge-base --is-ancestor <TARGET_SHA> origin/main`;
   `git merge-base --is-ancestor <PRIVACY_FIX_SHA> <TARGET_SHA>`.
5. Dispatch: `gh workflow run deploy-pages.yml --ref main -f target_sha=<TARGET_SHA>`.
6. Watch: `gh run watch <RUN_ID> --exit-status`.
7. Verify: `uv run --frozen python -m scripts.verify_pages_release --base-url https://liuh886.github.io/alpha_engine/ --expected-commit <TARGET_SHA>`.
8. Confirm `deployment.json.commit_sha == <TARGET_SHA>` and `catalog.json` SHA-256 unchanged; `git status` clean.
9. Restore the known-good current release SHA with the same dispatch pattern and re-verify.
10. Retain receipts outside the repository; state explicitly that A6/A7 remain pending.

**Rollback must not:** rewrite/re-seal/delete formal evidence; re-point a `model_version_id`; force-push `main`; restore a pre-privacy-fix artifact merely because it verifies; delete failed records.

**Observer caveat:** the `pages-release-receipt` observer was fixed on 2026-11-16 to resolve the deployed SHA from `deployment.json` rather than `workflow_run.head_sha`, but the fix has text-test coverage only and has not been exercised by a real rollback. Until a rehearsal is run, treat the Owner-run verifier receipt as authoritative.

### A7 — Owner decision: **NOT_TESTED** (current recommendation NO-GO)

- The W4 review records `recommendation: "NO-GO"`, `owner_decision: null`, `approved_release_candidate: null`.
- No dated Owner GO/NO-GO exists.
- CI, merges, this packet and green Pages deployments do not sign for the Owner.
- The complete residual-risk list is §7.

---

## 3. Owner next actions (ordered checklist)

Each row is executable. Do not skip a prerequisite; a later row cannot make an earlier row true.

| # | Action | Command / input | Expected receipt or evidence | Blocking condition |
| ---: | --- | --- | --- | --- |
| 1 | Confirm the current release baseline | Read `deployment.json` and `catalog.json`; record `commit_sha` and formal cutoffs | Deployment SHA `6d8f08db…` (or newer) and four catalog records at US 2026-11-19 / CN 2026-11-24 | Pages SHA is not the intended candidate, or identity differs |
| 2 | Review the A1 observation packets | Owner reviews each `<run_id>:<run_attempt>` packet, cutoffs, blockers, final Actions metadata, sealed decision/delivery evidence | Signed review notes / `review-draft.json` per observation | Missing packet, cutoffs mismatch, or manual-intervention value unknown |
| 3 | Record A1 declarations | `uv run --frozen python -m scripts.record_operating_review record … --manual-interventions <owner_count> --reviewed-by <owner_name> --cadence-and-freshness-verified` | Append-only `review-declarations.json` with observation SHA-256 and bound file hashes | Owner cannot supply a real intervention count or reviewer name |
| 4 | Verify A1 declarations | `uv run --frozen python -m scripts.record_operating_review verify --declarations …` | Exit 0; no drift/missing binding/invalid digest | Any hash drift, missing binding or research-boundary violation |
| 5 | Rerun A1 acceptance | `uv run --frozen alpha ops acceptance --input-root … --declarations … --through <completed_session>` | Acceptance report with US/CN qualified counts | Fewer than 20 qualified sessions per market, or missing due-cycle evidence |
| 6 | Repeat A1 until 20/20 per market | New real sessions only; no backfill | 20 qualified US + 20 qualified CN, on time | Elapsed real trading sessions are insufficient |
| 7 | Obtain isolated A4 identities | Dedicated Owner, Pro, denied, expired and revoked accounts/JWTs (non-production test identities) | Identity inventory without secret values | No isolated identity available; do not fabricate or mutate production |
| 8 | Run the A4 matrix | Execute the §2 A4 table; record HTTP status, row count, sensitive-key scan per identity | Per-identity receipt outside the repo | Any protected row leaks, any identity returns unexpected rows |
| 9 | Decide historical disclosure disposition | Owner records the decision for irreversible historical Git exposure | Dated Owner note; residual risk accepted or mitigated | No Owner decision |
| 10 | Name the A6 rollback target | `<TARGET_SHA>` ancestor of `main`, post-privacy-fix, previously verified | Signed target note + verifier receipt for the target | Target is not on `main`, pre-fix, or unverified |
| 11 | Execute A6 rollback rehearsal | Run the §2 A6 steps 1–10 | Two successful deploy runs, two verifier receipts, unchanged catalog hash, clean `git status` | Any evidence mutation, failed verifier, or concurrent refresh |
| 12 | Freeze the RC fields | Fill every `PENDING` row in the §2 A6 checklist from actual runs | Completed RC freeze table | Any field inferred from a nearby run |
| 13 | Run quality-only release gate | `uv run --frozen python scripts/release_gate.py --candidate <explicit-id> --run-quality-gates --evidence-dir artifacts/release_gates` | `artifacts/release_gates/release_gate_verdict.json` | No explicit candidate, or a quality command fails |
| 14 | Record the dated A7 decision | Use the §6 template | Signed GO/NO-GO with date, evidence links and residual-risk acknowledgement | A1/A4/A6 incomplete, or Owner not satisfied |

**Agent boundary:** an Agent may prepare evidence, run read-only checks and draft receipts. An Agent must not sign A1 declarations, supply a false intervention count, execute a production rollback without Owner authorization, or record the A7 decision.

---

## 4. Dated A7 GO/NO-GO decision template

Copy, fill, sign and retain outside the repository (or in the Owner's private acceptance record). Do not commit a filled decision without the Owner's explicit instruction.

```
Direction A v1 release decision

Decision date (UTC): 2026-11-26 (or later)   ______________________
Reviewer / Owner (name):                     ______________________
Evidence base (main SHA):                    ______________________
Deployed Pages SHA:                          ______________________
Release candidate id (if any):               ______________________

Gate results at decision time:
  A0 identity/authority:      [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A1 daily reliability:       [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A2 data integrity:          [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A3 user journeys:           [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A4 access/privacy:          [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A5 local research:          [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED
  A6 release/recovery:        [ ] PASS   [ ] FAIL   [ ] BLOCKED   [ ] NOT_TESTED

Residual risks acknowledged:
  [ ] A1 qualified sessions below 20 per market
  [ ] A4 real entitled/denied/expired/revoked sessions not all tested
  [ ] Historical Git disclosure disposition
  [ ] A6 production rollback rehearsal
  [ ] A2 scoped training-profile blockers
  [ ] Other: ______________________________________________

Decision:   [ ] GO   [ ] NO-GO   [ ] DEFERRED
Conditions (if any): ______________________________________
Evidence directory (outside repo): ________________________
Signature: _______________________________________________
```

---

## 5. Residual risk register

| # | Risk | Impact | Current mitigation | Owner action |
| ---: | --- | --- | --- | --- |
| 1 | A1 has 1 qualified session per market (disclosed 2026-11-16), not 20 | Release cannot claim continuous operating reliability | Fail-closed; counts disclosed; no fabricated sessions | Collect/review 20 eligible sessions per market on time |
| 2 | On-time collection not proven; 2026-11-08 audit was retroactive; declaration store empty | Observed captures may not represent on-time due-cycle delivery | A1 runbook requires per-observation declarations and manual-intervention values | Record declarations and verify |
| 3 | A4 real entitlement sessions never tested | Unauthorized protected-row access cannot be ruled out | Anonymous/static boundary verified; RLS local fixtures pass; fail-closed defaults | Provide isolated identities and run the matrix |
| 4 | Historical Git disclosure is irreversible | Public historical operating data cannot be made confidential by a Pages repair | Active public write/read paths cut; historical disclosure recorded as residual | Record disposition decision |
| 5 | A6 production rollback not rehearsed | Recovery path is documented but unproven in production | Static/private recovery tests and tamper rejection pass; observer fixed with text tests | Run the rehearsal |
| 6 | No frozen Direction A release candidate | A GO would not be reproducible | `release_gate.py` requires an explicit candidate and fails closed | Complete the RC freeze table |
| 7 | A2 two training profiles blocked (`us_selected_alpha158_v1`, `us_small_pool_price_plus_fundamentals_v1`) | Model-ready training claims cannot be made for those profiles | Scoped separately; active-strategy ops unaffected | Accept scope or fund the missing source/entitlement |
| 8 | CN_27 frozen trace ends 2026-09-04 while the catalog cutoff advanced to 2026-11-24 | Readers may misread appended evidence as part of the frozen trace | UI discloses stale/frozen boundary; A5 receipt states the caveat | Keep the caveat visible; do not relabel appended economics |
| 9 | QQQ replay depends on live Yahoo/yfinance availability | Provider-vintage reproducibility is not guaranteed | Locked interpreter/yfinance; provider caveat recorded | Do not claim provider-vintage reproducibility |
| 10 | Pages can lag `main` by design (`no_publication_impact`) | A deployment SHA may not equal `main` HEAD | `deployment.json` is the published truth; manual dispatch can force a SHA | Read the deployed SHA, not `main`, for release identity |

---

## 6. Do not claim

- **Do not claim A1 PASS.** One qualified session per market (as disclosed 2026-11-16) is not 20. A green health run, merged PRs or a current catalog cutoff do not create eligible sessions.
- **Do not claim A4 PASS.** Anonymous/static verification is not a real entitlement test. Historical Git disclosure remains. SQL role fixtures are not real HTTP/session evidence.
- **Do not claim A6 PASS.** A delivered runbook and passing recovery unit tests are not a production rollback rehearsal.
- **Do not claim A7 GO or any Owner decision.** The recorded recommendation is NO-GO and `owner_decision` is `null`. Only the Owner can sign.
- **Do not claim CI, merges, documentation or a Pages deployment substitute for A1/A4/A6/A7.** Run `45616820407`, PRs #1486–#1488, this packet and deployment `6d8f08db` are technical facts, not release acceptance.
- **Do not claim A5 proves alpha, prospective validity, out-of-sample performance or trade readiness.** It is a bounded exact replay of two accepted references.
- **Do not claim A2 Ops PASS proves full training-data readiness.** Two profiles remain explicitly blocked.
- **Do not claim a release candidate is frozen.** Every RC field in §2 A6 is `PENDING`.
- **Do not claim the anonymous UI is the security boundary.** React gating is a reading affordance; Supabase/RLS is the authority.
- **Do not claim a Pages rollback is safe merely because an old artifact verifies.** It must be post-privacy-fix and ancestor-qualified.

---

## 7. Evidence and verification index

### Repository evidence read for this packet

| Path | What it establishes |
| --- | --- |
| `AGENTS.md` | Current research-only scope, four-strategy product, A0–A7 tracking, lightweight governance |
| `docs/product/strategy_console.md` | Maintained routes and evidence path; no live execution |
| `docs/product/product_completion_scorecard_2026-10-25.md` | A0–A7 gate definitions and historical classifications |
| `docs/product/owner_release_runbook_2026-11-16.md` | Release/rollback procedure; §9 rehearsal `NOT_EXECUTED`; §10 RC `PENDING` |
| `docs/product/a1_operating_review_runbook.md` | Declaration mechanism; A1 `BLOCKED`; commands |
| `docs/product/next_stage_execution_plan.md` §13 | 2026-11-12 gate matrix, A1 acceptance counts, A4 anonymous 401/0, data readiness |
| `docs/evidence/product_v1/w4_release_review_2026-10-25.json` | `recommendation: NO-GO`, `owner_decision: null`, A0 PASS / A1–A6 blocked / A7 NOT_TESTED |
| `docs/evidence/product_v1/w2_uat_privacy_2026-11-16.json` | Eight anonymous journeys, 64 screenshots, static privacy verified, restricted/RLS NOT_TESTED |
| `docs/evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json` | A5 `ACCEPTED`, CN/QQQ `exact_replay`, caveats |
| `docs/evidence/product_v1/a1_operating_reconciliation_2026-11-02.md` | 20-session window reconciliation and historical failures |
| `docs/evidence/product_v1/launch_2026-11-08/a1-independent-reaudit.json` | 17 observed / 0 qualified, retroactive collection, manual interventions null |
| `docs/evidence/product_v1/launch_2026-11-08/a4-anonymous.json` | Pre-fix anonymous allocation exposure baseline |
| `docs/evidence/product_v1/launch_2026-11-08/rls-local-fixture.json` | Local SQL role fixture (not real sessions) |
| `docs/evidence/product_v1/a4_permission_resolution_2026-11-02.md` | A4 FAIL rationale; real sessions NOT_TESTED |
| `docs/evidence/product_v1/a6_release_recovery_rehearsal_2026-11-01.json` | 46 release/checkpoint tests; A6 remains BLOCKED |
| `docs/evidence/product_v1/accountless_access_observation_2026-10-31.json` | Accountless observation; protected/denied sessions unresolved |
| `docs/architecture/frontend_access_control.md` | Four tiers; Supabase/RLS is the security authority |
| `docs/architecture/current_operations_security_audit_1288.md` | Historical Git/Actions exposure audit |
| `docs/architecture/current_operations_publication_repair_1288.md` | Publication-boundary repair context |
| `configs/strategies/registry.json` | Exactly four active strategies |
| `data/research/formal_model_runs/catalog.json` | Four accepted records; US 2026-11-19, CN 2026-11-24 |
| `data/research/model_data_bundle_v1/model-data-readiness.json` | 6 ready / 2 partial / 0 blocked components; two blocked profiles |

### GitHub facts verified on 2026-11-26

| Reference | Verified state |
| --- | --- |
| Health run `45616820407` | `success`; head `1b073bcb2e`; 4,693 tests / 0 failures / 0 errors / 8 skipped; all jobs success |
| Pages deploy run `45616159405` | `success`; head `6d8f08db`; event `workflow_dispatch` |
| Issue #1483 | CLOSED 2026-11-25T12:50:57Z |
| PR #1486 | MERGED `e5665c5401` at 2026-11-25T12:00:15Z |
| PR #1487 | MERGED `6d8f08dbeb` at 2026-11-25T12:36:28Z |
| PR #1488 | MERGED `1b073bcb2e` at 2026-11-25T12:42:42Z |
| Issue #1277 (A1) | OPEN |
| Issue #1278 (A0) | CLOSED |
| Issue #1279 (A3/A4) | OPEN |
| Issue #1281 (A6) | OPEN |
| Issue #1282 (A5) | CLOSED |
| PR #1276 (A0–A7 proposal) | MERGED (architecture proposal only; not a release) |
| PR #1446 (QQQ reason-label correction) | MERGED |

### Verification limits

- The `20 / 21 observed` and `US 1 / CN 1 qualified` figures are the Owner-disclosed 2026-11-16 counts. No committed public receipt in this worktree contains them; the last committed audits are the 2026-11-08 (17/0) and 2026-11-12 (20/20 observed, 0 qualified) records cited above.
- The production Supabase project ref and endpoint are quoted from the 2026-11-08 receipt; confirm the current project before running A4 probes.
- No production rollback, entitlement mutation, data refresh or model run was performed for this packet.
- This packet did not re-run the full test suite; it parsed the artifacts of health run `45616820407`.

---

*Prepared 2026-11-26 against `main` `1b073bcb2e06101a73795dfcaac9c15ba161bab4`. Research only; not trade ready. The Owner alone decides A7.*
