"""T47.2 model drift monitor statistical-integrity tests."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def _dated_series(
    n: int = 100,
    *,
    seed: int = 42,
    mean: float = 0.02,
    std: float = 0.05,
) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-01-02", periods=n, name="datetime")
    return pd.Series(rng.normal(mean, std, n), index=index, name="prediction")


def _panel(
    days: int = 40,
    symbols: int = 30,
    *,
    seed: int = 42,
    relation: float = 1.0,
    noise: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-01-02", periods=days, name="datetime")
    columns = [f"S{i:03d}" for i in range(symbols)]
    pred = pd.DataFrame(
        rng.normal(0.0, 1.0, (days, symbols)),
        index=index,
        columns=columns,
    )
    realized = relation * pred + pd.DataFrame(
        rng.normal(0.0, noise, (days, symbols)),
        index=index,
        columns=columns,
    )
    return pred, realized


def _check(report, name: str):
    matches = [check for check in report.checks if check.check_name == name]
    assert len(matches) == 1
    return matches[0]


def test_insufficient_evidence_counts_trading_days_not_panel_rows():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(min_evidence_days=20, min_cross_section_size=20)
    pred, realized = _panel(days=1, symbols=130)

    report = monitor.check_model("mv_one_day", pred, realized)

    assert report.overall_severity == DriftSeverity.INCONCLUSIVE
    assert report.checks == []
    assert "1 trading days" in report.summary


def test_prediction_mean_shift_detected_with_dated_evidence():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(min_evidence_days=20)
    baseline = _dated_series(100, seed=1, mean=0.02, std=0.05)
    current = _dated_series(100, seed=2, mean=0.14, std=0.05)
    realized = _dated_series(100, seed=3, mean=0.01, std=0.04)

    report = monitor.check_model(
        "mv_mean_shift",
        current,
        realized,
        baseline_predictions=baseline,
    )

    assert _check(report, "prediction_mean_shift").severity in {
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
        DriftSeverity.CRITICAL,
    }


def test_prediction_mean_and_std_are_inconclusive_without_baseline():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(min_evidence_days=20)
    current = _dated_series(100, seed=4)
    realized = _dated_series(100, seed=5)

    report = monitor.check_model("mv_no_baseline", current, realized)

    assert _check(report, "prediction_mean_shift").severity == DriftSeverity.INCONCLUSIVE
    assert _check(report, "prediction_std_shift").severity == DriftSeverity.INCONCLUSIVE
    assert _check(report, "psi").severity == DriftSeverity.INCONCLUSIVE
    assert report.overall_severity == DriftSeverity.INCONCLUSIVE
    assert "inconclusive" in report.summary


def test_psi_detects_shift_using_baseline_quantile_probability_bins():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(psi_threshold=0.1, min_evidence_days=20)
    baseline = _dated_series(300, seed=6, mean=0.0, std=1.0)
    current = _dated_series(300, seed=7, mean=2.0, std=1.4)
    realized = _dated_series(300, seed=8)

    report = monitor.check_model(
        "mv_psi",
        current,
        realized,
        baseline_predictions=baseline,
    )

    psi = _check(report, "psi")
    assert psi.severity in {DriftSeverity.WATCH, DriftSeverity.WARNING}
    assert psi.measured_value > 0.1
    assert psi.details["method"] == "baseline_quantile_probability_bins"


def test_psi_is_near_zero_for_identical_distribution():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(psi_threshold=0.25, min_evidence_days=20)
    baseline = _dated_series(300, seed=9, mean=0.0, std=1.0)
    realized = _dated_series(300, seed=10)

    report = monitor.check_model(
        "mv_psi_same",
        baseline.copy(),
        realized,
        baseline_predictions=baseline,
    )

    psi = _check(report, "psi")
    assert psi.severity == DriftSeverity.OK
    assert psi.measured_value < 1e-6


def test_ic_decay_uses_daily_cross_sectional_rank_ic():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        ic_decay_threshold=0.3,
    )
    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=11)
    current_pred, current_ret = _panel(days=40, symbols=30, seed=12)

    report = monitor.check_model(
        "mv_rank_ok",
        current_pred,
        current_ret,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    ic = _check(report, "ic_decay")
    assert ic.severity == DriftSeverity.OK
    assert ic.details["n_dates"] == 40
    assert ic.details["baseline_n_dates"] == 40
    assert ic.details["mean_rank_ic"] > 0.9
    assert ic.details["baseline_mean_rank_ic"] > 0.9


def test_global_spearman_market_level_trap_does_not_pass_rank_ic():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    days = 40
    symbols = 30
    index = pd.bdate_range("2025-01-02", periods=days, name="datetime")
    columns = [f"S{i:03d}" for i in range(symbols)]
    rng = np.random.default_rng(13)

    day_level = np.arange(days, dtype=float)[:, None] * 20.0
    current_pred = pd.DataFrame(
        day_level + rng.normal(0.0, 1.0, (days, symbols)),
        index=index,
        columns=columns,
    )
    current_ret = pd.DataFrame(
        day_level + rng.normal(0.0, 1.0, (days, symbols)),
        index=index,
        columns=columns,
    )
    global_spearman = current_pred.stack().corr(current_ret.stack(), method="spearman")
    assert global_spearman > 0.95

    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=14)
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        ic_decay_threshold=0.3,
    )
    report = monitor.check_model(
        "mv_global_trap",
        current_pred,
        current_ret,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    ic = _check(report, "ic_decay")
    assert ic.severity in {
        DriftSeverity.WATCH,
        DriftSeverity.WARNING,
        DriftSeverity.CRITICAL,
    }
    assert abs(ic.details["mean_rank_ic"]) < 0.2


def test_negative_rank_ic_is_critical_not_rescued_by_absolute_value():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=15)
    current_pred, _ = _panel(days=40, symbols=30, seed=16)
    rng = np.random.default_rng(17)
    current_ret = -current_pred + pd.DataFrame(
        rng.normal(0.0, 0.05, current_pred.shape),
        index=current_pred.index,
        columns=current_pred.columns,
    )

    monitor = ModelDriftMonitor(min_evidence_days=20, min_cross_section_size=20)
    report = monitor.check_model(
        "mv_negative_ic",
        current_pred,
        current_ret,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    ic = _check(report, "ic_decay")
    assert ic.severity == DriftSeverity.CRITICAL
    assert ic.details["mean_rank_ic"] < -0.9


def test_ic_decay_requires_model_specific_baseline_returns():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred, realized = _panel(days=40, symbols=30, seed=18)
    monitor = ModelDriftMonitor(min_evidence_days=20, min_cross_section_size=20)
    report = monitor.check_model(
        "mv_missing_ic_baseline",
        pred,
        realized,
        baseline_predictions=pred.copy(),
    )

    ic = _check(report, "ic_decay")
    assert ic.severity == DriftSeverity.INCONCLUSIVE
    assert "baseline returns" in ic.recommended_action.lower()
    assert report.overall_severity == DriftSeverity.INCONCLUSIVE


def test_single_asset_rank_ic_is_explicitly_not_applicable():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred = _dated_series(100, seed=19)
    realized = _dated_series(100, seed=20)
    baseline = _dated_series(100, seed=21)

    monitor = ModelDriftMonitor(min_evidence_days=20)
    report = monitor.check_model(
        "mv_single_asset",
        pred,
        realized,
        baseline_predictions=baseline,
    )

    ic = _check(report, "ic_decay")
    assert ic.severity == DriftSeverity.INCONCLUSIVE
    assert ic.details["not_applicable"] is True


def test_rank_score_calibration_is_not_applicable():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred, realized = _panel(days=40, symbols=30, seed=22)
    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=23)
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        prediction_semantics="rank_score",
    )
    report = monitor.check_model(
        "mv_rank_calibration",
        pred,
        realized,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    calibration = _check(report, "calibration")
    assert calibration.severity == DriftSeverity.INCONCLUSIVE
    assert calibration.details["not_applicable"] is True
    assert calibration.details["prediction_semantics"] == "rank_score"


def test_return_forecast_calibration_uses_daily_cross_sectional_slopes():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred, realized = _panel(days=40, symbols=30, seed=24, relation=1.0, noise=0.02)
    baseline_pred, baseline_ret = _panel(
        days=40, symbols=30, seed=25, relation=1.0, noise=0.02
    )
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        prediction_semantics="return_forecast",
        calibration_slope_threshold=0.2,
    )
    report = monitor.check_model(
        "mv_return_calibration",
        pred,
        realized,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    calibration = _check(report, "calibration")
    assert calibration.severity == DriftSeverity.OK
    assert calibration.details["mode"] == "daily_cross_sectional"
    assert calibration.details["n_dates"] == 40
    assert abs(calibration.details["slope"] - 1.0) < 0.05


def test_return_forecast_calibration_detects_wrong_scale():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred, realized = _panel(days=40, symbols=30, seed=26, relation=0.1, noise=0.01)
    baseline_pred, baseline_ret = _panel(
        days=40, symbols=30, seed=27, relation=1.0, noise=0.02
    )
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        prediction_semantics="return_forecast",
        calibration_slope_threshold=0.2,
    )
    report = monitor.check_model(
        "mv_bad_scale",
        pred,
        realized,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    calibration = _check(report, "calibration")
    assert calibration.severity == DriftSeverity.CRITICAL
    assert calibration.details["slope"] < 0.2


def test_single_asset_return_forecast_uses_time_series_calibration():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    pred = _dated_series(100, seed=28, mean=0.0, std=0.03)
    rng = np.random.default_rng(29)
    realized = pred + pd.Series(
        rng.normal(0.0, 0.003, len(pred)),
        index=pred.index,
    )
    baseline = _dated_series(100, seed=30, mean=0.0, std=0.03)
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        prediction_semantics="return_forecast",
    )
    report = monitor.check_model(
        "mv_single_forecast",
        pred,
        realized,
        baseline_predictions=baseline,
    )

    calibration = _check(report, "calibration")
    assert calibration.severity == DriftSeverity.OK
    assert calibration.details["mode"] == "single_asset_time_series"
    assert abs(calibration.details["slope"] - 1.0) < 0.1


def test_feature_drift_checks_features_beyond_old_twenty_feature_cap():
    from src.research.drift_monitor import DriftSeverity, ModelDriftMonitor

    rng = np.random.default_rng(31)
    columns = [f"f{i:02d}" for i in range(25)]
    baseline_features = pd.DataFrame(
        rng.normal(0.0, 1.0, (400, 25)),
        columns=columns,
    )
    current_features = baseline_features.copy()
    current_features["f24"] = current_features["f24"] + 4.0

    pred, realized = _panel(days=40, symbols=30, seed=32)
    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=33)
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        psi_threshold=0.1,
    )
    report = monitor.check_model(
        "mv_feature_25",
        pred,
        realized,
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
        features=current_features,
        baseline_features=baseline_features,
    )

    feature = _check(report, "feature_drift")
    assert feature.severity in {DriftSeverity.WATCH, DriftSeverity.WARNING}
    assert feature.details["n_features_checked"] == 25
    assert feature.details["max_feature"] == "f24"


def test_invalid_prediction_semantics_rejected():
    import pytest

    from src.research.drift_monitor import ModelDriftMonitor

    with pytest.raises(ValueError, match="prediction_semantics"):
        ModelDriftMonitor(prediction_semantics="magic")


def test_drift_report_persisted_and_roundtrips(tmp_path):
    from src.research.drift_monitor import ModelDriftMonitor

    pred, realized = _panel(days=40, symbols=30, seed=34)
    baseline_pred, baseline_ret = _panel(days=40, symbols=30, seed=35)
    monitor = ModelDriftMonitor(
        min_evidence_days=20,
        min_cross_section_size=20,
        artifact_dir=tmp_path / "drift",
    )
    monitor.check_model(
        "mv_roundtrip",
        pred,
        realized,
        data_snapshot_id="snapshot_123",
        baseline_predictions=baseline_pred,
        baseline_returns=baseline_ret,
    )

    files = list((tmp_path / "drift").glob("drift_*.json"))
    assert len(files) == 1
    retrieved = monitor.get_last_report("mv_roundtrip")
    assert retrieved is not None
    assert retrieved.model_version_id == "mv_roundtrip"
    assert retrieved.data_snapshot_id == "snapshot_123"
    assert _check(retrieved, "ic_decay").details["n_dates"] == 40


def test_get_last_report_returns_none_for_unknown_model(tmp_path):
    from src.research.drift_monitor import ModelDriftMonitor

    monitor = ModelDriftMonitor(artifact_dir=tmp_path / "drift")
    assert monitor.get_last_report("missing") is None
