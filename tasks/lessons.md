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


---

## 2026-10-27: Critical Flaws in Error Categorization & Data Merging (异常分类与跨源合并深刻教训)

### Context & User Correction
1. **BYD 异常捕获过宽 (Fatal vs Recoverable)**:
   - `scripts/refresh_byd_v1_3_formal.py` 粗暴捕获了所有 `BYDFormalRefreshError` 并转为退出码 10 (`data_blocked`)。
   - 严重漏洞：`BYDFormalRefreshError` 也用于历史数据篡改、重复日期、历史回放前缀不匹配等严重问题。将其统一转为 10 会导致原本致命的历史损坏被系统降级容忍，破坏 fail-closed 原则。
   - **铁律**：只有明确的“前瞻观测日尚未到达”可转为 `data_blocked`；所有历史完整性、回放偏差、契约哈希不符必须维持致命退出 (code 1)。
2. **跨源成交量差异静默污染历史 (Historical Overlap Pollution)**:
   - `scripts/data/refresh_selected_pool_prices.py` 将 `volume` 移出 overlap 比对后，后续仍执行 `keep="last"`，导致重叠区间的成交量被新供应商（以“股”为单位）静默覆盖原先经过核验的历史数据（以“手”为单位）。
   - 严重漏洞：导致 Alpha158、量价因子历史特征被直接污染。
   - **铁律**：历史重叠区间的数据（包括价格和成交量）必须严格保留原经过治理的基准值，跨源拉取的数据只能向前单向追加 ($t > T_{cutoff}$)。
3. **系统事实与 Issue 状态脱节 (GitHub Issue Sync)**:
   - 本地文档声明 Issue #1288 "REOPENED"，但 GitHub 线上实际为 Closed。
   - **铁律**：文档声明必须配合实际 CLI / API 动作同步到系统真实状态。

---

## 2026-10-27: CI Prepare Stage Hygiene & Typed Exception Scope (CI 门禁与异常作用域精简)

### Context & User Correction (Run 40359577256)
1. **测试代码中的未引用局部变量引发 CI 熔断 (Ruff F841)**:
   - `tests/test_refresh_selected_pool_prices.py` 中引入了 `original_bytes = (source / "000001.csv").read_bytes()` 但未在断言中使用。
   - CI 的 `prepare` 阶段先跑 `ruff check`，任何微小未引用变量直接退出，导致后续实际拉数和策略阶段根本未执行。
   - **铁律**：每次提交与推送前必须强制执行 `uv run ruff check`，所有声明的测试快照变量必须具备明确断言（如证明历史源文件未被就地修改）。
2. **防守型字符串模式匹配的降级隐患 (String Matching Fallback in Exceptions)**:
   - `scripts/refresh_byd_v1_3_formal.py` 在已有 `BYDProspectiveDataMissingError` 类型化异常的情况下，仍在通用 `BYDFormalRefreshError` 中保留了 `if "do not reach target cutoff" in str(exc): return 10`。
   - **隐患**：若底层其他致命完整性、数据库损坏或契约不一致错误的异常消息偶然包含该文字，会导致致命故障被误当作正常前瞻延迟降级处理。
   - **铁律**：一旦建立了专门的领域异常类型，彻底删除防御性字符串模式匹配；只有类型匹配才能进入特定降级处理，其余所有异常一律作为未受控致命错误 fail-closed。

---

## 2026-10-27: Projection Contract Dynamic Binding & Backtest State Decoupling (契约动态绑定与回测解耦)

### Context & Implementation
1. **投研回测与实时执行状态解耦 (Stop The Bleed)**:
   - 彻底移除了 `scripts/refresh_cn_27_v1_3_formal.py` 中向 `candidate["evidence"]` 注入包含持仓明文的 `operating_state`，全面对齐 BYD v1.3 的 `operational_monitoring` 独立指示。
   - 删除了 `scripts/run_formal_refresh_transaction.py` 中过时的强制检查代码，阻止未来增量刷新向公开 Git 提交包含敏感权重的 `lineage.json`。
2. **测试中断言哈希随流水线推进脆弱硬编码 (Dynamic Binding vs. Hardcoded Bundle IDs)**:
   - `tests/test_public_source_boundary.py` 中写死了 CN_27 在 `2026-10-23` 的 `canonical_bundle_id`。随着正式刷新成功推进到 `2026-10-26`，该硬编码断言立刻抛错。
   - **铁律**：验证派生资产（如公开投影）与源资产（如权威回测包）的密码学绑定时，必须动态读取权威目录（`data/research/formal_model_runs/catalog.json`）并断言绑定相等性，严禁写死易随交易日推进发生变迁的散列值。
