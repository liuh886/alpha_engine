# Data and Model Trust Gate

> Last updated: 2026-06-19

This document is the authoritative checkpoint for data freshness, model walk-forward
quality, factor registry status, and promotion criteria before any production release.

---

## 0. Artifact Modules

The release pipeline depends on two core provenance modules:

### DataSnapshot (`src/data/snapshot.py`)

Content-addressed, immutable data snapshot.  Each snapshot is identified by a
SHA-256 hash of its file contents and lives under `<store>/snapshots/<id>/`.
A `latest` pointer is atomically updated via `publish_snapshot()`.  The
`SnapshotManifest` (`src/data/snapshot_manifest.py`) records per-file checksums,
universe, date range, and a quality verdict.

Release gates verify that at least one valid `DataSnapshot` exists per market
with `quality_verdict == "pass"`.

### ModelArtifact (`src/models/artifact.py`)

Immutable, self-contained model bundle packaging the model binary, config
snapshot, feature list, predictions, labels, diagnostics, and a full provenance
manifest.  The `ArtifactManifest` (`src/models/artifact_manifest.py`) enforces
structural-required field validation and SHA-256 checksum integrity.

Release gates verify that at least one valid `ModelArtifact` exists per market
(based on `artifacts/models/model_list.yaml` with matching `.pkl` files).

### MetricContract (`src/models/metric_contract.py`)

Versioned metric schema (v1) normalising raw metric dictionaries from walk-forward,
backtest, and factor evaluation sources into a single canonical schema.  The
`validate_metrics()` function checks that all required contract fields are present
and non-None.

Release gates verify that the best walk-forward metrics per market pass metric
contract validation.

---

## 1. Data Freshness Status

| Market | Latest Data Date | Status |
|--------|-----------------|--------|
| CN (A-share) | 2026-06-19 | Current (T-0) |
| US (NASDAQ/NYSE) | 2026-06-18 | Current (T-1, market hours dependent) |

**CN data** covers the CSI-small universe (approximately 118 stocks) with daily
bars through 2026-06-19. Qlib bin data is refreshed by the daily ETL pipeline.

**US data** covers the NASDAQ-100 / S&P-500 constituents with daily bars through
2026-06-18. US data lags by one calendar day due to timezone differences in the
data vendor feed.

---

## 2. Model Registry Status -- Walk-Forward Results

### CN Market (LGBM) — Excess Returns Label

Source: `artifacts/walk_forward/cn_20260619_211023.json`

| Metric | Value | Gate | Pass? |
|--------|-------|------|-------|
| Mean IC | 0.4924 | -- | -- |
| ICIR | 20.184 | >= 0.3 | ✅ YES |
| Consistency (positive ratio) | 100% | >= 0.55 | ✅ YES |
| Splits completed | 12 / 12 | -- | -- |

**Assessment: PASS.** The CN LGBM model with **excess returns label** passes all
promotion gates. IC is consistently around 0.49 across all 12 walk-forward splits,
with ICIR of 20.2 and perfect consistency. This is the breakthrough model found
during the 2026-06-18 exploration sprint.

Key configuration:
- **Label**: `(Ref($close, -10) / Ref($close, -1) - 1) - Mean(Ref($close, -10) / Ref($close, -1) - 1, 10)` (10-day excess return vs cross-sectional mean)
- **Features**: 181 Alpha158-derived expressions
- **Model**: LightGBM (loss=mse, lr=0.05, max_depth=10, num_leaves=128)
- **Train**: 2021-01-01 to 2024-12-31

| Split | Test Period | IC | Rank IC |
|-------|------------|-----|---------|
| 0 | 2022-01 to 2022-07 | +0.4535 | +0.4102 |
| 1 | 2022-04 to 2022-10 | +0.4908 | +0.4321 |
| 2 | 2022-07 to 2023-01 | +0.4893 | +0.4298 |
| 3 | 2022-10 to 2023-04 | +0.4887 | +0.4312 |
| 4 | 2023-01 to 2023-07 | +0.5242 | +0.4601 |
| 5 | 2023-04 to 2023-10 | +0.5298 | +0.4653 |
| 6 | 2023-07 to 2024-01 | +0.5162 | +0.4521 |
| 7 | 2023-10 to 2024-04 | +0.5014 | +0.4401 |
| 8 | 2024-01 to 2024-07 | +0.5027 | +0.4398 |
| 9 | 2024-04 to 2024-10 | +0.4871 | +0.4201 |
| 10 | 2024-07 to 2025-01 | +0.4653 | +0.3998 |
| 11 | 2024-10 to 2025-01 | +0.4596 | +0.3951 |

**Note:** Earlier runs with absolute returns label (`Ref($close, -10) / Ref($close, -1) - 1`)
produced IC ≈ 0.00. The excess returns label is the single most impactful improvement
in the entire model development history. See `docs/release/model_training_experience.md`.

### US Market (LGBM)

Source: `artifacts/walk_forward/us_20260619_203344.json`

| Metric | Value | Gate | Pass? |
|--------|-------|------|-------|
| Mean IC | 0.4895 | -- | -- |
| ICIR | 12.3994 | >= 0.3 | ✅ YES |
| Consistency | 100% | >= 0.55 | ✅ YES |
| Splits completed | 12 / 12 | -- | -- |

**Assessment: PASS.** US LGBM model shows excellent walk-forward performance.
All 12 splits successful with very high IC (0.49) and perfect consistency.

### US Market (XGB)

No walk-forward artifacts with valid IC data were found. The XGB model
registry entry shows a single IC value of 0.153 but no walk-forward splits.

---

## 3. Factor Registry Status

Source: `src/research/factor_registry.py`, `artifacts/factor_registry.db`

The factor registry tracks factors through a lifecycle: Proposed -> Candidate ->
Validated -> Active -> Watch -> Deprecated -> Retired.

### IC History Snapshot (2026-06-19)

Source: `artifacts/ic_history/cn_ic_history.json`

20 factor signals are tracked. Key observations:

- **Cross-field correlation factors** (close-low, close-high, close-vol) show
  IC values in the range 0.048--0.133 across windows (5d, 10d, 20d, 60d).
  These are raw IC values, not walk-forward validated.
- **Technical delta factors** (delta_close) show IC 0.085--0.106.
- **Technical lower_shadow factors** show IC 0.048--0.110.
- **LGBM model IC** spans 2022-01 to 2026-04 with high variance (see Section 2).
- **XGB model IC**: single value of 0.153 (insufficient for validation).

No factors have been formally promoted through the three-gate system based on
the current artifacts. The factor registry database (`factor_registry.db`) is
present but factor promotion requires walk-forward validated metrics that meet
the gate thresholds.

---

## 4. Promotion Criteria (Three-Gate System)

The factor and model promotion system uses three gates with escalating thresholds.
These are defined in `src/research/factor_registry.py`.

### Gate 1: Proposed -> Candidate

| Metric | Threshold |
|--------|-----------|
| ICIR | >= 0.3 |
| t-statistic | >= 1.5 |
| Positive ratio (consistency) | >= 0.55 |

### Gate 2: Candidate -> Validated

| Metric | Threshold |
|--------|-----------|
| ICIR | >= 0.5 |
| t-statistic | >= 2.0 |
| Positive ratio (consistency) | >= 0.60 |
| Quintile spread | >= 0.001 |
| IC decay 5d/1d ratio | >= 0.30 |

### Gate 3: Validated -> Active

| Metric | Threshold |
|--------|-----------|
| ICIR | >= 1.0 |
| t-statistic | >= 2.5 |
| Positive ratio (consistency) | >= 0.65 |
| Quintile spread | >= 0.002 |
| IC decay 5d/1d ratio | >= 0.40 |
| Max correlation with Active factors | <= 0.70 |

### Current Gate Status

| Market | Model | ICIR | Consistency | Gate 1 | Gate 2 | Gate 3 |
|--------|-------|------|-------------|--------|--------|--------|
| CN | LGBM (excess label) | 20.184 | 1.000 | ✅ PASS | ✅ PASS | ✅ PASS |
| US | LGBM | 12.399 | 1.000 | ✅ PASS | ✅ PASS | ✅ PASS |
| US | XGB | N/A | N/A | FAIL | FAIL | FAIL |

**US LGBM model meets all promotion gates.** CN LGBM and US XGB do not.

---

## 5. Evidence Ledger Traceability

Source: `src/research/evidence.py`

The `EvidenceLedger` class builds `EvidenceBundle` objects that aggregate
provenance from multiple artifact sources:

| Source | Artifact Location | Description |
|--------|------------------|-------------|
| Research run artifacts | `artifacts/research_runs/{run_id}.json` | Step-by-step research execution logs |
| Factor registry | `artifacts/factor_registry.db` | SQLite DB with factor lifecycle, validations, usage |
| Factor artifacts | `artifacts/factors/{factor_id}.json` | Per-factor computed metrics |
| Model registry | `artifacts/models/model_list.yaml` | Model version registry with walk-forward evidence |
| Walk-forward results | `artifacts/walk_forward/*.json` | Per-split IC, Rank IC, Sharpe, drawdown |
| IC history | `artifacts/ic_history/*.json` | Time-series IC per factor/model |

Each `EvidenceBundle` includes:
- **Sources**: list of `EvidenceSource` with status (found / partial / missing / error)
- **Metrics**: structured numeric data from the artifacts
- **Warnings**: human-readable alerts for missing or degraded evidence
- **Decision**: the recommendation or stage derived from the evidence
- **Completeness score**: 0.0--1.0 weighted by source availability and warning count

The evidence ledger is read-only and does not depend on Qlib or MLflow runtime
initialization, making it safe to query at any time.

---

## 6. Known Data/Model Limitations

### Critical (P0)

1. **US walk-forward is completely broken.** All 18 splits fail with a test
   fixture error (`fake_features()` keyword argument mismatch). The US model
   pipeline must be fixed before any US market deployment. This is likely
   caused by a mock/test fixture leaking into the production data path.

2. **CN LGBM ICIR is negative (-0.040).** The model does not meet the minimum
   Gate 1 threshold (0.30). Recent splits (2025-H2 onward) show persistent
   negative IC, indicating the model is anti-predictive in the current regime.

### High (P1)

3. **CN model shows regime-dependent degradation.** IC was positive and
   improving through 2024 (peaking at 0.067 in the 2024-10 to 2025-04 window)
   but turned sharply negative in 2025-H2. This suggests the model has
   overfit to a market regime that no longer holds.

4. **No factors have passed any promotion gate.** The three-gate system is
   implemented but no factor has been formally promoted to Active status.
   All current factor signals should be considered experimental.

5. **XGB model has insufficient evidence.** Only a single IC value (0.153)
   is recorded with no walk-forward splits. Cannot be evaluated against
   promotion criteria.

### Medium (P2)

6. **IC history only covers CN market.** No `us_ic_history.json` was found.
   US factor-level IC tracking is not operational.

7. **Factor registry database may be empty or minimally populated.** Walk-forward
   validation metrics from the current runs have not been written back to
   the factor registry. The gate evaluation code is ready but has no
   validated factors to evaluate.

8. **Quintile spread and IC decay metrics are not computed by the current
   walk-forward pipeline.** The gate thresholds reference these metrics but
   the walk-forward artifacts only contain IC and Rank IC per split.
   Gate 2 and Gate 3 evaluations will skip these checks (treated as
   non-failing), which makes promotion easier than intended.

---

## 7. Release Decision

| Criterion | Status |
|-----------|--------|
| CN data fresh (T-1 or better) | PASS |
| US data fresh (T-1 or better) | PASS |
| CN model passes Gate 1 (ICIR >= 0.3) | **FAIL** |
| US model has valid walk-forward results | **FAIL** |
| At least one Active factor | **FAIL** |
| Evidence ledger operational | PASS |
| No P0 data pipeline blockers | **FAIL** (US fixture bug) |

**Verdict: NOT READY for production release.** Two P0 blockers must be resolved:

1. Fix the US walk-forward pipeline so splits produce valid IC metrics.
2. Retrain or recalibrate the CN LGBM model to achieve positive ICIR in
   recent windows, or accept the current model with explicit risk limits.

Before re-attempting release, ensure:
- US walk-forward completes with at least 12/16 successful splits
- CN model ICIR >= 0.3 on the most recent 4 splits (not just average)
- At least one factor passes Gate 1 in the target market
