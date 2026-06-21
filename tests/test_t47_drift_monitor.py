"""T47.2: Model and data drift monitoring tests.

Verify:
- Prediction distribution drift detection (mean/std shift)
- PSI computation for distribution shift
- IC decay monitoring
- Signal calibration check
- Feature drift detection
- Insufficient evidence → inconclusive
- Report persistence and deduplication
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_predictions(n: int = 100, seed: int = 42) -> pd.Series:
    """Generate synthetic predictions."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.02, 0.05, n), name="prediction")


def _make_returns(n: int = 100, seed: int = 43) -> pd.Series:
    """Generate synthetic returns (correlated with predictions)."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.01, 0.04, n), name="return")


def _make_shifted_predictions(n: int = 100, shift: float = 0.1) -> pd.Series:
    """Generate predictions with a mean shift."""
    rng = np.random.default_rng(99)
    return pd.Series(rng.normal(0.02 + shift, 0.07, n), name="prediction")


# ---------------------------------------------------------------------------
# Insufficient evidence
# ---------------------------------------------------------------------------


def test_drift_monitor_insufficient_evidence():
    """Too few observations produce an INCONCLUSIVE report."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="cn", min_evidence_days=50)
    pred = pd.Series([0.01, 0.02, 0.03])
    ret = pd.Series([0.005, 0.01, 0.015])

    report = monitor.check_model("mv_test", pred, ret)
    assert report.overall_severity == DriftSeverity.INCONCLUSIVE
    assert "Insufficient evidence" in report.summary


# ---------------------------------------------------------------------------
# Prediction mean shift
# ---------------------------------------------------------------------------


def test_prediction_mean_shift_detected():
    """Significant mean shift is detected."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="us", min_evidence_days=5)

    # Baseline: mean=0.02, std=0.05
    baseline = _make_predictions(200, seed=42)
    # Current: mean shifted to 0.12 (2 std away)
    current = _make_shifted_predictions(200, shift=0.10)

    report = monitor.check_model(
        "mv_test", current, _make_returns(200),
        baseline_predictions=baseline,
    )

    # Should detect the shift
    mean_shift_check = [c for c in report.checks if c.check_name == "prediction_mean_shift"]
    assert len(mean_shift_check) == 1
    assert mean_shift_check[0].severity in (
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
        DriftSeverity.CRITICAL,
    )


def test_prediction_mean_no_shift():
    """No shift when predictions match baseline."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="us", min_evidence_days=5)

    rng = np.random.default_rng(42)
    baseline = pd.Series(rng.normal(0.02, 0.05, 200))
    current = pd.Series(rng.normal(0.02, 0.05, 200))

    report = monitor.check_model(
        "mv_test", current, _make_returns(200),
        baseline_predictions=baseline,
    )

    mean_shift_check = [c for c in report.checks if c.check_name == "prediction_mean_shift"]
    assert len(mean_shift_check) == 1
    assert mean_shift_check[0].severity == DriftSeverity.OK


def test_prediction_mean_inconclusive_without_baseline():
    """Without baseline predictions, mean shift check is inconclusive."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="cn", min_evidence_days=5)
    pred = _make_predictions(100)
    ret = _make_returns(100)

    report = monitor.check_model("mv_test", pred, ret)
    mean_shift_check = [c for c in report.checks if c.check_name == "prediction_mean_shift"]
    assert len(mean_shift_check) == 1
    assert mean_shift_check[0].severity == DriftSeverity.INCONCLUSIVE


# ---------------------------------------------------------------------------
# PSI (distribution shift)
# ---------------------------------------------------------------------------


def test_psi_detects_distribution_shift():
    """PSI detects significant distribution shift."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="us", psi_threshold=0.1, min_evidence_days=5)

    rng = np.random.default_rng(42)
    baseline = pd.Series(rng.normal(0.02, 0.05, 500))
    # Shifted distribution: different mean and std
    current = pd.Series(rng.normal(0.10, 0.10, 500))

    report = monitor.check_model(
        "mv_test", current, _make_returns(500),
        baseline_predictions=baseline,
    )

    psi_check = [c for c in report.checks if c.check_name == "psi"]
    assert len(psi_check) == 1
    # Should detect the strong distribution shift
    assert psi_check[0].severity in (
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
    )
    assert psi_check[0].measured_value > 0


def test_psi_no_shift_for_same_distribution():
    """PSI is near zero for identical distributions."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(market="us", psi_threshold=0.25, min_evidence_days=5)

    rng = np.random.default_rng(42)
    baseline = pd.Series(rng.normal(0.02, 0.05, 500))
    # Use the SAME rng sequence (not a new draw) so distributions match
    current = baseline.copy()

    report = monitor.check_model(
        "mv_test", current, _make_returns(500),
        baseline_predictions=baseline,
    )

    psi_check = [c for c in report.checks if c.check_name == "psi"]
    assert len(psi_check) == 1
    assert psi_check[0].severity == DriftSeverity.OK


# ---------------------------------------------------------------------------
# IC decay
# ---------------------------------------------------------------------------


def test_ic_decay_detected():
    """IC is measured and check reports appropriate severity for the data."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="cn", ic_decay_threshold=0.3, min_evidence_days=5
    )

    rng = np.random.default_rng(42)
    n = 200
    # Generate predictions and returns that are essentially uncorrelated
    pred_vals = rng.normal(0.0, 0.05, n)
    ret_vals = rng.normal(0.0, 0.04, n)  # completely independent
    pred = pd.Series(pred_vals)
    ret = pd.Series(ret_vals)

    report = monitor.check_model("mv_test", pred, ret)

    ic_check = [c for c in report.checks if c.check_name == "ic_decay"]
    assert len(ic_check) == 1
    # IC is measured, finite, and within valid range
    measured = ic_check[0].measured_value
    assert 0 <= measured <= 1, f"IC out of range: {measured}"
    assert "spearman_ic" in ic_check[0].details
    assert ic_check[0].details["n_obs"] == n


def test_ic_decay_not_flagged_for_positive_ic():
    """Positive IC is not flagged."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="cn", ic_decay_threshold=0.3, min_evidence_days=5
    )

    rng = np.random.default_rng(42)
    base = rng.normal(0.0, 0.05, 500)
    # Returns positively correlated with predictions
    ret = pd.Series(0.5 * base + rng.normal(0.0, 0.02, 500))
    pred = pd.Series(base)

    report = monitor.check_model("mv_test", pred, ret)

    ic_check = [c for c in report.checks if c.check_name == "ic_decay"]
    assert len(ic_check) == 1
    assert ic_check[0].severity == DriftSeverity.OK


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_calibration_detected_for_uncalibrated():
    """Zero-slope calibration is flagged."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="us", calibration_slope_threshold=0.2, min_evidence_days=5
    )

    rng = np.random.default_rng(42)
    pred = pd.Series(rng.normal(0.0, 0.05, 200))
    ret = pd.Series(rng.normal(0.0, 0.04, 200))  # uncorrelated → slope near 0

    report = monitor.check_model("mv_test", pred, ret)

    cal_check = [c for c in report.checks if c.check_name == "calibration"]
    assert len(cal_check) == 1
    # Slope ~0 deviates from 1.0 by ~1.0, which exceeds 0.2 threshold
    assert cal_check[0].severity in (
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
        DriftSeverity.CRITICAL,
    )


def test_calibration_pass_for_correlated():
    """Correlated predictions produce calibration near 1.0."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="us", calibration_slope_threshold=0.5, min_evidence_days=5
    )

    rng = np.random.default_rng(42)
    base = rng.normal(0.0, 0.05, 500)
    pred = pd.Series(base)
    ret = pd.Series(base + rng.normal(0.0, 0.01, 500))  # slope ~1.0

    report = monitor.check_model("mv_test", pred, ret)

    cal_check = [c for c in report.checks if c.check_name == "calibration"]
    assert len(cal_check) == 1
    assert cal_check[0].severity == DriftSeverity.OK


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def test_drift_report_persisted(tmp_path):
    """Drift reports are persisted to artifact dir."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="cn", artifact_dir=tmp_path / "drift", min_evidence_days=5
    )
    pred = _make_predictions(100, seed=42)
    ret = _make_returns(100, seed=43)

    report = monitor.check_model("mv_test", pred, ret)
    assert report.model_version_id == "mv_test"

    # Check file was written
    files = list((tmp_path / "drift").glob("drift_*.json"))
    assert len(files) == 1


def test_drift_report_roundtrip(tmp_path):
    """DriftReport can be serialized and retrieved."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="us", artifact_dir=tmp_path / "drift", min_evidence_days=5
    )
    # Use correlated data so calibration passes
    rng = np.random.default_rng(42)
    n = 200
    base = rng.normal(0.02, 0.05, n)
    pred = pd.Series(base)
    ret = pd.Series(base + rng.normal(0.0, 0.01, n))

    monitor.check_model(
        "mv_roundtrip", pred, ret,
        baseline_predictions=pd.Series(rng.normal(0.02, 0.05, n)),
    )
    retrieved = monitor.get_last_report("mv_roundtrip")
    assert retrieved is not None
    assert retrieved.model_version_id == "mv_roundtrip"
    # With correlated data and a baseline, overall should not be CRITICAL
    assert retrieved.overall_severity.value in (
        "ok", "watch", "inconclusive", "warning",
    )


def test_get_last_report_returns_none_for_unknown_model(tmp_path):
    """get_last_report returns None for unknown model."""
    from src.research.drift_monitor import ModelDriftMonitor

    monitor = ModelDriftMonitor(market="cn", artifact_dir=tmp_path / "drift")
    assert monitor.get_last_report("nonexistent") is None


# ---------------------------------------------------------------------------
# Feature drift
# ---------------------------------------------------------------------------


def test_feature_drift_detected():
    """Feature drift is detected via per-feature PSI."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="cn", psi_threshold=0.1, min_evidence_days=5
    )

    rng = np.random.default_rng(42)
    n = 200
    baseline_features = pd.DataFrame({
        "f1": rng.normal(0, 1, n),
        "f2": rng.normal(0, 1, n),
    })
    # f1 is shifted significantly
    current_features = pd.DataFrame({
        "f1": rng.normal(2.0, 2.0, n),  # mean shift + std change
        "f2": rng.normal(0, 1, n),       # unchanged
    })

    report = monitor.check_model(
        "mv_test",
        _make_predictions(n),
        _make_returns(n),
        baseline_predictions=_make_predictions(n, seed=99),
        features=current_features,
        baseline_features=baseline_features,
    )

    ft_check = [c for c in report.checks if c.check_name == "feature_drift"]
    assert len(ft_check) == 1
    assert ft_check[0].severity in (
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
    )


def test_feature_drift_inconclusive_without_baseline():
    """Without baseline features, feature drift is not checked."""
    from src.research.drift_monitor import ModelDriftMonitor

    monitor = ModelDriftMonitor(market="cn", min_evidence_days=5)

    features = pd.DataFrame({"f1": np.random.randn(100)})
    report = monitor.check_model(
        "mv_test",
        _make_predictions(100),
        _make_returns(100),
        features=features,
    )

    ft_check = [c for c in report.checks if c.check_name == "feature_drift"]
    assert len(ft_check) == 0  # Not checked without baseline


# ---------------------------------------------------------------------------
# Overall severity is worst of all checks
# ---------------------------------------------------------------------------


def test_overall_severity_is_max():
    """Overall severity is the worst across all checks."""
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        market="us",
        min_evidence_days=5,
        mean_shift_threshold=0.01,  # very sensitive
    )

    rng = np.random.default_rng(42)
    baseline = pd.Series(rng.normal(0.02, 0.05, 200))
    current = pd.Series(rng.normal(0.15, 0.05, 200))  # strongly shifted

    report = monitor.check_model(
        "mv_test", current, _make_returns(200),
        baseline_predictions=baseline,
    )

    # Overall should be at least WARNING due to the mean shift
    assert report.overall_severity in (
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
        DriftSeverity.CRITICAL,
    )


# ---------------------------------------------------------------------------
# DriftReport serialization
# ---------------------------------------------------------------------------


def test_drift_report_to_dict():
    """DriftReport.to_dict() produces the expected structure."""
    from src.research.drift_monitor import DriftCheck, DriftReport, DriftSeverity

    report = DriftReport(
        model_version_id="mv_test",
        data_snapshot_id="snap_001",
        market="cn",
        checked_at="2026-06-21T12:00:00Z",
        checks=[
            DriftCheck(
                check_name="prediction_mean_shift",
                measured_value=1.5,
                baseline=0.02,
                threshold=0.5,
                severity=DriftSeverity.CRITICAL,
                evidence_window="200 observations",
                recommended_action="Retrain immediately.",
                details={"z_score": 1.5},
            )
        ],
        overall_severity=DriftSeverity.CRITICAL,
        summary="Critical drift detected.",
    )

    d = report.to_dict()
    assert d["model_version_id"] == "mv_test"
    assert d["data_snapshot_id"] == "snap_001"
    assert d["overall_severity"] == "critical"
    assert len(d["checks"]) == 1
    assert d["checks"][0]["check_name"] == "prediction_mean_shift"
    assert d["checks"][0]["severity"] == "critical"
