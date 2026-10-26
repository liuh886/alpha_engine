# Lessons Learned & Operational Memory

## 2026-10-26: Strict Acceptance Boundaries vs. Premature Scope Expansion (验收口径膨胀的深刻教训)

### Context & User Correction
The user identified premature scope expansion in `tasks/todo.md` and the scorecard:
- **Phase 3 (Privacy & Security / Gate A4)** was marked "验收通过 / PASS", but this was a false positive of scope:
  - `tests/test_public_source_boundary.py` only checked the locally generated build directory (`public_historical_projection_v1` in `qlib-dashboard/dist`).
  - It failed to cover the public GitHub repository itself, which is `public` and directly tracks the raw canonical lineage and decision ledgers (`data/research/formal_model_runs/cn_27_rotation/cn_27_v1_3/**/lineage.json`, blob SHA `13489a0d...`).
  - Anyone viewing GitHub can inspect `operating_state.current_weights` in plain text. Local projection stripping does NOT close the repository-level security boundary.
  - **Verdict**: Gate A4 remains **FAIL / OPEN** until the public Git repository source files are sanitized or decoupled.
- **Phase 4 (v1 Integration & Release Candidate / Gate A7)** was marked "验收通过", but only document PR #1276 was merged:
  - Release Candidate acceptance requires end-to-end operational verification under a single frozen SHA, proven publication success in real production (which failed in Run 40321512230), and privacy-compliant rollback/recovery verification.
  - Merging a documentation PR is NOT a validated Release Candidate.
  - **Verdict**: Phase 4 remains **未验收 (INCOMPLETE / BLOCKED)**.

### Rules Established (Never Violate)
1. **Never conflate code changes with boundary closure**:
   - Modifying a consumer export script is a code change, NOT proof that the data source is secure.
   - If the repository is public, every tracked file in Git is public. Asserting zero leakage requires scanning git-tracked files in the public repo, not just build output directories.
2. **Never label Release Candidate "验收通过" without real production publication**:
   - An RC is only accepted when:
     a) All hard gates A0–A6 are independently verified with evidence;
     b) A real, non-synthetic production run succeeds end-to-end under the candidate SHA;
     c) Owner performs explicit review and acceptance (A7).
3. **Transparent Status Reporting**:
   - Use strict, uninflated statuses: "局部代码交付完成，完整安全边界待闭环" rather than "验收通过".

---

## 2026-10-26: Production Pipeline Resilience vs. Fail-Closed Boundary

### Context
GitHub Actions Run 40321512230 on 2026-10-26 failed during daily formal backtest & market evidence refresh.
- BYD strategy calculation aborted with `execution_failed` because prospective observations did not reach target cutoff (latest was 2026-10-23 instead of 2026-10-26).
- CN_27 strategy calculation safely blocked with `data_blocked` due to 22 required symbols being flagged by Provider Health.
- Atomic publication aborted because BYD reported `execution_failed` (a FATAL state) rather than a governed data block.

### Root Causes
1. **Timing Inversion & Coupling**:
   - `byd-prospective-shadow.yml` was scheduled at 11:30 UTC (19:30 CST), whereas `formal-backtest-refresh.yml` ran at 08:30 UTC (16:30 CST) or on push to `main`.
   - The prospective updater had not yet executed for today's market close when the refresh was triggered.
2. **Error Classification Gap**:
   - `scripts/refresh_byd_v1_3_formal.py` let `BYDFormalRefreshError` escape unhandled (exiting code 1), causing `run_formal_strategy_refresh.py` to classify it as `execution_failed` (FATAL), which melts the whole fan-in transaction.
   - It should catch missing observation data and raise `DataBlockedError` (exit code 10), allowing graceful retention (`status: degraded`).
3. **Provider Overlap Check Too Strict on Volume Units**:
   - Tushare triggered rate limits (`40203: 1 call/min for adj_factor`).
   - The fallback provider `akshare_sina` fetched valid prices, but `refresh_selected_pool_prices.py` checked `fields = ("open", "high", "low", "close", "factor", "volume")`.
   - Sina returned volume in shares instead of lots, causing `mismatched_fields=volume` and rejecting the entire valid price series.

### Rules Established
- **Fail-Closed vs. Operational Block**: A missing future session in prospective observation is a **governed data block (`data_blocked`)**, not an unhandled strategy crash (`execution_failed`). Always map missing external inputs to exit code 10.
- **Volume Unit Tolerance**: In daily price refresh overlap verification, volume unit differences across vendors (lots vs shares) must not invalidate exact price/factor matches. Price and adjustment factors are mandatory; volume should be verified for presence and sign, but not locked to identical vendor scaling across distinct providers.
- **Workflow Order of Operations**: Scheduled dependent tasks (like prospective shadow observations) must execute before downstream aggregators (like formal backtest refresh).
