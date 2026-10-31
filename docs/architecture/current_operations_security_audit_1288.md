# Security Audit & Authoritative Storage Migration Plan (#1288 / Gate A4)

> **Authority**: Gate A4 (Security & Confidentiality)  
> **Status**: **REOPENED / P0 (Gate A4 remains FAIL)**  
> **Context**: Resolving current operating state leakage across public channels.  

---

## 1. Five-Surface Security Audit Matrix

The matrix records the initial disclosure baseline; §7–§9 track subsequent code
and transport changes. Historical observations are not current acceptance proof.
Gate A4 remains FAIL until the stated independent post-cutover checks pass.

| Surface | Scope / Target | Observed Finding | Leakage Status | Required Remediation |
| :--- | :--- | :--- | :--- | :--- |
| **1. 公开 Git**<br>(Current tracked files) | `data/research/formal_model_runs/`<br>`data/research/strategy_signal_ledgers/`<br>`data/research/model_decisions/` | `cn_27_v1_3` formal lineage (`blob 13489a0d...`) contains raw `operating_state.current_weights`. All 4 active strategy ledgers contain `latest.json` with target weights in public git. | **LEAKING (P0)** | 1. Stop embedding `operating_state` in formal bundle lineage.<br>2. Cease committing new signal ledgers into public git.<br>3. Sanitize current tracked files. |
| **2. 历史 Git**<br>(Historical commits) | Commit history on `main` up to `1d176034c` | Historical commits contain disclosed weights/allocations in commit trees. | **HISTORICAL EXPOSURE (Residual Risk)** | Per ADR-0004, git history cannot be made retrospectively secret without disruptive rewriting. Record as documented residual risk; stop all future publication. |
| **3. Pages**<br>(Static build output) | `qlib-dashboard/dist`<br>`public_historical_projection_v1` | `sync-formal-model-runs.mjs` generates sanitized projection stripping `operating_state`. Verified by `test_public_source_boundary.py` (32 tests pass). | **PROTECTED AT BUILD LEVEL** | Maintain regression barrier; ensure no raw bundles are copied into `dist/`. |
| **4. Actions Artifacts**<br>(CI workflow outputs) | Workflow artifacts in GitHub Actions (`formal-strategy-*`, `formal-backtest-refresh-*`) | Unsanitized intermediate strategy output directories (`strategy-result`) uploaded as public artifacts in GitHub Actions. | **LEAKING (P0)** | Update upload masks to sanitize intermediate receipts or restrict sensitive uploads to private runners/secrets. |
| **5. 当前数据写入路径**<br>(Write & commit pipelines) | `formal-backtest-refresh.yml`<br>`cn27-current-target.yml`<br>`byd-daily-signal-alert.yml`<br>`qqq-v4-3-signal-alert.yml`<br>`ranker-10d-current-target.yml` | Workflows execute `git add` and commit real-time target weights directly into `main`. | **ACTIVE LEAKING PATH (P0)** | **Stop the Bleed**: Disable git commit of runtime signal ledgers to public repo. Direct writes exclusively to protected store (Supabase RLS). |

---

## 2. Immediate Action: Stop the Bleed (停止新增当前策略数据进入公开仓库)

1. **Decouple `operating_state` from Formal Lineage**:
   - **Current builder fixed; published-data cleanup remains open.** `scripts/refresh_cn_27_v1_3_formal.py` already removes embedded runtime state and declares `runtime_state_embedded=false`. This source fix does not sanitize previously published lineage or artifacts.
   - Formal model evidence represents immutable *backtest history*, not live execution instructions.
   - Replace embedded operating state with:
     ```python
     candidate["operational_monitoring"] = {
         "status": "separate_runtime_signal_ledger",
         "runtime_state_embedded": False,
     }
     ```
2. **Cease Git Commits of Runtime Signal Ledgers**:
   - Remove `git add data/research/strategy_signal_ledgers` steps from automated daily workflows.
   - Live targets and decision signals must not be pushed to the public GitHub repository.

---

## 3. Reuse Existing Protected Authorities (No Duplicate State System)

Per ADR-0004 and Owner directive:
1. **Reuse Existing Authority Planes**:
   - Do **NOT** create new Supabase tables, parallel registries, or secondary state systems.
   - Reuse existing **Strategy Operations**, **Strategy Decision Ledgers** (`data/research/strategy_signal_ledgers`), **private archive**, and **authenticated RLS policies**.
   - Retain existing Strategy Decision Ledger append-only formats and authority; change only their storage/delivery boundary (isolated in private archive / authenticated runtime access), not their definitions, schemas, or model identities.
2. **Public Historical Projection Remains Read-Only**:
   - Public Pages consumers read only sanitized, sealed backtests (`public_historical_projection_v1`).
   - Entitled workstation sessions fetch authorized live targets directly through existing authenticated RLS APIs.

---

## 4. Rigorous Gate A4 Verification Standard (Four Independent Negative Proofs)

Gate A4 shall remain **FAIL** until all four surfaces have independent negative proof:
- [ ] **1. Public Git Negative Proof**: No git-tracked file in the repository contains plain-text `current_weights` or `target_weights` for active strategies.
- [ ] **2. Pages Negative Proof**: Anonymous traversal of public static bundles finds zero `operating_state` or runtime weights (enforced by `test_public_formal_runs_have_zero_operational_leakage`).
- [ ] **3. Actions Artifacts Negative Proof**: Daily CI workflows sanitize intermediate strategy output artifacts, preventing public zip artifact inspection.
- [ ] **4. Write Pipelines Negative Proof**: Daily automation workflows no longer commit live strategy decisions to public `origin/main`.

## 5. G0 transport checkpoint evidence (2026-10-30; not A4 closure)

Implementation `0234de8f47739a6fab007d4a2560f550a765b701` adds the existing-ledger checkpoint/restore CLI. A real checkpoint of all four active model subtrees (263 files, 483509 ZIP bytes) was retained in the **existing private archive** `liuh886/alpha-engine-data-archive`, then read back at exact private commit `d561366885bf02fab17dc29f464809a52016605a`. Archive SHA-256: `455a2889f170513a56400371385adee59f20a11a6e834b887818f6c8f86a777a`; registry SHA-256: `636b76803029fff5358c40ecb7f1572d9c4868399a606a0440f1d36f402a654c`.

Private member: `archives/strategy-signal-checkpoints/2026-10-30/0234de8f47739a6fab007d4a2560f550a765b701/455a2889f170513a56400371385adee59f20a11a6e834b887818f6c8f86a777a.zip`.

- Authenticated exact-commit readback matched SHA/size; fresh restore matched every original active-subtree file byte and all four canonical latest-reader results, including delivery state. No strategy refresh or message delivery was invoked.
- Anonymous GitHub Contents and raw-content requests both returned **404**. This proves this private object boundary only; it is not a public Git/Pages/artifact/writer negative proof.
- Source latest signal/data dates (both equal per model): BYD 2026-10-29, CN27 2026-10-26, QQQ 2026-10-28, US x1.3 2026-10-23. This checkpoint does not claim newer observations.
- Four nonactive directories were explicitly excluded, unmodified: BYD v1.2, CN x1.1/x1.2, US x1.1. Their historical preservation and any eventual public-tree removal remain separate work.
- Bootstrap used the authenticated GitHub Contents API to the existing archive; production retention already has its SSH path. No new storage authority, credentials or workflow was created. Ongoing concurrent writes, restore integration and retention are **not** provided by this one-time bootstrap.

**Open integration blockers:** four producer restore/write flows, formal-refresh planning, outbox delivery-receipt persistence and dispatch/deduplication, private-content identity in Operations cache/publication, raw Actions artifact removal, current Git cleanup and entitled/denied/revoked runtime evidence. Public Issue bodies are an additional disclosure surface beyond the matrix; the renderer correction below does not remove earlier disclosures. Do not remove existing public ledger writes until protected continuity is proven. **G0 is incomplete and A4 remains FAIL.**

## 6. Public delivery Issue renderer correction (2026-10-30)

The outbox previously copied the complete strategy message into both the public GitHub Issue and private Telegram text, including a free-text signal title. `scripts/run_signal_delivery_outbox.py` now constructs the Issue title/body only from a fixed receipt template, validated registry model ID, date and the unchanged decision marker. No signal title, action, reason, execution time, position, weight or arbitrary signal field is copied into the public message. A receipt records a delivery **attempt**, not successful Telegram delivery. Model/date/fingerprint and the existence of an attempt remain public metadata; this change does not promise to hide them.

The detailed Telegram text, existing old-Issue marker lookup and canonical delivery state machine are preserved. Unexpected marker formats fail closed before either transport, without echoing their contents. Current QQQ/BYD fingerprints are 20 lowercase hex characters; US/CN fingerprints are 64. Tests use actual canonical decision/receipt files with mocked transports, including sent deduplication, ambiguous pre-existing Issues, rejected API retry, ambiguous-network non-retry and missing Telegram configuration. Both current and historical records remain unchanged.

The same outbox workflow now uploads only `artifacts/signal-delivery-outbox/result.json` (metadata receipt), rather than its entire output directory, which also contains a protected Strategy Operations projection. The protected local projection is still built for the existing operating path. Other producer/Operations/formal workflow uploads and older artifacts remain separate open blockers; this restricted mask is not proof that all Actions artifacts are safe.

No production notification was triggered for verification. This is code/fixture evidence for subsequent Issue rendering, not a live delivery acceptance receipt, historical Issue cleanup, private-ledger cutover or A4 closure. Scheduled Issue paths pick up the change from main; previously running revisions and already public messages remain residual exposure.

## 7. Private integration and real transport evidence (#1326)

The #1322 owner comment of 2026-10-30 requires all consumers to use the same
protected canonical state before public-write removal. #1326 connects four
producers, Formal prepare/plan/strategy/publish, Operations and Outbox through
the existing archive's `archives/strategy-signal-ledgers/latest.zip`. Details,
CAS/conflict semantics, durable pre-send fences and recovery are in the
[runbook](../operations/private_signal_ledger.md).

- Bootstrap public source: `96c70b4142a100820816d639cad925b9a54f1754`, including
  the new QQQ 2026-10-29 decision and actual delivery receipt. Private seed commit:
  `2be909d6b46f88221d0cf76fe3fd18769c44157a`. All 265 active files were preserved
  byte-for-byte and all four canonical readers matched. An obsolete public
  source was rejected before seeding; source equality was rechecked afterwards.
- Archive: 486726 bytes, SHA-256
  `da57d9ddef99a7e2e4afdbc6e178b424c4c3980f13132a963f4b050e9805203a`.
  Registry SHA-256 remains
  `636b76803029fff5358c40ecb7f1572d9c4868399a606a0440f1d36f402a654c`.
  Active file inventory SHA-256:
  `392817bb00e3b2c2a033285054e690d6c034b53bd83c9757a7ed54d86e1324d7`.
  Anonymous archive Contents/raw requests both returned 404.
- Real SSH [run 40996617113](https://github.com/liuh886/alpha_engine/actions/runs/40996617113),
  code head `0bfe7d9b6d0db99145a52bb230542553f7eac01b`, succeeded. Its metadata
  receipt reports the same archive SHA/size and all four models, `changed=false`
  and `write_access_verified=true`. Private main had advanced to
  `e68a4d9e80269577233aadd248372b0689c5606e` through unrelated retention; the
  canonical checkpoint content remained identical. The run verified restore,
  semantic closure and dry-run receive-pack authorization without changing
  protected state. Drain, public mirror, Operations materialization/publication
  and dispatch were all skipped; Telegram secrets were not exposed to the probe.

This is real transport evidence, not a newly generated four-strategy signal or
actual delivery acceptance. The four normal producer executions, Operations
publication, ambiguous-outcome recovery acceptance and subsequent removal of
public mirrors/raw uploads still require their own receipts. Code rollback must
not silently return an advanced private authority to public-only writers.
**G0 incomplete, A4 FAIL, full product NO-GO.**

## 8. Stop active public mirrors, producer logs and raw runtime uploads

After #1327, real Formal run `40999354397` succeeded through prepare, both
providers, plan and publish; strategy recomputation was correctly unnecessary.
QQQ `40999790973` and BYD `40999790914` then succeeded on private paths, joining
US `40998276868`, CN `40998276839`, Outbox `40998387772` / `40998395769` and
Operations `40998276856`. The outbox receipts retain the four original terminal
delivery identities; these observations do not invent a new signal/delivery.

This follow-up stops the four producer Git mirrors and the Outbox receipt mirror.
Dispatch follows confirmed private persistence, with `any_changed` accumulated
across writes. QQQ/US no longer need public contents-write permission; BYD/CN/
Outbox retain it for the existing repository dispatch operations. The four
active public ledger subtrees are removed and fresh hydrated paths are ignored.
All 267 removed files were checked as retained by private commit
`b798c41e593b58474a66bcb83f696d44286a46ce`, archive SHA-256
`d6b389fba81b1b4832e003d2ae5fbbedfa1dc59ddd5b5fa0dd45b0001d7f1616`, 489915
bytes. Git history and nonactive sealed model subtrees remain intact.

The producer CLI handlers previously printed full signal objects. They now emit
only a validated six-field write receipt; raw private JSON and Telegram payloads
remain unchanged. Unused free-text title GitHub outputs are removed. Producer
artifacts contain only the last verified private transport receipt; a retained
base receipt after job failure is not proof of a new publication. Operations
uploads only its publication receipt, and review packets upload only their
existing private archive binding. No raw current snapshot is uploaded there.

Future native MTM lineage uses `ranker_mtm_projection_reference_v1`, whitelisted
identity fields and `private_input_sha256`; it no longer copies the entire
private MTM object or its raw target into public lineage. Frozen economic
sections and existing sealed files are not rewritten. Older native lineage and
historical portfolio target traces remain separately inventoried; deleting
every historical weight key is not a legitimate way to preserve sealed evidence.

**Still open:** Formal strategy-result cross-job raw artifact transfer, older
published native MTM/Actions/Git disclosure, independent post-cutover Git/Pages/
artifact/writer negatives and entitled/denied/revoked runtime reads. Local
allowlist/canary tests and source-file removal do not replace those proofs.
**A4 remains FAIL; this is not full operating or product release acceptance.**

## 9. Real Formal closure and accountless observations (2026-10-31)

#1329, #1330 and #1331 are merged. Normal Formal run
[41083709573](https://github.com/liuh886/alpha_engine/actions/runs/41083709573)
passed both real private strategy retentions, exact restoration, atomic fan-in,
candidate #1332 merge and exact Pages verification. Its two strategy artifacts
contain only archive bindings; its 16 final observation JSON members contain no
`current_weights`, `target_weights` or `operating_state` keys. This closes the
new cross-job raw-artifact path, not older disclosed history.

The [accountless receipt](../evidence/product_v1/accountless_access_observation_2026-10-31.json)
records 16 anonymous Raw/Contents active-latest probes returning 404 at current
main and its exact SHA. Live Pages has four protected static runtime shells,
zero allocations and zero factor evidence. The private ledger Raw URL returns
404; its Contents request returned 403 and is not certified as a private-specific
denial. Public formal portfolio history remains distinct: US x1.3 has 71
`target_weights` keys in its retained historical portfolio section. A generic
key scan is therefore not a whole-site privacy PASS.

A fresh browser with no session read five runtime snapshots. All five have an
explicit live `public` strategy policy, including QQQ; this observation matches
current policy and does not prove a protected-row RLS failure. It also means
there is no currently non-public strategy row for anonymous-denial acceptance.
The retired `cn_x1_2` snapshot remains readable under the legacy public `cn_x`
policy; it is not part of the maintained four-strategy Console.

Next actions:

- Review and retire the legacy `cn_x` current runtime row/policy through the
  existing owner-governed lifecycle; preserve sealed historical evidence.
- Obtain an owner-approved protected test resource and dedicated sessions for
  entitled, denied, expired and revoked reads. Do not silently change production
  tiers or use an owner/service-role read as anonymous evidence.
- Complete older Git/Actions/native-lineage disclosure disposition separately.

The operator confirmed no test accounts/sessions are available. Real-session
tests and protected-row anonymous rejection remain **NOT_TESTED**; no access
policy, entitlement or production row was changed. **A4 remains FAIL; full
product acceptance remains NO-GO.**
