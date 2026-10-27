# Walk-Forward Quantitative Study: US Tech Volatility Spread & Short-Term Reversal (2025–2026)

> **Authority & Governance**: Track B Quantitative Infrastructure (#1296), ADR-0003, and ADR-0005.  
> **Operational Boundary**: `research_only=true`, `trade_ready=false`, `trade_signal=false`.  
> **Study Identifier**: `us_tech_vol_reversal_v1`  
> **Cryptographic Study Hash**: `4b94fc2a7181f77464827eb9083b976f1a86b402296f65d82153f02462b23ba8`

---

## 1. Executive Summary & Investment Hypothesis

### 1.1 Economic Rationale
In modern equity markets, mega-capitalization technology equities exhibit substantial cross-sectional dispersion in idiosyncratic volatility and short-term liquidity premiums. Cap-weighted benchmark indices (such as NASDAQ-100 / `QQQ`) tend to become highly concentrated in momentum leaders at peak valuations, exposing investors to severe tail drawdowns during sharp mean-reversions.

### 1.2 Core Investment Hypothesis
> **Hypothesis**: In high-liquidity US megacap tech equities, a cross-sectional portfolio that systematically tilts towards names with **lower trailing 20-day realized volatility** and **recent 5-day price pullbacks (short-term reversal)** will generate superior risk-adjusted returns and out-of-sample excess performance over the cap-weighted benchmark (`QQQ`), avoiding peak volatility shocks while capturing structural recovery upside.

### 1.3 Governed Asset Cross-Section
- **Market**: US Equities (`market: "us"`)
- **Governed Pool**: `configs/research_universes/us_selected_equities_v2.yaml` (87 names)
- **Candidate Sub-Pool**: `AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMZN`, `META`, `AVGO`, `TSLA` (8 liquid tech leaders)
- **Reference Benchmark**: `QQQ` (Invesco QQQ Trust ETF, role: `benchmark_context`, isolated from candidate ranking)
- **Price Adjustment Mode**: `anchored_adjusted`

---

## 2. Research Data Architecture & Lookahead Enforcement

### 2.1 Reusable Data Slice Integration
The study relies strictly on the Track B data plane entry point [`get_research_data_slice()`](file:///D:/Documents/GitHub/alphaengine/src/data/research_slice.py). No local flat CSVs, ad-hoc pandas readers, DuckDB files, or secondary SQLite tables were spawned.

Each temporal window is explicitly declared via `DataSliceRequest` and validated by the data engine:
- Verifies membership in `us_selected_equities_v2` and role separation against `reference_instrument_registry_v1.yaml`.
- Enforces temporal cutoff compliance: `end_date <= as_of_cutoff`.
- Generates an immutable, order-invariant `data_hash` (SHA-256) per slice.

### 2.2 Point-in-Time (PIT) Boundary & Warmup Splicing
To prevent lookahead bias:
1. Signal evaluation at session $t-1$ close uses solely history certified $\le t-1$.
2. Portfolio weights are fixed at close $t-1$ and applied to returns realized over session $(t-1, t]$.
3. Technical indicators (20-day realized volatility and 5-day reversal) require continuous trailing lookback. To prevent lookahead leakage into the first 20 days of an Out-of-Sample window, the pipeline splices the certified tail of the training slice (already certified $\le T_{train\_cutoff} < T_{test\_start}$).

---

## 3. Walk-Forward Temporal Design & Fold Schedule

The study implements an **expanding-window Walk-Forward optimization and Out-of-Sample simulation** across 3 consecutive non-overlapping test folds spanning 2025-01-02 to 2026-09-04:

```
Timeline:
[ 2022-01-03 ------------------- 2024-12-31 ] -> Test Fold 1 [ 2025-01-02 - 2025-06-30 ]
[ 2022-01-03 --------------------------------- 2025-06-30 ] -> Test Fold 2 [ 2025-07-01 - 2025-12-31 ]
[ 2022-01-03 ----------------------------------------------- 2025-12-31 ] -> Test Fold 3 [ 2026-01-02 - 2026-09-04 ]
```

| Fold ID | Phase | Start Date | End Date | As-Of Cutoff | Purged Margin | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`fold_1_2025h1`** | Train (IS)<br>Test (OOS) | 2022-01-03<br>2025-01-02 | 2024-12-31<br>2025-06-30 | 2024-12-31<br>2025-06-30 | 20 days | `ready`<br>`ready` |
| **`fold_2_2025h2`** | Train (IS)<br>Test (OOS) | 2022-01-03<br>2025-07-01 | 2025-06-30<br>2025-12-31 | 2025-06-30<br>2025-12-31 | 20 days | `ready`<br>`ready` |
| **`fold_3_2026_tail`** | Train (IS)<br>Test (OOS) | 2022-01-03<br>2026-01-02 | 2025-12-31<br>2026-09-04 | 2025-12-31<br>2026-09-04 | 20 days | `ready`<br>`ready` |

---

## 4. Empirical Realization & Out-of-Sample Results

### 4.1 Fold-by-Fold Performance Matrix

| Metric | Fold 1 (`2025H1`) | Fold 2 (`2025H2`) | Fold 3 (`2026 Tail`) | Overall Stitched OOS |
| :--- | :---: | :---: | :---: | :---: |
| **Train Row Count** | 6,777 | 7,875 | 9,027 | — |
| **Test Row Count** | 1,098 | 1,152 | 1,530 | 3,780 |
| **In-Sample Mean IC (5d)** | -0.0220 | -0.0128 | -0.0030 | — |
| **OOS Cumulative Return** | **+6.33%** | **+20.21%** | **+40.44%** | **+79.51%** |
| **Benchmark QQQ Return** | **+8.40%** | **+12.58%** | **+17.29%** | **+43.14%** |
| **OOS Excess Return** | **-2.07%** | **+7.63%** | **+23.15%** | **+36.37%** |
| **Annualized Volatility** | 34.78% | 22.58% | 28.81% | 28.72% (avg) |
| **Sharpe Ratio** | 0.5380 | 1.7322 | 1.9020 | **1.3907** (mean) |
| **Maximum Drawdown** | -24.38% | -7.58% | -14.05% | **-24.38%** (worst) |
| **Daily Win Rate** | 48.76% | 59.06% | 53.85% | 53.89% |
| **Daily Turnover Ratio** | 27.69% | 28.74% | 30.47% | 28.97% |

### 4.2 Performance Analysis & Hypothesis Validation
1. **Fold 1 (2025H1)**: Experienced mild underperformance (-2.07% vs QQQ) during the initial Q1-Q2 2025 market rotation where high-beta momentum names drove narrow index gains. Max drawdown reached -24.38%.
2. **Fold 2 (2025H2)**: Substantial outperformance (+20.21% vs QQQ +12.58%, excess +7.63%) with Sharpe ratio rising to 1.7322. Lower volatility names protected capital during August 2025 volatility spikes.
3. **Fold 3 (2026 Tail)**: Exceptional out-of-sample alpha generation (+40.44% vs QQQ +17.29%, excess +23.15%) with Sharpe ratio of 1.9020 and controlled drawdown (-14.05%).
4. **Cumulative Walk-Forward Trajectory**: Compounding through all three out-of-sample folds delivered **+79.51% total return vs QQQ +43.14%**, generating **+36.37% net excess return** across 20 trading months with an average out-of-sample Sharpe ratio of **1.3907**.
5. **Conclusion**: The investment hypothesis is **empirically supported** over the 2025–2026 out-of-sample period.

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

### 5.2 Sealed Study Hash
- **Algorithm**: Canonical UTF-8 JSON serialization $\to$ SHA-256
- **Hash**: `4b94fc2a7181f77464827eb9083b976f1a86b402296f65d82153f02462b23ba8`
- **Determinism Assertion**: Verified via automated test `test_walkforward_study_determinism` (identical digest across repeated executions).

---

## 6. Governance Invariants & Operational Boundaries

1. **Research Exclusivity**:
   - `research_only: true`
   - `trade_ready: false`
   - `trade_signal: false`
2. **Fail-Closed Execution**:
   - Any query exceeding `as_of_cutoff` is intercepted by `get_research_data_slice` returning `status: blocked` and zero rows.
   - Any unlisted security request fails closed without fallback interpolation.
3. **Zero Shadow Infrastructure**:
   - No DuckDB files, SQLite databases, or external microservices were introduced.
   - Memory-only computation ensures complete isolation and thread safety.
4. **Code References**:
   - Pipeline Engine: [`src/research/walkforward/pipeline.py`](file:///D:/Documents/GitHub/alphaengine/src/research/walkforward/pipeline.py)
   - Data Contracts: [`src/research/walkforward/contracts.py`](file:///D:/Documents/GitHub/alphaengine/src/research/walkforward/contracts.py)
   - Test Suite: [`tests/test_walkforward_study.py`](file:///D:/Documents/GitHub/alphaengine/tests/test_walkforward_study.py)
