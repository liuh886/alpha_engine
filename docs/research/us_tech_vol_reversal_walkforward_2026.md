# Walk-Forward Quantitative Study: US Tech Volatility Spread & Short-Term Reversal (2025–2026)

> **Authority & Governance**: Track B Quantitative Infrastructure (#1296), ADR-0003, and ADR-0005.  
> **Operational Boundary**: `research_only=true`, `trade_ready=false`, `trade_signal=false`.  
> **Study Identifier**: `us_tech_vol_reversal_v1`<br>
> **Methodology Version**: `v0.3.1` (Complete Session Integrity, Exchange Calendar Enforcement, Asset Weight Drift Accounting, Source Code Cryptographic Sealing & Terminal Liquidation Closure)<br>
> **Cryptographic Study Hash**: `1a21b9a16b0426ff75eb64ae393ac57396cb3586d1fe68177bae69079c380002`<br>
> **Configuration Digest (SHA-256)**: `9950f2af28b11b3fb9172bbc49304b3898afa171c1f5252ecd889368ed89be36`<br>
> **Git Baseline Commit**: `38bd960dd`

---

## 1. Executive Summary & Investment Hypothesis

### 1.1 Economic Rationale
In modern equity markets, mega-capitalization technology equities exhibit substantial cross-sectional dispersion in idiosyncratic volatility and short-term liquidity premiums. Cap-weighted benchmark indices (such as NASDAQ-100 / `QQQ`) tend to become highly concentrated in momentum leaders at peak valuations, exposing investors to severe tail drawdowns during sharp mean-reversions.

### 1.2 Core Investment Hypothesis
> **Hypothesis**: In high-liquidity US megacap tech equities, a cross-sectional portfolio that systematically tilts towards names with **lower trailing 20-day realized volatility** and **recent 5-day price pullbacks (short-term reversal)** will generate superior risk-adjusted returns and out-of-sample excess performance over the cap-weighted benchmark (`QQQ`), avoiding peak volatility shocks while capturing structural recovery upside.

### 1.3 Governed Asset Cross-Section & Qualification Disclosures
- **Market**: US Equities (`market: "us"`)
- **Governed Universe**: `configs/research_universes/us_selected_equities_v2.yaml` (87 names)
- **Candidate Sub-Pool**: `AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMZN`, `META`, `AVGO`, `TSLA` (8 liquid tech leaders)
- **Reference Benchmark**: `QQQ` (Invesco QQQ Trust ETF, role: `benchmark_context`, strictly isolated from candidate ranking)
- **Price Adjustment Mode**: `anchored_adjusted`

> [!IMPORTANT]
> **Data Qualification & Bias Disclosures (ADR-0005)**:
> 1. **Observation Cutoff Verified, Not Revision Certified**: Price and adjustment series meet `end_date <= as_of_cutoff`. The underlying data slice receipt explicitly carries `pit_certified: false`. Multi-vintage restatement histories and historical vendor ingestion timestamps ($t_{available}$) are unverified.
> 2. **Fixed Universe Selection Bias**: The 8 megacap candidate pool is fixed ex-post from `us_selected_equities_v2`. Historical point-in-time constituent reconstitution is not modeled; survivorship and selection biases are acknowledged.
> 3. **Research Exclusivity**: All metrics represent simulated historical research. No live trading recommendations or execution orders are authorized.

---

## 2. Research Data Architecture & Lookahead Enforcement

### 2.1 Reusable Data Slice Integration
The study relies strictly on the Track B data plane entry point [`get_research_data_slice()`](file:///D:/Documents/GitHub/alphaengine/src/data/research_slice.py). No local flat CSVs, ad-hoc pandas readers, DuckDB files, or secondary SQLite tables were spawned.

Each temporal window is explicitly declared via `DataSliceRequest`:
- Enforces temporal cutoff compliance: `end_date <= as_of_cutoff`.
- Fails closed upon unlisted or unregistered securities.
- Generates an immutable, order-invariant `data_hash` (SHA-256) per slice.

### 2.2 Purged Margin Execution & Warmup Lookback
To ensure complete isolation between In-Sample training and Out-of-Sample evaluation:
1. **Active Purge Margin**: Every fold enforces `purged_margin_days = 20`. The trailing 20 business days of the training slice (180 observation samples across 9 assets) are actively pruned from the training set, eliminating overlap between multi-day forward targets and test-period inputs.
2. **Next-Day Execution Boundary**: Signal evaluation at session $t-1$ close uses solely history certified $\le t-1$. Portfolio weights are applied to returns realized over session $(t-1, t]$.
3. **Warmup Splicing**: Trailing 20-day realized volatility and 5-day reversal for the first day of an OOS window are initialized strictly from the certified tail of the In-Sample training slice ($T \le T_{train\_cutoff} < T_{test\_start}$).

### 2.3 Exchange Calendar Enforcement & Complete Round-Trip Accounting
1. **Exchange Calendar Cross-Verification (`exchange_calendars`)**:
   - Every temporal window (both In-Sample and Out-of-Sample) is strictly verified against the official exchange calendar (`XNYS` for US Equities, `XSHG` for CN Equities).
   - Expected session counts: Fold 1 has 122 business sessions, Fold 2 has 128 sessions, Fold 3 has 170 sessions, totaling 420 continuous OOS trading days.
   - Any missing or extraneous trading day immediately triggers a `blocked` fail-closed halt (`missing_or_extra_oos_exchange_sessions`).
2. **Anchor Session Initialization**:
   - Each OOS fold initial target weights are computed at the close of $T_{anchor}$ (the last available session in the certified In-Sample window $\le T_{train\_cutoff}$).
   - The first OOS return is earned on Day 1 ($T_{test\_start}$) across $(T_{anchor}, T_{test\_start}]$, ensuring zero missing days.
3. **Asset Weight Drift & Independent Fold Round-Trip Liquidation**:
   - Intra-day price movement induces natural weight drift from previous targets:
     $$w_{i, t}^{drift} = \frac{w_{i, t-1}^{target} (1 + r_{i, t})}{1 + r_{gross, t}}$$
   - Single-sided portfolio turnover required to rebalance from drifted weights to new targets is:
     $$\text{Turnover}_t = \frac{1}{2} \sum_{i} |w_{i, t}^{target} - w_{i, t}^{drift}|$$
   - **Independent Fold Cash Closure**: Each fold starts with 100% cash (initial buy turnover = 1.0) and finishes with terminal liquidation back to 100% cash (closing liquidation turnover = 1.0).
   - Zero unliquidated open positions: every fold represents a fully costed, closed round-trip investment cycle.

---

## 3. Walk-Forward Optimization (WFO) Design

The study implements a true **Train $\to$ Select $\to$ Freeze $\to$ Out-of-Sample Evaluate** expanding-window workflow across 3 non-overlapping test folds:

```
Timeline:
[ 2022-01-03 ------------------- (Purged: 20d) - 2024-12-31 ] -> Test Fold 1 [ 2025-01-02 - 2025-06-30 ]
[ 2022-01-03 --------------------------------- (Purged: 20d) - 2025-06-30 ] -> Test Fold 2 [ 2025-07-01 - 2025-12-31 ]
[ 2022-01-03 ----------------------------------------------- (Purged: 20d) - 2025-12-31 ] -> Test Fold 3 [ 2026-01-02 - 2026-09-04 ]
```

### 3.1 In-Sample Parameter Optimization & Freezing
In each fold's In-Sample period, a grid search is performed over the purged training window across:
- Short-term reversal weight $w_{rev} \in \{0.5, 1.0, 1.5\}$
- Realized volatility weight $w_{vol} \in \{0.5, 1.0, 1.5\}$
- Portfolio breadth $top\_k \in \{2, 3\}$

The parameter set $\theta^* = (w_{rev}, w_{vol}, top\_k)$ maximizing In-Sample net Sharpe ratio is **frozen** into `selected_parameters` and applied out-of-sample.

| Fold ID | Phase | Calendar Window | As-Of Cutoff | Purged Days (Rows) | Frozen Parameters $\theta^*$ | IS Net Sharpe |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **`fold_1_2025h1`** | Train (IS)<br>Test (OOS) | 2022-01-03 ~ 2024-12-31<br>2025-01-02 ~ 2025-06-30 | 2024-12-31<br>2025-06-30 | 20 days (180 rows)<br>— | $w_{rev}=1.0, w_{vol}=1.5, k=3$<br>— | 0.8182<br>— |
| **`fold_2_2025h2`** | Train (IS)<br>Test (OOS) | 2022-01-03 ~ 2025-06-30<br>2025-07-01 ~ 2025-12-31 | 2025-06-30<br>2025-12-31 | 20 days (180 rows)<br>— | $w_{rev}=1.0, w_{vol}=1.5, k=3$<br>— | 0.7205<br>— |
| **`fold_3_2026_tail`** | Train (IS)<br>Test (OOS) | 2022-01-03 ~ 2025-12-31<br>2026-01-02 ~ 2026-09-04 | 2025-12-31<br>2026-09-04 | 20 days (180 rows)<br>— | $w_{rev}=0.5, w_{vol}=1.5, k=3$<br>— | 0.9296<br>— |

---

## 4. Empirical Realization & Net Performance Matrix

### 4.1 Fold-by-Fold Performance Matrix (Net of 8 bps Friction with Terminal Liquidation)

| Metric | Fold 1 (`2025H1`) | Fold 2 (`2025H2`) | Fold 3 (`2026 Tail`) | Stitched OOS Total |
| :--- | :---: | :---: | :---: | :---: |
| **Test Sessions (Trading Days)** | **122** | **128** | **170** | **420** |
| **Test Row Count** | 1,098 | 1,152 | 1,530 | 3,780 |
| **In-Sample Spearman IC** | -0.0104 | -0.0125 | -0.0112 | — |
| **OOS Gross Return (0 bps)** | **+7.87%** | **+21.20%** | **+22.46%** | **+60.10%** |
| **OOS Net Return (8 bps)** | **+5.71%** | **+19.01%** | **+19.73%** | **+50.63%** |
| **Benchmark QQQ Return** | **+8.19%** | **+11.63%** | **+17.06%** | **+41.38%** |
| **OOS Net Excess Return** | **-2.48%** | **+7.37%** | **+2.67%** | **+9.25%** |
| **Annualized Net Volatility** | 32.38% | 19.26% | 24.53% | 25.71% |
| **Net Sharpe Ratio** | **0.5134** | **1.8762** | **1.2110** | **1.0835** (continuous) |
| **Gross Sharpe Ratio** | 0.6429 | 2.0651 | 1.3472 | 1.2057 (continuous) |
| **Maximum Drawdown** | -21.04% | -7.46% | -20.69% | **-22.36%** (continuous) |
| **Daily Win Rate** | 49.18% | 61.72% | 51.18% | 53.81% |
| **Daily Turnover Ratio** | 20.65% | 17.83% | 16.61% | 18.36% |
| **Fold Transaction Cost Drag** | 2.16% | 2.19% | 2.73% | **9.48%** (cumulative) |

### 4.2 Transaction Cost & Slippage Sensitivity Analysis
Given average daily turnover of ~18.4% (including drift adjustments, opening purchase, and terminal liquidation), transaction friction imposes an institutional drag on returns:

| Friction Tier | Model Description | Cumulative OOS Return | Net Excess over QQQ | Cost Drag vs Gross |
| :--- | :--- | :---: | :---: | :---: |
| **Tier 0: Gross (0 bps)** | Theoretical frictionless execution | **+60.10%** | +18.72% | 0.00% |
| **Tier 1: Standard (8 bps)** | 3 bps commission + 5 bps slippage | **+50.63%** | **+9.25%** | **-9.48%** |
| **Tier 2: Stress (15 bps)** | 5 bps commission + 10 bps slippage | **+42.79%** | **+1.41%** | **-17.31%** |

> **Key Finding**: Transaction costs reduce cumulative out-of-sample alpha (from +18.72% gross excess down to +9.25% net excess at standard institutional friction with terminal liquidation). Under high stress friction (15 bps), net excess is compressed to +1.41%, demonstrating that full-cycle cash accounting and turnover control are critical.

---

## 5. Cryptographic Evidence & Lineage Bindings

### 5.1 Immutable Data Slice Hashes

```json
{
  "fold_1_2025h1": {
    "train_data_hash": "7c5a5ac34b1eede25a8602e68e0ffc7400b5f594bd385422253a3bc20f35f6e7",
    "test_data_hash": "c414e3fec17ed68efa0c0400679b2c384529a04fa59502bdd077842040b5a1c6"
  },
  "fold_2_2025h2": {
    "train_data_hash": "1d4bb044f20522859abdb2a0687724eb77f3b6f9124e636ad0dda7930f99b9eb",
    "test_data_hash": "3af5d946d4a5159e78885b401b01b64dd0220204116f87b7b9077abffdecf0b4"
  },
  "fold_3_2026_tail": {
    "train_data_hash": "3d873ff616f9892d69f70f09ac879c27e577ab46460ea6377792fee01ab3705e",
    "test_data_hash": "ed1cbe911c461ce052acdb0e8196cc13152cc464516c5fa064524af1aa0016bd"
  }
}
```

### 5.2 Sealed Study Hash & Execution Source Code Digests
- **Algorithm**: Canonical UTF-8 JSON serialization $\to$ SHA-256
- **Study Hash**: `1a21b9a16b0426ff75eb64ae393ac57396cb3586d1fe68177bae69079c380002`
- **Config Hash**: `9950f2af28b11b3fb9172bbc49304b3898afa171c1f5252ecd889368ed89be36`
- **Cryptographic Code Source Digests (SHA-256)**:
  - `walkforward_pipeline`: `bf08722686c4f23ed01c46b5a62e1880408dfffc42972213582ae27cb24157f1`
  - `walkforward_contracts`: `4d6c5ee53635b67df60eed84c082dbde628fbb945c47ebf13310a099476ed233`
  - `research_data_slice`: `ae3c93cb57bf2f69f8ef0daee21746a5fddd8428c2311aa4046a97aaf67123ba`
- **Bound Experiment State**: Full `WalkForwardConfig` (study ID, market, pool, symbols, benchmark, price mode, param grid, friction parameters, fold specifications) plus exact execution source code hashes and individual fold data receipts.
- **Determinism Assertion**: Verified via automated test `test_walkforward_study_determinism` (identical digest across repeated executions) and `test_walkforward_study_hash_binds_experiment_receipt` (any config alteration invalidates digest).

---

## 6. Governance Invariants & Fail-Closed Integrity

1. **Fail-Closed Fold Integrity**:
   - Every declared fold must achieve `status: "ready"`.
   - If any fold blocks or fails, `run_walkforward_study()` strictly sets `status = "blocked"` and suppresses overall return and Sharpe publication.
2. **Research Exclusivity**:
   - `research_only: true`
   - `trade_ready: false`
   - `trade_signal: false`
3. **Zero Shadow Infrastructure**:
   - No DuckDB files, SQLite databases, or external microservices were introduced.
   - Vectorized memory computation provides full determinism and rapid execution.
4. **Code References**:
   - Pipeline Engine: [`src/research/walkforward/pipeline.py`](file:///D:/Documents/GitHub/alphaengine/src/research/walkforward/pipeline.py)
   - Data Contracts: [`src/research/walkforward/contracts.py`](file:///D:/Documents/GitHub/alphaengine/src/research/walkforward/contracts.py)
   - Test Suite: [`tests/test_walkforward_study.py`](file:///D:/Documents/GitHub/alphaengine/tests/test_walkforward_study.py)
