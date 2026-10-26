# Investment Research Infrastructure: Data Product, Consumer & Rights Lineage Matrix (RI-01)

> **Authority**: PR #1296 (Track B / Long-Term Platform Umbrella)
> **Milestone**: Wave B0 (Empirical Data Product & Consumer Lineage Inventory)
> **Status**: **B0 REVISED — EMPIRICAL EVIDENCE MATRIX (FOR OWNER REVIEW)**
> **Scope**: Enumerates all governed data products, empirical dataset metrics, authoritative stores, consumers, rights boundaries, and blocker statuses across US and CN markets.
> **Integrity Rule**: Target universe candidate sizes (US 87, CN 130) must never be conflated with completed data coverage. All missing symbols, byte counts, and manifest hashes are directly bound to `data/research/model_data_bundle_v1/`.

---

## 1. Candidate Universes & Reference Instruments

| Asset Class | Identifier / Config Path | Target Candidates | Role | Governance Rule | Authoritative Storage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **US Candidate Pool** | `configs/research_universes/us_selected_equities_v2.yaml` | 87 equities | Cross-sectional selection pool | Market-isolated, survivorship-disciplined | `configs/pools/selected_pool_registry_v1.yaml` |
| **CN Candidate Pool** | `configs/research_universes/cn_selected_equities_v3.yaml` | 130 equities | Cross-sectional selection pool | Market-isolated, tradability-bounded | `configs/pools/selected_pool_registry_v1.yaml` |
| **US Reference ETFs** | `QQQ`, `QQQI`, `TQQQ` | 3 ETFs | Regime context & strategy portfolio | Distinct from equity cross-section | `configs/pools/reference_instrument_registry_v1.yaml` |
| **CN Reference ETFs/Indices** | `515180.SH`, `000300.SH` | 1 ETF, 1 Index | Benchmark & defensive allocation | Strict ETF vs Index role separation | `configs/pools/reference_instrument_registry_v1.yaml` |

---

## 2. Empirical Data Product Inventory & Coverage Audit

The authoritative evidence below is audited from `data/research/model_data_bundle_v1/data-components.json` (Bundle SHA `c07491e8edb6be2b40188aa888dbc98acdf087dd51aa0c0a4b0427fde2bf8e7c`):

| Data Product ID | Provider(s) | Actual Coverage | Coverage % | Date Range ($T_{first} \to T_{last}$) | Data Size / Records | Specific Missing / Inapplicable Symbols | Manifest Path & Hash | Readiness Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`fundamentals.cn_selected_equities_v3`** | `AKSHARE_SINA_FINANCIAL_REPORT_CNINFO_TIME` | **127 / 130** | **97.69%** | `2021-02-03` $\to$ `2026-09-01` (cutoff `2026-09-04`) | `events.jsonl`<br>(17.34 MB, SHA `1cf3eaf8...`) | **3 missing**: `301309` (万达轴承), `301666` (爱迪特), `600276` (恒瑞医药 - vendor report gap) | `sources/cn_events/fundamentals/component_manifest.json`<br>(`3f31cc5e...`) | **PARTIAL** |
| **`fundamentals.us_selected_equities_v2`** | `SEC_COMPANYFACTS` | **86 / 87** | **98.85%** | `2009-06-04` $\to$ `2026-09-30` (cutoff `2026-09-30`) | `events.jsonl`<br>(59.27 MB, SHA `a8581c0f...`) | **1 missing**: `SBGSY` (Schneider Electric ADR, SEC CIK cross-reference unmapped) | `sources/us_events/fundamentals/component_manifest.json`<br>(`45a82fea...`) | **PARTIAL** |
| **`corporate_actions.cn_selected_equities_v3`** | `AKSHARE_EASTMONEY_DIVIDEND` | **130 / 130** | **100.0%** | `1991-03-03` $\to$ `2026-09-03` (cutoff `2026-09-04`) | `events.jsonl`<br>(2.70 MB, SHA `5602eca9...`) | 0 missing (128 ready, 2 no event observed) | `sources/cn_events/corporate_actions/component_manifest.json`<br>(`3941c5da...`) | **READY** |
| **`corporate_actions.us_selected_equities_v2`** | `YFINANCE_ACTIONS` | **87 / 87** | **100.0%** | `1962-02-06` $\to$ `2026-09-30` (cutoff `2026-09-30`) | `events.jsonl`<br>(3.25 MB, SHA `c596b574...`) | 0 missing (65 ready, 22 no event observed) | `sources/us_events/corporate_actions/component_manifest.json`<br>(`97bf40cd...`) | **READY** |
| **`prices.cn_selected_equities_v3`** | `AKSHARE`, `AKSHARE_SINA`, `TENCENT_QFQ_HISTORY` | **130 / 130** | **100.0%** | `2026-04-16` $\to$ `2026-10-23` (cutoff `2026-10-23`) | `data/csv_source/*.csv` | 0 missing | `components/cn-selected-pool-prices.json`<br>(`9ec31d23...`) | **READY** |
| **`prices.us_selected_equities_v2`** | `YFINANCE` | **87 / 87** | **100.0%** | `2025-06-05` $\to$ `2026-10-23` (cutoff `2026-10-23`) | `data/csv_source/*.csv` | 0 missing | `components/us-selected-pool-prices.json` | **READY** |
| **`factors.qlib_alpha158.panel.cn.v1`** | `QLIB_PROVIDER` | **129 / 130** | **99.23%** | `2021-01-01` $\to$ `2026-09-04` (cutoff `2026-09-04`) | Compact binary array / panel manifest | **1 inapplicable**: `301666` (newly listed, insufficient historical bars for 158 features) | `sources/cn_alpha158/alpha158/factor_panel_manifest.json`<br>(`ca2f316d...`) | **PARTIAL** |
| **`rdi_research_events`** | Local RDI Engine | **Historical** | Scoped | Horizons: 7 / 14 / 28 sessions | `docs/evidence/ashare_rdi_phase2/` | Source family uncertified; status explicitly BLOCKED | `docs/evidence/ashare_rdi_phase2/` | **BLOCKED** |

---

## 3. Data Rights, Licensing & Redistribution Boundaries

| Data Family | Upstream Sources | Credential / API Env | Redistribution Rights & Restrictions | Governing Architecture Rule | Primary Authoritative Consumer |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **US Equities & ETFs Daily OHLCV** | Yahoo Finance (via `yfinance_adapter`) | None (Public Endpoint) | Personal quantitative research only; bulk redistribution prohibited | Yahoo research contract (ADR-0003) | `us_x1_3`, US Research Backtests |
| **CN Equities Daily OHLCV + Factors** | Tushare Pro (Primary), Akshare Sina (Fallback), Tencent (Fallback) | `TUSHARE_TOKEN` | Token permissions govern; internal research caching allowed, raw commercial resale prohibited | Anchored QFQ price basis (`ADR-0004`) | `cn_27_v1_3`, `cn_x1_2`, CN Research Backtests |
| **US Professional Reference Bundle** | Tiingo API (Authorized professional) | `TIINGO_API_TOKEN` | Commercial license limits raw export; licensed for internal strategy execution verification | Reference instrument isolation | `qqqi_qqq_tqqq_v4_3` Reference Evaluation |
| **US SEC Point-in-Time Fundamentals** | SEC EDGAR `companyfacts.zip` | None (Public Government API) | Public domain US government filings; automated rate limits strictly observed | SEC CIK mapping & lag rules | Multi-factor models, `us_selected_price_plus_fundamentals_v1` |
| **CN Financial Reports & Announcements** | CNINFO / Eastmoney (via `akshare`) | None (Public Financial Disclosure) | Public Chinese financial disclosure; research caching only | Point-in-time disclosure timestamps | Multi-factor models, `cn_selected_price_plus_fundamentals_v1` |
| **BYD Canonical Snapshot** | Sealed Historical Snapshot + Prospective Shadow | None (Sealed Repository Artifact) | Immutable repository evidence; no external credential required | Frozen contract `#282` | `byd_v1_3_recovery_event_low_vol_confirmation_v1` |

---

## 4. Consumer Lineage Map

```mermaid
flowchart TD
  subgraph Data_Products [Governed Data Products (Empirical Status)]
    PRICES_READY["Market Prices (100% US87 / 100% CN130) [READY]"]
    CORP_READY["Corporate Actions (100% US87 / 100% CN130) [READY]"]
    FUND_PARTIAL["PIT Fundamentals (86/87 US, 127/130 CN) [PARTIAL]"]
    ALPHA_PARTIAL["Alpha158 Factor Panel (129/130 CN) [PARTIAL]"]
    RDI_BLOCKED["RDI Research Readiness [BLOCKED]"]
  end

  subgraph Consumers [Authoritative Consumers]
    CONSOLE["Strategy Console: 4 Active Strategies [OPERATIONAL]"]
    REPLAY["Local Replay & Verification CLI [OPERATIONAL]"]
    REFRESH["Daily Formal Backtest Refresh [OPERATIONAL]"]
    TRAIN_READY["Price-Only Training Profiles [READY]"]
    TRAIN_BLOCKED["Fundamentals/Alpha158 Profiles (us_selected_alpha158_v1) [BLOCKED]"]
  end

  PRICES_READY --> REFRESH
  CORP_READY --> PRICES_READY
  PRICES_READY --> REPLAY
  REFRESH --> CONSOLE

  PRICES_READY --> TRAIN_READY
  FUND_PARTIAL --> TRAIN_BLOCKED
  ALPHA_PARTIAL --> TRAIN_BLOCKED
  RDI_BLOCKED -.-> CONSOLE
```

---

## 5. Provenance & Research Limits

1. **Strict Candidate Pool Separation**:
   - The US Candidate Pool (87) and CN Candidate Pool (130) define the fixed evaluation cross-section.
   - Partial fundamental coverage (86/87 US, 127/130 CN) explicitly blocks the corresponding combined training profiles (`us_small_pool_price_plus_fundamentals_v1`, `us_selected_alpha158_v1`), strictly enforcing fail-closed governance.
2. **No Forward-Filling / Zero-Substitution**:
   - Unavailable fundamental statements are recorded as `missing` (`301309`, `301666`, `600276`, `SBGSY`).
   - Forward-filling missing statements or imputing zeros is strictly prohibited by PIT rules.
3. **Research-Only Boundary**:
   - All dataset exports and derived factor matrices retain `research_only=true` and `trade_ready=false`.
