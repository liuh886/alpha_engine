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
   - Align CN_27 with BYD v1.3: in `scripts/refresh_cn_27_v1_3_formal.py`, remove the embedded `operating_state` dictionary from `candidate["evidence"]`.
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

## 3. Migration to Protected Authoritative Storage

1. **Protected Operational Target Store**:
   - Live strategy targets, weights, and decision justifications migrate to **Supabase RLS tables** (`strategy_operations`, `current_positions`, `decision_receipts`), accessible only with authenticated Owner JWT credentials.
2. **Public Historical Projection Remains Read-Only**:
   - Public Pages consumers read only sanitized, sealed backtests (`public_historical_projection_v1`).
   - Entitled workstation sessions fetch authorized live targets directly from Supabase via authenticated API.

---

## 4. Rigorous Gate A4 Verification Standard

Gate A4 shall remain **FAIL** until:
- [ ] No git-tracked file in the repository contains plain-text `current_weights` or `target_weights` for active strategies.
- [ ] Actions workflows no longer upload raw operating state in public artifacts.
- [ ] Automated tests include direct anonymous git tree inspection, verifying zero operational leakage across all public surfaces.
