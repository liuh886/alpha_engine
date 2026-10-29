# Security Audit & Authoritative Storage Migration Plan (#1288 / Gate A4)

> **Authority**: Gate A4 (Security & Confidentiality)  
> **Status**: **REOPENED / P0 (Gate A4 remains FAIL)**  
> **Context**: Resolving current operating state leakage across public channels.  

---

## 1. Five-Surface Security Audit Matrix

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
