# Gap Assessment: Design Doc v1.0 vs. Current Implementation (2026-02-11)

## 1. Executive Summary
The project has a solid foundation with Qlib integration, a functioning dashboard server, and basic SQLite metadata tracking. However, there is a significant gap between the **"Reproducible & Governed"** vision of the design doc and the current **"Script-driven"** implementation. Most missing pieces are related to formal versioning of metadata (Features, Labels, Policies) and unified主语 (ModelVersion).

---

## 2. Gap Matrix

| Domain | Feature / Capability | Status | Priority | Strategy | Gap Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Data** | Data Provenance | Minimal | P0 | Fix (B1-T3) | No persistent record of which provider was used for each ticker/batch or fallback reasons. |
| **Data** | Router Policy Versioning | Partial | P1 | Postpone | Policies exist in configs but are not versioned/referenced in Runs formally. |
| **Training** | Experiment/Run API | Partial | P0 | Fix (B1-T5) | Orchestrator handles runs, but the Dashboard API cannot yet trigger specific training jobs with full params. |
| **Training** | Feature/Label Spec Registry | Missing | P2 | Postpone | Specs are in YAML configs; no formal `FeatureSetVersion` SQLite table/registry. |
| **Model Registry**| Unified ModelVersion | Partial | P0 | Fix (B1-T4) | System currently oscillates between `run_id` (MLflow) and `model_tag`. Needs a stable `model_version_id`. |
| **Backtest** | Strategy Templates | Partial | P0 | Fix (B1-T6) | Backtests use "profiles" which are essentially templates, but they aren't formally registered as `StrategyTemplate`. |
| **Arena** | Participant Traceability | Partial | P1 | Fix (B1-T4) | Participants are linked to `run_id`, making it hard to track if a participant is a specific "Version" of a model. |
| **Reports** | Unified Export | Partial | P0 | Fix (B1-T7) | Individual scripts exist, but no unified `/api/reports/export` that handles indexing and zipping consistently. |
| **Dashboard** | Stock Terminal | Missing | P2 | Postpone | Design doc calls for a TradingView-like terminal; currently only backtest/arena charts exist. |

---

## 3. Domain Deep Dive

### 3.1 Data Layer
- **Status**: `scripts/update_data.py` works but is "fire and forget". 
- **Missing**: `data_provenance` table in SQLite. 
- **Risk**: Hard to debug why a specific backtest failed if we don't know if the data came from AkShare (clean) or EFinance (fallback, potentially messy).

### 3.2 Training & Model Registry
- **Status**: `ModelRegistryIndex` exists and `orchestrator.py` populates it.
- **Missing**: A clear distinction between a "Run" (an attempt) and a "Model Version" (a candidate for production). 
- **Risk**: Arena participants might point to a `run_id` that gets deleted during cleanup.

### 3.3 Backtest & Strategy
- **Status**: `BacktestService` is robust but relies on file-system profiles.
- **Missing**: Formalizing the `StrategyTemplate`.
- **Risk**: "Implicit" strategies make reports hard to compare (did we change the cost model or the model?).

### 3.4 Arena & Reporting
- **Status**: Arena settle works; reports are generated as HTML.
- **Missing**: Unified indexing.
- **Risk**: Reports get lost in the `reports/` folder without a database record to find them.

---

## 4. Recommended Handling for Batch B1
- **Focus**: Clear the P0 gaps in Model Registry, Provenance, and Unified APIs.
- **Postpone**: P2 items like "Stock Terminal" and "Feature Registry" to Batch B2 or later.
- **Action**: Proceed with `B1-T2` (API Contract) and `B1-T3` (Provenance) immediately.
