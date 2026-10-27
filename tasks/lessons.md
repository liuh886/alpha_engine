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

## 2026-10-27: Reusable Research Data Slices & PIT Provenance (可复用投研数据微切片与 PIT 血缘铁律)

### Context & Design
In launching Track B Phase B2 (RI-03A), we addressed the historical pain point where researchers wrote ad-hoc scripts to parse disparate JSON/CSV files, often violating point-in-time boundaries or creating redundant database shadows.

### Rules Established
1. **No-Duplication Architecture (零冗余存储铁律)**:
   - Data slice readers must return memory views, generators, or lightweight extracts directly from verified canonical files in `data/research/`.
   - Never introduce DuckDB, ClickHouse, or a secondary SQLite database to "cache" or "index" already-verified research files.
2. **Fail-Closed PIT Validation (PIT 越界坚决阻断)**:
   - If an algorithm or query requests an adjustment or event whose announcement date postdates the decision cutoff ($t_{announced} > T_{cutoff}$), the reader must return an explicit `status: blocked` with a structured blocker reason (`PIT_VIOLATION_FUTURE_EVENT_ANNOUNCEMENT`).
   - Never forward-fill, never backdate, and never silently substitute unverified values.
3. **Reference Proofs Before Implementation (编码前先冻结事实样本)**:
   - Always freeze concrete, verifiable test cases with historical issuer facts (such as Jinpan Technology `688676` dividend announced 2026-09-23 vs cutoff 2026-09-04) before implementing the reader, ensuring tests assert real data behaviors rather than mocked illusions.

---

## 2026-10-27: Projection Contract Dynamic Binding & Backtest State Decoupling (契约动态绑定与回测解耦)

### Context & Implementation
1. **投研回测与实时执行状态解耦 (Stop The Bleed)**:
   - 彻底移除了 `scripts/refresh_cn_27_v1_3_formal.py` 中向 `candidate["evidence"]` 注入包含持仓明文的 `operating_state`，全面对齐 BYD v1.3 的 `operational_monitoring` 独立指示。
   - 删除了 `scripts/run_formal_refresh_transaction.py` 中过时的强制检查代码，阻止未来增量刷新向公开 Git 提交包含敏感权重的 `lineage.json`。
2. **测试中断言哈希随流水线推进脆弱硬编码 (Dynamic Binding vs. Hardcoded Bundle IDs)**:
   - `tests/test_public_source_boundary.py` 中写死了 CN_27 在 `2026-10-23` 的 `canonical_bundle_id`。随着正式刷新成功推进到 `2026-10-26`，该硬编码断言立刻抛错。
   - **铁律**：验证派生资产（如公开投影）与源资产（如权威回测包）的密码学绑定时，必须动态读取权威目录（`data/research/formal_model_runs/catalog.json`）并断言绑定相等性，严禁写死易随交易日推进发生变迁的散列值。

---

## 2026-10-27: Dual-Consumer Slice Reuse & Anti-Lookahead Tail Enforcement (双消费者数据切片复用与尾部防未来函数)

### Context & Design (RI-04)
In RI-04, we integrated two completely distinct research problems (`CN Cross-Sectional Ranking` vs. `RDI Event Horizon Readiness`) into the unified `get_research_data_slice()` data plane.

### Rules Established
1. **Separation of Candidates and Reference Instruments in Slice Governance**:
   - `AGENTS.md` strictly dictates that candidate equities and reference/benchmark instruments (e.g. `000300.SH`) are distinct roles.
   - The reusable slice resolver must support both pool members and authorized market reference instruments/benchmarks (via `reference_instrument_registry_v1.yaml` and `catalog.json["benchmark"]`), maintaining market isolation while preventing researchers from having to bypass governance or hack pool YAMLs to inspect benchmarks.
2. **Strict Tail Horizon Fail-Closed Rigor (防未来函数尾部截断铁律)**:
   - When evaluating multi-horizon forward readiness (e.g. 7, 14, 28 trading sessions), events occurring near the evaluation cutoff date may have sufficient data for shorter horizons (e.g. 7 days) but lack future bars for longer horizons (e.g. 14 or 28 days).
   - Under NO circumstances may these future missing bars be forward-filled, estimated, or synthetically padded.
   - The consumer MUST fail-closed with `status: blocked` and report `insufficient_future_bars` for any horizon exceeding the historical cutoff, strictly preserving empirical truth.

---

## 2026-10-27: Researcher Efficiency Benchmarking & CLI Tabular Export (投研效率度量与 CLI 导出铁律)

### Context & Implementation (RI-05)
In RI-05, we quantitatively benchmarked the governed data slice plane against the legacy ad-hoc script approach on a fixed US tech cross-section problem (`AAPL`, `GOOGL`, `MSFT`, `NVDA` vs. `QQQ`), achieving an 89.6% reduction in boilerplate code and a 71.4% reduction in manual steps.

### Rules Established
1. **Mathematical Equivalence Must Precede Efficiency Claims**:
   - Never claim an efficiency gain without proving mathematical equivalence ($|\Delta| < 10^{-5}$) between the legacy parser and the unified data slice extractor on identical raw evidence.
   - Preserves feature integrity for quant models while removing boilerplate.
2. **CLI Data Export Fail-Closed Integrity**:
   - When providing tabular data exports via CLI (`--data-output <path>`), the file must ONLY be written if `result.is_ready` is true.
   - If the slice is blocked by governance or PIT lookahead, the exporter MUST strictly suppress file creation (or remove any partial file), returning exit code 10 (`data_blocked`) so downstream tools or scripts can never consume unverified or forward-looking data.

---

## 2026-10-27: Empirical Rigor, Safe Atomic CLI Writes & True PIT Qualification (实证严谨性、安全写入与 PIT 资质分级)

### Context & User Correction
The user identified four critical areas requiring calibration across RI-03/04/05:
1. **RDI Consumer unanchored to real events**: RI-04 used arbitrary dates without binding verified `#1272` `RiskEvent` provenance (`source_id`, `source_hash`, `available_at`).
2. **Heuristic assumptions disguised as empirical metrics**: RI-05 hardcoded 48->5 lines, 7->2 steps, and boolean PIT flags, labeling them as "实测".
3. **Destructive CLI file deletion**: `alpha data slice --data-output` unlinked pre-existing user files when blocked.
4. **Overclaiming PIT readiness**: `status: ready` was susceptible to being misread as "strict PIT certified", whereas it currently only verifies observation cutoff boundaries.

### Rules Established
1. **Never Conflate Heuristic Estimates with Empirical Evidence**:
   - Workflow task steps (e.g. 7 steps -> 2 steps) are human cognitive models and must be explicitly labeled `estimated_*`.
   - Empirical metrics must be dynamically calculated from execution (AST statement counts via `inspect`/`ast`, peak memory via `tracemalloc`, timer via `perf_counter`, and PIT lookahead interception verified via actual challenge execution with `end_date > cutoff`).
2. **Safe Atomic Writing (Zero Destructive Side Effects)**:
   - File exports must write to a temporary file in the target directory and rename atomically.
   - If execution fails or is blocked, NEVER touch or delete any existing file at the target path. Leave user files intact and return exit code 10.
3. **Observation Cutoff Bounds vs. Full Multi-Vintage PIT Certification**:
   - Meeting `end_date <= as_of_cutoff` is an **observation cutoff verification**, NOT full PIT certification under ADR-0005.
   - Data slice receipts must explicitly declare `pit_qualification: "observation_cutoff_verified_not_revision_certified"`, `pit_certified: false`, and disclose `pit_limitations` until vendor availability timestamps (`t_available`) and multi-vintage restatement histories are proven.
4. **Mandatory Event Provenance in Macro Risk Studies (#1272)**:
   - Forward horizon studies must bind to an authoritative `RiskEvent` with verified source timestamps.
   - Missing event history cannot be treated as zero or substituted with unanchored dates; it must strictly fail closed with `blocked_event_pit_coverage`.

---

## 2026-10-27: Walk-Forward Out-of-Sample Splicing & Zero-Lookahead Simulation (滚动步进样本外评估与防未来函数)

### Context & Implementation (Phase 6.0)
In launching the real investment hypothesis Walk-Forward pipeline (`us_tech_vol_reversal_v1`), we evaluated cross-sectional volatility spread and short-term reversal across 8 US tech leaders (`AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMZN`, `META`, `AVGO`, `TSLA` vs `QQQ`) over 3 expanding folds (2025H1, 2025H2, 2026 Tail).

### Rules Established
1. **Certified Warmup Lookback Splicing (预热数据严密取自 In-Sample 尾部)**:
   - Technical indicators (e.g. 20-day realized volatility, 5-day reversal) require trailing history to compute signals for day 1 of the Out-of-Sample test window.
   - Splicing MUST only pull bars from the certified tail of the training slice (which was already certified $\le T_{train\_cutoff} < T_{test\_start}$).
   - Never pull trailing bars from uncertified test data or outside declared boundaries.
2. **Next-Day Execution Boundary (信号生成与持仓执行严格跨日)**:
   - Cross-sectional ranking and portfolio weights are determined strictly at close of session $t-1$.
   - Realized returns are evaluated over session $(t-1, t]$. Same-day bar returns ($close_t / open_t$ or $close_t / close_t$) cannot be used to weight session $t$ portfolios.
3. **End-to-End Cryptographic Sealing & Immutable Hashes**:
   - Every training slice and testing slice produces an immutable `data_hash`.
   - The overall study bundles all fold metrics and hashes into a canonical JSON payload, hashed via SHA-256 (`study_hash`).
   - Asserts 100% determinism across runs, ensuring zero hidden state drift.
4. **Targeted Invariant Assertions Without Unbounded File Traversals**:
   - In test assertions verifying "zero secondary databases", do NOT use recursive `ROOT.glob("**/*.duckdb")` as it traverses `.venv` / `node_modules` on Windows, causing 40s+ slowdowns.
   - Use targeted directory checks (`ROOT.glob("*.db")` and `(ROOT / "data").glob("*.db")`).

---

## 2026-10-27: Walk-Forward Engine v0.2 Methodological Calibration (统计计算口径与 WFO 严密性教训)

### Context & User Correction
1. **Spearman IC 样本协方差与总体标准差分母不一致 (Mathematical Flaw)**:
   - `_compute_spearman_ic` 原实现使用 `np.cov` (除以 $n-1$) 与 `np.std` (除以 $n$)，导致分母偏小，完美正相关时算出 1.3333 (n=4) 或 1.1429 (n=8)。
   - **铁律**：严禁混用无偏样本协方差与总体标准差。必须复用 `scipy.stats.spearmanr`，并对常数序列（方差为 0）和退化样本做严格的 0.0 保守防守。
2. **Fail-Closed 整体研究完整性 (Fold Integrity Gate)**:
   - 原代码过滤 `ready_folds` 后，如果任一 Fold 被阻断，仍对剩余通过的 Fold 计算累计收益。
   - 严重漏洞：这会导致缺失未知区间的缺陷被掩盖，发布看似完整的残缺业绩。
   - **铁律**：预先声明的研究折叠必须全部就绪；若任意一个 Fold `status != "ready"`，整体研究必须立即置为 `status: "blocked"`，绝对禁止静默删除失败区间并输出片面收益。
3. **真实 Purge Margin 与在样本参数优化冻结 (Train-Select-Freeze-OOS)**:
   - `purged_margin_days=20` 绝不能仅停留在数据结构声明，必须在训练期末尾真实剔除对应交易日（180 个样本），阻断未来信息泄漏。
   - 真正的 Walk-Forward 必须在样本内执行网格参数选择并**冻结 (`selected_parameters`)**，再将冻结参数外推至测试期，严禁全区间硬编码同一组参数。
4. **交易摩擦与敏感性分析 (Net Drag & Turnover)**:
   - 日均 16%~29% 的换手具有显著交易成本。必须引入单边费用与滑点模型，报告净收益及 0 bps、8 bps、15 bps 多档敏感性分析。
5. **向量化仿真加速 (Vectorized Numpy Execution)**:
   - 在高频或参数网格迭代中，严禁在 Python 循环中频繁调用 DataFrame `.loc`，应在函数入口处预切片为连续 Numpy 数组，将仿真耗时从 320 秒降至 31 秒（提速 10 倍）。

---

## 2026-10-27: Walk-Forward Engine v0.3 Session Integrity & Asset Weight Drift (会话完整性与资产负债级摩擦会计教训)

### Context & User Correction
1. **OOS 折叠首日被静默遗漏 (Session 1 Omission)**:
   - `_simulate_portfolio` 之前在测试区间上从 `i = 1` 开始计算，传入的 sessions 仅包含测试区间自身，导致第一个测试日（如 Fold 1 的 `2025-01-02`）无法覆盖自上一锚定日收盘至该日收盘的变动，折叠边界每次少算一个交易日收益。
   - **铁律**：必须引入锚定日机制 ($T_{anchor} \le T_{train\_cutoff}$)，在 $T_{anchor}$ 收盘计算信号并在 $T_{test\_start}$ 首日开盘/收盘间执行第一笔收益；断言 `len(daily_net_returns) == len(test_sessions)` 严格相等（Fold 1 为 122 日、Fold 2 为 128 日、Fold 3 为 170 日，420 个交易日连续无缝）。
2. **严格 Fail-Closed 杜绝静默跳过与填零 (Absolute Fail-Closed Boundary)**:
   - 之前在候选股票不足 `top_k` 时使用 `continue` 跳过交易日，基准缺失时直接填 0.0，训练样本不足时退回未剪裁分支。这会改变收益序列却保持 `ready` 状态。
   - **铁律**：投研流水线必须绝对 fail-closed。任何缺失候选价格、基准价格为 NaN、有效候选不足 `top_k` 或训练长度短于 Purge 的情况，必须立即抛出 `SimulationBlockError` 或将 Fold 状态置为 `blocked`，杜绝任何以跳过交易日或填零维持 `ready` 状态的妥协。
3. **资产负债级权重漂移与单边换手会计 (Weight Drift & Rebalance Friction)**:
   - 组合换手不能简单用前后持仓集合差异估算。盘中价格相对变动会引起资产权重自然漂移：
     $$w_{i, t}^{drift} = \frac{w_{i, t-1}^{target}(1 + r_{i, t})}{1 + r_{gross, t}}$$
   - 真实换手为单边换手率 $\text{Turnover}_t = \frac{1}{2} \sum |w_{i, t}^{target} - w_{i, t}^{drift}|$。首日由现金建仓扣除完整换手费用（Turnover = 1.0），后续每日再平衡计入价格漂移引起的调仓摩擦。
4. **完整实验配置与代码版本绑定至研究指纹 (Experiment Receipt Lineage Binding)**:
   - 单纯绑定 Fold 结果与数据哈希不足以防范参数或代码变动碰撞。
   - **铁律**：将完整的 `config.to_dict()`（含 param_grid、各档摩擦费率、价格模式与折叠定义）以及当前 Git Commit SHA 完整嵌入 canonical payload 与研究收据中，确保任何实验定义或代码版本变动必然改变 `study_hash`。

---

## 2026-10-27: Walk-Forward Engine v0.3.1 Exchange Calendar & Code Source Hashing (交易所日历与代码指纹铁律)

### Context & User Correction
1. **研究哈希与 Git 提交时序耦合 (Git Commit Fixed-Point Trap)**:
   - 之前将 `git rev-parse HEAD` 直接嵌入 `study_payload`，导致在代码提交前生成的报告哈希与提交后重跑的哈希必然不一致。
   - **铁律**：严禁仅依赖动态的 `git rev-parse HEAD` 作为唯一代码指纹。必须直接计算执行源码文件（`pipeline.py`, `contracts.py`, `research_slice.py`）的 SHA-256 (`code_source_sha256`) 嵌入研究指纹，确保源码不变时指纹 100% 稳定，同时在无法获取有效 Git SHA 时直接阻断，严禁静默回退到 `"unknown"`。
2. **交易日历必须与交易所官方日历严格比对 (Exchange Calendar Verification)**:
   - 仅仅检查仿真收益天数与行情切片天数相等不够防范整日缺失（若行情源丢失某一天，两者同时少一天仍能相等）。
   - **铁律**：必须接入官方交易所日历（美股 `XNYS`、A股 `XSHG`），对声明的 In-Sample 与 Out-of-Sample 区间严格校验每一个交易日，多一天或缺一天均立即阻断 (`missing_or_extra_oos_exchange_sessions`)。
3. **独立 Fold 必须实现闭环期末清仓 (Terminal Liquidation Closure)**:
   - 若模拟的是独立 Fold，首日从现金建仓收取摩擦，期末必须平仓回现金收取末日平仓摩擦，杜绝不平仓的免费午餐；若连续持仓，则折叠间只计漂移调仓。
   - 明确选定独立 Fold 闭环口径：首日建仓（Turnover = 1.0），每日漂移再平衡，末日按漂移权重平仓回现金（Turnover = 1.0），实现完整的现金到现金闭环。
4. **Python 切片负零陷阱 (Python Negative-Zero Slicing Trap)**:
   - 当 `purged_margin_days=0` 时，`lst[:-0]` 等价于 `lst[:0]`，会产生空列表并误杀有效数据。
   - **铁律**：切片截断必须先校验 `purged_margin > 0`，对合法 0 值直接取全列表，坚决杜绝切片负零陷阱。

---

## 2026-10-27: Personal Investment Decoupled Lens & Zero Privacy Leakage (个人投资解耦透镜与隐私铁律)

### Context & User Direction
The user established a personal US equity holdings repository in Obsidian (`D:\Documents\zhihaol\200_Area\Investment\Pool`) and required:
1. Clarify how these holdings can help and interface with Alpha Engine;
2. Strict decoupling: The personal ledger is the user's private financial record, decoupled from Alpha Engine;
3. Speak like a human (说人话): Keep the interface, explanations, and outputs simple, direct, and practical.

### Rules Established
1. **Unidirectional Decoupling (单向解耦与零反向写入)**:
   - Personal records remain purely in Obsidian Markdown. Alpha Engine never writes, edits, or deletes any personal file.
   - The interface is read-only. Alpha Engine extracts ticker metadata to provide quantitative capability, without acting as a personal ledger or portfolio accountant.
2. **Gate A4 / Zero Privacy Leakage (零财务敏感数据读取与暴露)**:
   - The user's notes contain private transaction and portfolio data (`shares`, `total_cost`, `cost_basis`, `realized_pnl`, `accounts`, cash amounts, transaction tables).
   - **铁律**：投研透镜（Personal Lens）在 YAML 解析阶段与数据类（`PersonalHoldingAudit`）两级设置防御性白名单过滤，绝不读取、存储、返回或打印任何个人财务数值与账户敏感词。
3. **Accurate Market Data Readiness Mapping (治理底座与行情切片精准比对)**:
   - 区分候选选股池（US 87）、参考基准资产（Ref ETF）、现金储备（Cash）、跨市场标的（EU）以及缺失行情切片的标的。
   - 对未覆盖标的（如杠杆 ETF、未上市股权或跨市场标的）诚实标记 `missing_market_evidence` 或 `unregistered_market_*`，绝不猜测或混淆。

---

## 2026-10-27: Supplementing Holdings Evidence via Reference Roles (参考资产治理扩充铁律)

### Context & Implementation
The user requested supplementing market data for the 4 missing tickers (`PL`, `SOXL`, `SPCX`, `IQQ`).
- Candidate pool `us_selected_equities_v2.yaml` is frozen at 87 names under ADR-0003 governance.
- Expanding candidates requires formal versioning (`us_selected_equities_v3`), but non-candidate securities can be legally ingested into the evidence plane by registering as **reference instruments (`comparison_reference`)** in `reference_instrument_registry_v1.yaml`.
- This strictly preserves the candidate universe boundaries while granting clean `get_research_data_slice()` and `PersonalLens` coverage.

### Rules Established
1. **Never Silently Inject Securities without Governance Identity (绝不注入无角色标的)**:
   - Any new market evidence file in `symbols/{ticker}.json` must declare governed `roles` (e.g. `["comparison_reference"]`).
   - Every supplemented symbol must be registered in `configs/pools/reference_instrument_registry_v1.yaml` with `candidate_eligible: false` and `portfolio_eligible_by_default: false`.
2. **Deterministic Full Technical Indicator Generation (指标全量规范物化)**:
   - Materializing market evidence files must include standard technical studies (`boll20`, `macd_12_26_9`, `rsi14`) computed on exact OHLCV series.
   - All generated evidence files and catalog entries must bind SHA-256 hashes to guarantee data immutability.
3. **Cross-Market Geographic Boundary Integrity (跨市场地理边界清晰划分)**:
   - For foreign securities (e.g. `2DG` in Frankfurt XETRA / `2DG.DE`, primary `SIVE.ST` in Stockholm), do not conflate them with the US dollar equity plane. Clearly mark them as foreign/cross-market assets.

---

## 2026-10-27: Multi-Domain Research Study Workspace Integration (投研工作区第二阶段多领域接入铁律)

### Context & Implementation
In Phase 7.0, we completed Phase 2 of the Research Study Workspace (`alpha research study`), expanding beyond the initial single-hypothesis volatility reversal to a unified 4-family quantitative study workspace:
1. `us_tech_vol_reversal_v1`: Expanding Walk-Forward Volatility Reversal with drift turnover and friction closure;
2. `cross_sectional_xgb_v1`: Multi-factor non-linear XGBoost ranking with query groups and OOS evaluation;
3. `factor_exploration_v1`: Multi-factor Rank IC, IC-IR, positive rate, and cross-sectional monotonicity exploration;
4. `ashare_rdi_v1`: A-share CSI 300 macro/policy risk event (#1272) 7/14/28-session forward outcome response.

### Rules Established
1. **Single Data Plane Across All Research Domains (单一数据底座铁律)**:
   - All study families MUST consume market bars and events exclusively via `src/data/research_slice.py` (`get_research_data_slice`).
   - Zero duplicate caching, zero shadow databases (DuckDB/SQLite), and zero ad-hoc CSV/JSON parsing scripts.
2. **Strict Cryptographic & Lineage Binding (收据密码学绑定铁律)**:
   - Every study produces a canonical payload with SHA-256 `study_hash` bound to the input data hash, code source file hashes (`code_source_sha256`), and Git commit SHA.
   - Receipts are retained atomically in `artifacts/research_studies/<study_id>/<study_hash>.json` using exclusive writes (`save_receipt_exclusive`).
3. **Fail-Closed Gate on Missing Events or Unverified Boundaries**:
   - In A-Share RDI studies, missing risk events or events postdating the cutoff (`available_at > as_of_cutoff`) MUST fail closed with `status: blocked` and exit code 10.
   - In XGBoost studies, unlisted symbols or sessions failing exchange calendar match MUST fail closed with exit code 10, preventing silent data substitution.
4. **Strict Cross-Family Comparison Isolation (严禁跨领域胡乱比对)**:
   - `compare_studies` must enforce matching `study_id` and identical data hashes.
   - Comparing apples to oranges (e.g. comparing an XGBoost equity ranking with an RDI macro event) MUST raise `ResearchStudyError` fail-closed.

---

## 2026-10-27: XGBoost OOS Temporal Causality, RDI Provenance Hardening & Workspace Modularity (时序因果性、事件来源验证与工作区模块化铁律)

### Context & User Correction
The user conducted a thorough review of Phase 2 and identified critical defects:
1. **XGBoost Lookahead Bias (P0)**:
   - Signals were computed using day $t$ close features, then multiplied by day $t$ close-to-close returns, retroactively earning same-day return.
   - QQQ first-session return was arbitrarily filled with 0.0 instead of using an anchor session.
   - Maximum drawdown curve omitted initial capital baseline 1.0, and gross returns were not derived from true turnover frictions.
2. **RDI Unverified Event Masking (P0)**:
   - The default RDI template used synthetic identifiers (`macro-risk-policy-20240510`) that were not validated against an authoritative archived repository event store.
   - The repository explicitly notes `historical_pit_event_coverage_complete: false`. Unverified events must strictly fail closed with `blocked_event_pit_coverage` rather than reporting false `ready`.
3. **Workspace Monolith Bloat (P1)**:
   - `src/research/study_workspace.py` ballooned with embedded XGBoost training, portfolio simulation, and factor loops, instead of delegating to domain execution modules.
4. **Research Review Presentation (P1)**:
   - Results were only readable as raw JSON, hindering quick research decision making.

### Rules Established
1. **Strict Temporal Causality & Anchor Session (时序因果与锚定日铁律)**:
   - Signals for trading session $t$ MUST be computed strictly at session $t-1$ close (or $T_{anchor}$ for day 1 of test).
   - Realized returns are evaluated across $(t-1, t]$. Never compute signals at date $t$ close to capture date $t$ returns.
   - Benchmark returns on test day 1 must be calculated from $T_{anchor}$ close to $T_{test\_start}$ close, with zero fill-0.0 compromises.
   - Drawdown curves must initialize with $1.0$.
2. **Authoritative Event Archive Authentication (事件档案核验铁律)**:
   - An RDI risk event is only admissible if verified against the authoritative repository event archive (`historical_pit_event_coverage_complete`).
   - If event coverage is incomplete or the event is unauthenticated, the study MUST fail closed with `blocked_event_pit_coverage` and exit code 10.
3. **Lean Workspace Orchestrator (精简门面与领域解耦)**:
   - `study_workspace.py` MUST serve as a clean orchestrator (discovery, configuration, validation, dispatching, and presentation).
   - Domain-specific execution logic (XGBoost ranker, factor statistics, RDI forward windows) MUST reside in dedicated study execution modules under `src/research/studies/`.
