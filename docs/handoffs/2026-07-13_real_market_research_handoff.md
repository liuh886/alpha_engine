# AlphaEngine 真实市场研究交接文档

**交接日期：2026-07-13**  
**仓库：`liuh886/alpha_engine`**  
**当前主分支基线：`224041f2d8271bb34f122e70d9440edc676ac3c4`**  
**适用范围：固定 10D 研究范式、真实市场数据验收、单因子诊断、后续模型研究**

---

## 1. 当前结论

AlphaEngine 已完成从“多个专用 runner 和重复决策语义”向固定 10D、spec-bound、fail-closed 研究范式的核心收敛。

真实 CN/US 市场数据链已经完整跑通：

```text
版本化研究股票池
  → 真实数据更新与 provider provenance
  → 市场独立 Qlib provider
  → real-market acceptance
  → horizon-contained single-factor diagnostics
  → diagnostic-only evidence
```

Issue #124 已完成并由 PR #146 固化证据。当前结果只证明：

- 数据链和研究合同可复现；
- CN/US 数据均达到当前 acceptance 门槛；
- 单因子诊断可以在真实数据上执行；
- 目前没有证据支持 factor/model promotion 或交易就绪。

必须继续保持：

```text
diagnostic_only = true
promotion_eligible = false
promotion_evaluated = false
trade_ready = false
```

---

## 2. 当前仓库状态

### 已完成并合并

- PR #92：replacement-first 核心收敛架构。
- PR #93：固定 10D 结构化研究合同。
- PR #94：declared/effective execution identity gate。
- PR #99 / #101：CN/US spec-bound Qlib adapters。
- PR #100 / #104：`SignalFrame → PortfolioIntent → EvaluationReport` parity 与旧入口兼容迁移。
- PR #102 / #103 / #105 / #106：唯一 PromotionDecision 与只读消费者。
- PR #107 / #109 / #110：旧 specialized runners 降级为兼容 wrapper。
- PR #111 / #112 / #113：adapter 纯 evidence producer、公共 Qlib core、窄化 evaluation context。
- PR #114 / #116：历史 universe/stable-blend 流程降级为 diagnostic-only。
- PR #115：删除 ranker 的缺失特征填 0 和缺失标签填 0.5。
- PR #117：真实市场 acceptance gate。
- PR #118：版本化 CN/US 研究股票池。
- PR #119 / #123：spec-bound factor diagnostics 与一键真实市场研究管线。
- PR #122：provider 与 symbol identity 修正。
- PR #131：交易日边界与 OHLC 异常审计。
- PR #132：CN/US/HK 市场独立 Qlib providers，验证市场自身 10-session 语义。
- PR #133：truthful partial snapshot 与 provider provenance。
- PR #137 / #139：CSI 300 AkShare 指数历史及 `cn:000300` symbol-level provider policy。
- PR #142：仅容忍机器精度级 OHLC roundoff。
- PR #144：T+10 标签不得跨 OOS 窗口边界。
- PR #146：持久化 Issue #124 最终真实市场证据，关闭 Issue #124。
- PR #149：分离 configured factor IDs 与 canonical expression identities，关闭 Issue #147。

### 当前开放项

#### Issue #148

目标：把“不完整最终 OOS 窗口如何处理”变成明确、版本化的研究合同。

#### Draft PR #150

标题：`fix(research): make incomplete OOS window policy explicit`

当前状态：**不得合并。**

原因：

- 常规 Alpha Engine CI 已通过；
- 但一次性 `Patch incomplete OOS window policy` workflow 失败；
- 当前 diff 仍包含一次性文件：
  - `.github/workflows/patch-incomplete-oos-window-policy.yml`
  - `scripts/_patch_incomplete_oos_window_policy.py`
  - `scripts/_harden_oos_adapter_sampling.py`
  - `scripts/_harden_oos_policy_evidence.py`
- 当前永久改动只有 `src/research/window_policy.py` 和 `tests/test_window_policy.py`；
- 预期的 paradigm schema、execution contract、CN/US adapters、factor diagnostics 和 canonical specs 集成尚未完整落地。

接手后的首要动作是完成或重做 #150，而不是因为常规 CI 绿色直接合并。

---

## 3. Issue #124 最终证据

证据已由 PR #146 固化在：

```text
docs/evidence/issue-124/
├── README.md
├── evidence_index.json
├── cn/
│   ├── real_market_acceptance.json
│   ├── factor_diagnostics.json
│   └── real_market_research_manifest.json
└── us/
    ├── real_market_acceptance.json
    ├── factor_diagnostics.json
    └── real_market_research_manifest.json
```

原始执行来源：

- final execution PR：#145；
- workflow run：`29203030333`；
- execution head：`c53bc485647c4876b2155ac0a1bb704f1056ad72`；
- production base：`aee95750a819fa414b5e204c322772c9fe61adca`；
- durable evidence merge：`8b2817b3b7ef386a815051121208ea376ffab28f`。

### CN

- Acceptance：**10 passed / 1 warning / 0 failed**。
- 研究股票池：223。
- 完整覆盖：164。
- 最低门槛：50。
- Benchmark：`000300`，覆盖 2021-01-04 至 2026-07-10。
- CSV integrity：165 inspected / 0 invalid / 0 missing。
- Acceptance SHA-256：
  `52e008b381c389e4a01c2f82124fcc33f1c683d74c64583c71c1778c4597d623`
- Diagnostics SHA-256：
  `60d2b0d10cd90bbed68aa362416c2cd03eb553f3cd6e26039628ff81706f6b71`
- Research manifest SHA-256：
  `352b09587a64ddf067e813218d93043834c63464ef5b008e0a91dc4e9978f78b`
- Issue #124 证据版本：47 factor IDs / 23 unique expressions。
- Horizon-contained rebalance dates：46。
- 完整窗口：2024H1、2024H2、2025H1、2025H2。

较高的唯一表达式诊断结果：

| 表达式/代表因子 | 建议方向 | Oriented ICIR | Oriented spread | 同向窗口比例 | 判断 |
|---|---:|---:|---:|---:|---|
| 5D return / `cn:momentum:ret_5d` | invert | 0.2149 | 0.0055 | 50% | 弱，方向不稳定 |
| 5D reversal / `cn:reversal:ref5_close_inv` | keep | 0.2149 | 0.0056 | 50% | 与上项本质相近 |
| high-low ratio | invert | 0.2013 | 0.0069 | 75% | 可保留为研究候选 |
| 5D return volatility | invert | 0.2004 | -0.0014 | 75% | IC 与 spread 不一致，不应 promotion |
| high-low range percentage | invert | 0.1992 | 0.0073 | 75% | 可保留为研究候选 |

CN 当前没有达到 promotion 强度的单因子。

### US

- Acceptance：**10 passed / 1 warning / 0 failed**。
- 研究股票池：133。
- 完整覆盖：120。
- 最低门槛：30。
- Benchmark：QQQ，覆盖 2021-01-04 至 2026-07-10。
- CSV integrity：121 inspected / 0 invalid / 0 missing。
- Acceptance SHA-256：
  `4d427c9aa2f834b154792add30ce7e1bbbe4bb6d5af5afa24466dbb62fc01c75`
- Diagnostics SHA-256：
  `fc52db50a15a55006a190623d434db8298d5d145e4e5d6245ab6232643c9b776`
- Research manifest SHA-256：
  `c9baad0ce4042b010df57bc5e6b8e6f87d835944ca147ff13f0c0e3e64b617d5`
- Issue #124 证据版本：24 factor IDs / 9 unique expressions。
- Horizon-contained rebalance dates：48。
- 完整窗口：2024H1、2024H2、2025H1、2025H2。

较高的唯一表达式诊断结果：

| 表达式/代表因子 | 建议方向 | Oriented ICIR | Oriented spread | 同向窗口比例 | 判断 |
|---|---:|---:|---:|---:|---|
| 20D risk-adjusted momentum | keep | 0.2869 | 0.0104 | 50% | 相对领先，但稳定性不足 |
| 20D momentum | keep | 0.2842 | 0.0111 | 75% | 当前最值得继续验证 |
| 20D volatility | keep | 0.1682 | 0.0344 | 100% | ICIR 较弱，spread 一致 |
| 10D volatility | keep | 0.1607 | 0.0268 | 100% | ICIR 较弱，spread 一致 |
| 5D momentum | keep | 0.1505 | 0.0094 | 75% | 次级候选 |

US 当前也没有达到 promotion 强度的单因子。

---

## 4. 证据解释边界

### 4.1 静态股票池与幸存者偏差

CN/US universe 均为 `static_curated`，并明确：

```text
survivorship_bias = true
```

因此当前结果适用于工程验证与探索性研究，不是无偏的历史指数成分回测。

### 4.2 只有四个完整半年度窗口

当前最终证据只包括：

```text
2024H1
2024H2
2025H1
2025H2
```

2026H1 因 `test_end=2026-06-18` 早于自然半年度结束日 2026-06-30 而被排除。Issue #148 / PR #150 正在把该规则显式化。

### 4.3 Orientation 不是独立验证结论

`recommended_orientation` 来源于同一批 OOS 诊断证据的平均 Rank IC。不能在同一批数据上选择 invert/keep 后，再把 oriented 指标描述为独立、无偏的策略表现。

后续采用某一方向时，必须：

- 先锁定方向；
- 在新增时间窗口、nested walk-forward 或独立 holdout 上验证；
- 禁止仅凭本次 oriented ICIR 直接进入模型或交易。

### 4.4 单因子诊断不是完整策略回测

当前 factor diagnostics 主要衡量：

- coverage；
- Rank IC / ICIR；
- fixed Top-N minus Bottom-N raw forward-return spread；
- window consistency。

它不是包含真实换手、交易成本、容量和执行限制的完整 portfolio P&L。

### 4.5 Issue #124 证据 schema 与当前 main 不同

Issue #124 的持久化证据生成于 PR #149 之前：

```text
CN: factor_count = 47 IDs, unique expressions = 23
US: factor_count = 24 IDs, unique expressions = 9
```

PR #149 已将未来 diagnostics 改为：

```text
factors = canonical-expression leaderboard
factor_count = unique expression count
factor_id_count = configured ID count
factor_alias_rows / factor_alias_map = alias audit
```

因此重跑后的 `factor_count` 会变为 CN 23、US 9。这是 schema/identity 修正，不是因子数量突然减少。

---

## 5. 当前生产研究链

```text
ResearchParadigmSpec
  → versioned research universe
  → market-specific real provider
  → real-market acceptance
  → declared/effective execution identity
  → horizon-contained factor diagnostics
  → canonical-expression identity
  → diagnostic-only evidence
```

模型研究链：

```text
ResearchParadigmSpec
  → SpecBoundExecutionPlan
  → common Qlib execution
  → CN/US thin adapter
  → EvaluationContext
  → SignalFrame
  → PortfolioIntent
  → EvaluationReport
  → EvidenceBundle
  → PromotionDecision
```

任何 frontend、registry、agent 或 notebook 只能读取 PromotionDecision，不得自行重新计算 `trade_ready`。

---

## 6. 接手后的执行顺序

### P0：完成 PR #150

1. 检查失败 workflow：`Patch incomplete OOS window policy`。
2. 不要把常规 CI 绿色视为完成。
3. 将 `window_policy` 真正接入：
   - paradigm validation；
   - execution-contract identity；
   - CN/US adapters；
   - factor diagnostics；
   - boundary readiness；
   - canonical CN/US specs。
4. 确保 `complete_windows_only` 保持 Issue #124 的现有行为。
5. 确保 partial final window 永远不计入 `min_windows`。
6. 删除所有一次性 workflow 和 patch scripts。
7. 最终 diff 只能包含永久实现和测试。
8. 完整 CI、真实 pyqlib fixture 全绿后再合并并关闭 #148。

### P1：建立基于最终证据的因子缩减方案

不要直接修改 factor library。先提交一个 evidence-backed proposal，引用：

- CN diagnostics SHA：`60d2b0d1...`；
- US diagnostics SHA：`fc52db50...`。

建议初始研究候选：

- CN：5D reversal、high-low ratio、high-low range；
- US：20D momentum、20D risk-adjusted momentum、10D/20D volatility。

建议隔离或暂缓：

- IC 与 spread 方向不一致的 CN volatility 因子；
- 低覆盖或低 ICIR volume factors；
- 仅通过 alias 重复出现、但没有独立 expression identity 的配置项。

该 PR 只能改变 factor selection，不得同时改变 universe、日期、cadence、benchmark 或 gate。

### P2：锁定方向后做独立验证

对 keep/invert 决策采用以下任一方式：

- 增加新的完整 OOS 窗口；
- nested walk-forward；
- 方向选择与结果评估分离的 holdout；
- point-in-time universe 对照。

不能继续用同一份 Issue #124 evidence 同时选择方向和声称提升。

### P3：小规模模型候选实验

单因子筛选稳定后，再运行 spec-bound ranker：

- 每市场只保留少量 canonical expressions；
- declared candidate manifest 必须等于 effective runtime manifest；
- raw 10D return provenance 保持不变；
- Top-N / Bottom-N、benchmark、日期和 cadence 不变；
- PromotionDecision 继续 fail-closed。

### P4：解决 point-in-time universe

当前静态 universe 的 survivorship bias 是中长期最主要的研究有效性限制。后续应设计：

- point-in-time membership snapshots；
- IPO/listing date eligibility；
- delisted symbol preservation；
- historical index constituent comparison；
- static-curated 与 point-in-time 结果分层报告。

---

## 7. 常用命令

```bash
git checkout main
git pull --ff-only
uv sync --frozen --extra dev
```

运行 CN 真实市场管线：

```bash
uv run python scripts/run_real_market_research.py \
  --root . \
  --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml
```

运行 US 真实市场管线：

```bash
uv run python scripts/run_real_market_research.py \
  --root . \
  --spec configs/research_paradigms/us_10d_qqq_baseline.yaml
```

查看持久化基线：

```bash
cat docs/evidence/issue-124/README.md
cat docs/evidence/issue-124/evidence_index.json
```

运行与研究合同最相关的测试：

```bash
uv run pytest \
  tests/test_research_paradigm.py \
  tests/test_spec_bound_execution.py \
  tests/test_real_market_acceptance.py \
  tests/test_spec_bound_factor_diagnostics.py \
  tests/test_real_market_research_pipeline.py \
  tests/test_window_policy.py \
  -q --strict-markers --tb=short --disable-warnings --maxfail=1
```

---

## 8. 禁止事项

- 不得降低 acceptance 或 promotion gates 以让结果通过。
- 不得用 synthetic fixture 作为真实因子有效性证据。
- 不得把缺失 OHLCV、feature 或 return 填成 0 或中性标签。
- 不得把 benchmark 放入 candidate ranking universe。
- 不得恢复跨市场联合 Qlib calendar。
- 不得在 identity gate 前生成 lifecycle decision。
- 不得让 frontend、registry 或 agent 自行解释 `trade_ready`。
- 不得在一个 PR 中同时修改 factor、universe、日期、cadence 和 thresholds。
- 不得把 oriented diagnostics 描述为独立 holdout 表现。

---

## 9. 完成交接的判定

下一位 agent 接手后，应首先能够回答：

1. 当前主分支为什么仍然不能 promotion？
2. Issue #124 的 CN/US evidence hash 是什么？
3. 47/24 factor IDs 与 23/9 canonical expressions 的差异是什么？
4. 为什么 PR #150 现在不能合并？
5. 下一项工作为什么是显式 window policy，而不是继续调模型？
6. 后续因子方向为什么必须在新 holdout 上验证？

如果以上问题无法从本文件和 `docs/evidence/issue-124/` 回答，不应开始新的因子或模型调参工作。
