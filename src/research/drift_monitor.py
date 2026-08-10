"""Model and data drift monitoring (T47.2).

The monitor separates three statistical concepts that must not be conflated:

- distribution drift, evaluated over the prediction/feature population;
- cross-sectional rank skill, evaluated per trading date and then through time;
- return calibration, evaluated only when model outputs are actual return forecasts.

Missing, stale, structurally invalid, or non-comparable evidence is inconclusive
rather than passing. Structurally inapplicable checks are recorded explicitly and
do not downgrade an otherwise valid report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "DriftSeverity",
    "DriftCheck",
    "DriftReport",
    "ModelDriftMonitor",
]


class DriftSeverity(str, Enum):
    """Severity of a drift alert."""

    OK = "ok"
    INCONCLUSIVE = "inconclusive"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class DriftCheck:
    """A single drift check result."""

    check_name: str
    measured_value: float
    baseline: float
    threshold: float
    severity: DriftSeverity
    evidence_window: str
    recommended_action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftReport:
    """Complete drift monitoring report for one model."""

    model_version_id: str
    data_snapshot_id: str
    market: str
    checked_at: str
    checks: list[DriftCheck]
    overall_severity: DriftSeverity
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version_id": self.model_version_id,
            "data_snapshot_id": self.data_snapshot_id,
            "market": self.market,
            "checked_at": self.checked_at,
            "overall_severity": self.overall_severity.value,
            "summary": self.summary,
            "checks": [
                {
                    "check_name": c.check_name,
                    "measured_value": round(c.measured_value, 6),
                    "baseline": round(c.baseline, 6),
                    "threshold": round(c.threshold, 6),
                    "severity": c.severity.value,
                    "evidence_window": c.evidence_window,
                    "recommended_action": c.recommended_action,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


class ModelDriftMonitor:
    """Monitor model-level distribution, rank-skill, and calibration drift.

    ``prediction_semantics`` is intentionally explicit:

    - ``"rank_score"``: scores are ordinal / arbitrary-scale model outputs.
      Cross-sectional Rank IC is valid; calibration slope to 1.0 is not.
    - ``"return_forecast"``: outputs are realized-return-unit forecasts.
      Rank IC and return calibration are both valid when the data shape permits.

    Rank IC decay requires a frozen baseline prediction/return evidence pair.
    There is no generic IC fallback because a model-specific decay check without
    a model-specific baseline is not a decay measurement.
    """

    _VALID_PREDICTION_SEMANTICS = {"rank_score", "return_forecast"}

    def __init__(
        self,
        market: str = "cn",
        *,
        mean_shift_threshold: float = 0.5,
        std_shift_threshold: float = 0.3,
        psi_threshold: float = 0.25,
        ic_decay_threshold: float = 0.3,
        calibration_slope_threshold: float = 0.2,
        min_evidence_days: int = 20,
        min_cross_section_size: int = 20,
        prediction_semantics: str = "rank_score",
        artifact_dir: str | Path = "artifacts/drift",
    ) -> None:
        semantics = str(prediction_semantics).strip().lower()
        if semantics not in self._VALID_PREDICTION_SEMANTICS:
            raise ValueError(
                "prediction_semantics must be one of "
                f"{sorted(self._VALID_PREDICTION_SEMANTICS)}"
            )
        if min_evidence_days < 2:
            raise ValueError("min_evidence_days must be at least 2")
        if min_cross_section_size < 2:
            raise ValueError("min_cross_section_size must be at least 2")

        self.market = market.lower()
        self.mean_shift_threshold = mean_shift_threshold
        self.std_shift_threshold = std_shift_threshold
        self.psi_threshold = psi_threshold
        self.ic_decay_threshold = ic_decay_threshold
        self.calibration_slope_threshold = calibration_slope_threshold
        self.min_evidence_days = min_evidence_days
        self.min_cross_section_size = min_cross_section_size
        self.prediction_semantics = semantics
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def check_model(
        self,
        model_version_id: str,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
        *,
        data_snapshot_id: str = "",
        baseline_predictions: pd.DataFrame | pd.Series | None = None,
        baseline_returns: pd.DataFrame | pd.Series | None = None,
        features: pd.DataFrame | None = None,
        baseline_features: pd.DataFrame | None = None,
    ) -> DriftReport:
        """Run all applicable drift checks for one model.

        Predictions and returns must carry a real date index. Wide
        ``date × instrument`` DataFrames and ``(datetime, instrument)`` Series
        are treated as cross-sectional panels. A single DatetimeIndex Series is
        treated as a single-asset time series.
        """
        checks: list[DriftCheck] = []

        current_days = self._evidence_days(predictions)
        evidence_window = f"{current_days} trading days"
        if current_days < self.min_evidence_days:
            return DriftReport(
                model_version_id=model_version_id,
                data_snapshot_id=data_snapshot_id,
                market=self.market,
                checked_at=datetime.now(timezone.utc).isoformat(),
                checks=[],
                overall_severity=DriftSeverity.INCONCLUSIVE,
                summary=(
                    f"Insufficient evidence: {current_days} trading days < "
                    f"{self.min_evidence_days} minimum."
                ),
            )

        pred_series = self._to_series(predictions)
        base_days = self._evidence_days(baseline_predictions)
        base_series = (
            self._to_series(baseline_predictions)
            if baseline_predictions is not None and base_days >= self.min_evidence_days
            else None
        )

        checks.append(
            self._check_prediction_mean_shift(
                pred_series, base_series, evidence_window
            )
        )
        checks.append(
            self._check_prediction_std_shift(
                pred_series, base_series, evidence_window
            )
        )

        if base_series is not None:
            checks.append(self._check_psi(pred_series, base_series, evidence_window))
        else:
            checks.append(
                self._inconclusive_check(
                    "psi",
                    self.psi_threshold,
                    evidence_window,
                    "A baseline prediction window with sufficient trading days is required.",
                )
            )

        checks.append(
            self._check_ic_decay(
                predictions,
                returns,
                baseline_predictions,
                baseline_returns,
                evidence_window,
            )
        )
        checks.append(
            self._check_calibration(predictions, returns, evidence_window)
        )

        if features is not None and baseline_features is not None:
            checks.append(
                self._check_feature_drift(
                    features, baseline_features, evidence_window
                )
            )

        overall = self._overall_severity(checks)
        summary = self._build_summary(checks, overall)

        report = DriftReport(
            model_version_id=model_version_id,
            data_snapshot_id=data_snapshot_id,
            market=self.market,
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            overall_severity=overall,
            summary=summary,
        )
        self._persist_report(report)
        return report

    def _check_prediction_mean_shift(
        self,
        pred: pd.Series,
        baseline: pd.Series | None,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if the prediction population mean shifted from baseline."""
        current = pd.to_numeric(pred, errors="coerce").dropna()
        current_mean = float(current.mean()) if not current.empty else 0.0

        if baseline is None:
            return DriftCheck(
                check_name="prediction_mean_shift",
                measured_value=current_mean,
                baseline=0.0,
                threshold=self.mean_shift_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="Establish a frozen baseline prediction window.",
            )

        base = pd.to_numeric(baseline, errors="coerce").dropna()
        baseline_mean = float(base.mean())
        baseline_std = float(base.std())

        if not np.isfinite(baseline_std) or baseline_std < 1e-12:
            return self._inconclusive_check(
                "prediction_mean_shift",
                self.mean_shift_threshold,
                evidence_window,
                "Baseline prediction variance is zero or non-finite.",
                baseline=baseline_mean,
                details={"current_mean": current_mean, "baseline_mean": baseline_mean},
            )

        z_score = abs(current_mean - baseline_mean) / baseline_std
        if z_score > self.mean_shift_threshold * 3:
            severity = DriftSeverity.CRITICAL
            action = "Block new signals; prediction mean has shifted severely."
        elif z_score > self.mean_shift_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Prediction mean shifted materially; schedule model review."
        elif z_score > self.mean_shift_threshold:
            severity = DriftSeverity.WATCH
            action = "Monitor prediction mean more frequently."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="prediction_mean_shift",
            measured_value=round(float(z_score), 6),
            baseline=round(baseline_mean, 6),
            threshold=self.mean_shift_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "current_mean": round(current_mean, 6),
                "baseline_mean": round(baseline_mean, 6),
                "baseline_std": round(baseline_std, 6),
                "z_score": round(float(z_score), 6),
            },
        )

    def _check_prediction_std_shift(
        self,
        pred: pd.Series,
        baseline: pd.Series | None,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if prediction dispersion shifted from baseline."""
        current = pd.to_numeric(pred, errors="coerce").dropna()
        current_std = float(current.std()) if len(current) > 1 else 0.0

        if baseline is None:
            return DriftCheck(
                check_name="prediction_std_shift",
                measured_value=current_std,
                baseline=0.0,
                threshold=self.std_shift_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="Establish a frozen baseline prediction window.",
                details={"current_std": round(current_std, 6)},
            )

        base = pd.to_numeric(baseline, errors="coerce").dropna()
        baseline_std = float(base.std())
        if not np.isfinite(baseline_std) or baseline_std < 1e-12:
            return self._inconclusive_check(
                "prediction_std_shift",
                self.std_shift_threshold,
                evidence_window,
                "Baseline prediction variance is zero or non-finite.",
                baseline=baseline_std if np.isfinite(baseline_std) else 0.0,
                details={"current_std": current_std},
            )

        ratio = current_std / baseline_std
        deviation = abs(ratio - 1.0)
        if deviation > self.std_shift_threshold * 3:
            severity = DriftSeverity.WARNING
            action = "Prediction variance shifted severely; schedule model review."
        elif deviation > self.std_shift_threshold:
            severity = DriftSeverity.WATCH
            action = "Monitor prediction variance trend."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="prediction_std_shift",
            measured_value=round(float(deviation), 6),
            baseline=round(baseline_std, 6),
            threshold=self.std_shift_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "current_std": round(current_std, 6),
                "baseline_std": round(baseline_std, 6),
                "ratio": round(float(ratio), 6),
            },
        )

    def _check_psi(
        self,
        pred: pd.Series,
        baseline: pd.Series,
        evidence_window: str,
    ) -> DriftCheck:
        """Compute PSI using baseline-quantile probability bins."""
        psi = self._population_stability_index(pred, baseline)
        if psi is None:
            return self._inconclusive_check(
                "psi",
                self.psi_threshold,
                evidence_window,
                "Insufficient finite variation for PSI computation.",
            )

        if psi > self.psi_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Prediction distribution shifted materially; schedule model review."
        elif psi > self.psi_threshold:
            severity = DriftSeverity.WATCH
            action = "Monitor prediction distribution."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="psi",
            measured_value=round(psi, 6),
            baseline=0.0,
            threshold=self.psi_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "method": "baseline_quantile_probability_bins",
                "interpretation": "PSI > configured threshold indicates distribution shift",
            },
        )

    def _check_ic_decay(
        self,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
        baseline_predictions: pd.DataFrame | pd.Series | None,
        baseline_returns: pd.DataFrame | pd.Series | None,
        evidence_window: str,
    ) -> DriftCheck:
        """Compare daily cross-sectional Rank IC with frozen baseline evidence."""
        current = self._daily_rank_ic(predictions, returns)
        if current is None:
            return self._not_applicable_check(
                "ic_decay",
                self.ic_decay_threshold,
                evidence_window,
                "Cross-sectional Rank IC is undefined for non-panel/single-asset inputs.",
            )
        if len(current) < self.min_evidence_days:
            return self._inconclusive_check(
                "ic_decay",
                self.ic_decay_threshold,
                evidence_window,
                (
                    f"Only {len(current)} valid cross-sectional IC dates; "
                    f"{self.min_evidence_days} required."
                ),
                details={"n_dates": int(len(current))},
            )
        if baseline_predictions is None or baseline_returns is None:
            return self._inconclusive_check(
                "ic_decay",
                self.ic_decay_threshold,
                evidence_window,
                "IC decay requires frozen baseline predictions and baseline returns.",
                details=self._rank_ic_summary(current),
            )

        baseline = self._daily_rank_ic(baseline_predictions, baseline_returns)
        if baseline is None or len(baseline) < self.min_evidence_days:
            return self._inconclusive_check(
                "ic_decay",
                self.ic_decay_threshold,
                evidence_window,
                "Baseline evidence does not contain enough valid cross-sectional IC dates.",
                details={
                    **self._rank_ic_summary(current),
                    "baseline_n_dates": 0 if baseline is None else int(len(baseline)),
                },
            )

        current_mean = float(current.mean())
        baseline_mean = float(baseline.mean())
        details = {
            **self._rank_ic_summary(current),
            "baseline_mean_rank_ic": round(baseline_mean, 6),
            "baseline_n_dates": int(len(baseline)),
            "baseline_positive_rank_ic_ratio": round(float((baseline > 0).mean()), 6),
            "min_cross_section_size": self.min_cross_section_size,
        }

        if not np.isfinite(baseline_mean) or baseline_mean <= 0:
            return self._inconclusive_check(
                "ic_decay",
                self.ic_decay_threshold,
                evidence_window,
                "Baseline mean Rank IC is not positive; decay is not a meaningful ratio.",
                baseline=baseline_mean if np.isfinite(baseline_mean) else 0.0,
                details=details,
            )

        decay_fraction = (baseline_mean - current_mean) / abs(baseline_mean)
        details["decay_fraction"] = round(float(decay_fraction), 6)

        if current_mean <= 0:
            severity = DriftSeverity.CRITICAL
            action = "Cross-sectional rank skill reversed or vanished; block new signals."
        elif decay_fraction > self.ic_decay_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Rank IC decayed materially versus frozen baseline; review/retrain."
        elif decay_fraction > self.ic_decay_threshold:
            severity = DriftSeverity.WATCH
            action = "Rank IC is declining versus frozen baseline."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="ic_decay",
            measured_value=round(float(decay_fraction), 6),
            baseline=round(baseline_mean, 6),
            threshold=self.ic_decay_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details=details,
        )

    def _check_calibration(
        self,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
        evidence_window: str,
    ) -> DriftCheck:
        """Check return-unit calibration only for actual return forecasts."""
        if self.prediction_semantics != "return_forecast":
            return self._not_applicable_check(
                "calibration",
                self.calibration_slope_threshold,
                evidence_window,
                "Slope-to-1 calibration is undefined for arbitrary-scale rank scores.",
                baseline=1.0,
                details={"prediction_semantics": self.prediction_semantics},
            )

        panel_slopes = self._daily_calibration_slopes(predictions, returns)
        if panel_slopes is not None:
            if len(panel_slopes) < self.min_evidence_days:
                return self._inconclusive_check(
                    "calibration",
                    self.calibration_slope_threshold,
                    evidence_window,
                    (
                        f"Only {len(panel_slopes)} valid cross-sectional calibration dates; "
                        f"{self.min_evidence_days} required."
                    ),
                    baseline=1.0,
                    details={
                        "mode": "daily_cross_sectional",
                        "n_dates": int(len(panel_slopes)),
                    },
                )
            slope = float(panel_slopes.median())
            details = {
                "mode": "daily_cross_sectional",
                "slope": round(slope, 6),
                "mean_slope": round(float(panel_slopes.mean()), 6),
                "n_dates": int(len(panel_slopes)),
                "expected_slope": 1.0,
                "min_cross_section_size": self.min_cross_section_size,
            }
        else:
            aligned = self._aligned_temporal_series(predictions, returns)
            if aligned is None:
                return self._not_applicable_check(
                    "calibration",
                    self.calibration_slope_threshold,
                    evidence_window,
                    "Return calibration requires either a dated panel or dated single-asset series.",
                    baseline=1.0,
                )
            if len(aligned) < self.min_evidence_days:
                return self._inconclusive_check(
                    "calibration",
                    self.calibration_slope_threshold,
                    evidence_window,
                    (
                        f"Only {len(aligned)} aligned return-forecast observations; "
                        f"{self.min_evidence_days} required."
                    ),
                    baseline=1.0,
                    details={"mode": "single_asset_time_series", "n_obs": int(len(aligned))},
                )
            slope = self._ols_slope(
                aligned["prediction"].to_numpy(dtype=float),
                aligned["return"].to_numpy(dtype=float),
            )
            if slope is None:
                return self._inconclusive_check(
                    "calibration",
                    self.calibration_slope_threshold,
                    evidence_window,
                    "Prediction variance is zero; calibration slope is undefined.",
                    baseline=1.0,
                )
            details = {
                "mode": "single_asset_time_series",
                "slope": round(float(slope), 6),
                "n_obs": int(len(aligned)),
                "expected_slope": 1.0,
            }

        deviation = abs(float(slope) - 1.0)
        if deviation > self.calibration_slope_threshold * 3:
            severity = DriftSeverity.CRITICAL
            action = "Return forecasts are severely miscalibrated; block new signals."
        elif deviation > self.calibration_slope_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Return calibration degraded; schedule model review."
        elif deviation > self.calibration_slope_threshold:
            severity = DriftSeverity.WATCH
            action = "Return calibration is slipping."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="calibration",
            measured_value=round(float(deviation), 6),
            baseline=1.0,
            threshold=self.calibration_slope_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details=details,
        )

    def _check_feature_drift(
        self,
        features: pd.DataFrame,
        baseline_features: pd.DataFrame,
        evidence_window: str,
    ) -> DriftCheck:
        """Check PSI for every common feature and report the maximum."""
        common_cols = features.columns.intersection(baseline_features.columns)
        if len(common_cols) == 0:
            return self._inconclusive_check(
                "feature_drift",
                self.psi_threshold,
                evidence_window,
                "No common features between current and baseline.",
            )

        per_feature_psi: dict[str, float] = {}
        for col in common_cols:
            psi = self._population_stability_index(features[col], baseline_features[col])
            if psi is not None:
                per_feature_psi[str(col)] = psi

        if not per_feature_psi:
            return self._inconclusive_check(
                "feature_drift",
                self.psi_threshold,
                evidence_window,
                "No feature had enough finite variation for PSI computation.",
                details={"n_features_requested": int(len(common_cols))},
            )

        max_feature, max_psi = max(per_feature_psi.items(), key=lambda item: item[1])
        if max_psi > self.psi_threshold * 2:
            severity = DriftSeverity.WARNING
            action = f"Feature drift in {max_feature} (PSI={max_psi:.4f}); review model."
        elif max_psi > self.psi_threshold:
            severity = DriftSeverity.WATCH
            action = f"Feature {max_feature} shows moderate drift."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="feature_drift",
            measured_value=round(float(max_psi), 6),
            baseline=0.0,
            threshold=self.psi_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "max_feature": max_feature,
                "n_features_checked": len(per_feature_psi),
                "per_feature_psi": {
                    key: round(value, 6)
                    for key, value in sorted(
                        per_feature_psi.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )[:10]
                },
            },
        )

    def _persist_report(self, report: DriftReport) -> None:
        """Save report to artifact dir for deduplication."""
        key = hashlib.sha256(
            f"{report.model_version_id}:{report.checked_at[:10]}".encode()
        ).hexdigest()[:16]
        path = self.artifact_dir / f"drift_{key}.json"
        try:
            path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist drift report", error=str(exc))

    def get_last_report(self, model_version_id: str) -> DriftReport | None:
        """Return the most recent drift report for this model, if any."""
        reports = sorted(
            self.artifact_dir.glob("drift_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in reports:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("model_version_id") == model_version_id:
                    return self._dict_to_report(data)
            except Exception:
                continue
        return None

    @staticmethod
    def _to_series(data: pd.DataFrame | pd.Series | None) -> pd.Series:
        """Flatten values for population-distribution checks only."""
        if data is None:
            return pd.Series(dtype=float)
        if isinstance(data, pd.DataFrame):
            if data.shape[1] == 1:
                return data.iloc[:, 0]
            return data.stack(dropna=True)
        return data

    @staticmethod
    def _date_level(index: pd.Index) -> int | None:
        if isinstance(index, pd.DatetimeIndex):
            return 0
        if not isinstance(index, pd.MultiIndex):
            return None
        for candidate in ("datetime", "date"):
            if candidate in index.names:
                return index.names.index(candidate)
        for level in range(index.nlevels):
            values = index.get_level_values(level)
            if isinstance(values, pd.DatetimeIndex):
                return level
            if pd.api.types.is_datetime64_any_dtype(values.dtype):
                return level
        return None

    @classmethod
    def _evidence_days(cls, data: pd.DataFrame | pd.Series | None) -> int:
        if data is None or len(data) == 0:
            return 0
        index = data.index
        level = cls._date_level(index)
        if level is None:
            return 0
        if isinstance(index, pd.MultiIndex):
            values = pd.DatetimeIndex(index.get_level_values(level)).normalize()
        else:
            values = pd.DatetimeIndex(index).normalize()
        return int(values.nunique())

    @classmethod
    def _panel_series(
        cls, data: pd.DataFrame | pd.Series
    ) -> pd.Series | None:
        """Normalize a cross-sectional panel to (datetime, instrument) Series."""
        if isinstance(data, pd.DataFrame):
            if isinstance(data.index, pd.DatetimeIndex) and data.shape[1] >= 2:
                series = data.stack(dropna=False)
                series.index = series.index.set_names(["datetime", "instrument"])
                return pd.to_numeric(series, errors="coerce").sort_index()
            if isinstance(data.index, pd.MultiIndex) and data.shape[1] == 1:
                data = data.iloc[:, 0]
            else:
                return None

        if not isinstance(data.index, pd.MultiIndex) or data.index.nlevels != 2:
            return None
        date_level = cls._date_level(data.index)
        if date_level is None:
            return None
        instrument_level = 1 - date_level
        dates = pd.to_datetime(data.index.get_level_values(date_level), errors="coerce")
        instruments = data.index.get_level_values(instrument_level).astype(str)
        if dates.isna().any():
            return None
        index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex(dates).normalize(), instruments],
            names=["datetime", "instrument"],
        )
        series = pd.Series(
            pd.to_numeric(data.to_numpy(), errors="coerce"),
            index=index,
            name=data.name,
            dtype=float,
        ).sort_index()
        if series.index.has_duplicates:
            return None
        return series

    def _daily_rank_ic(
        self,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
    ) -> pd.Series | None:
        pred = self._panel_series(predictions)
        realized = self._panel_series(returns)
        if pred is None or realized is None:
            return None

        joined = pd.concat(
            [pred.rename("prediction"), realized.rename("return")],
            axis=1,
            join="inner",
        ).replace([np.inf, -np.inf], np.nan)
        rows: dict[pd.Timestamp, float] = {}
        for date, group in joined.groupby(level="datetime", sort=True):
            clean = group.dropna()
            if len(clean) < self.min_cross_section_size:
                continue
            if clean["prediction"].nunique() < 2 or clean["return"].nunique() < 2:
                continue
            value = clean["prediction"].corr(clean["return"], method="spearman")
            if pd.notna(value) and np.isfinite(value):
                rows[pd.Timestamp(date)] = float(value)
        return pd.Series(rows, dtype=float, name="rank_ic").sort_index()

    @staticmethod
    def _rank_ic_summary(values: pd.Series) -> dict[str, Any]:
        mean = float(values.mean()) if len(values) else 0.0
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        return {
            "mean_rank_ic": round(mean, 6),
            "rank_icir": round(mean / std, 6) if std > 0 else 0.0,
            "positive_rank_ic_ratio": round(float((values > 0).mean()), 6)
            if len(values)
            else 0.0,
            "n_dates": int(len(values)),
        }

    def _daily_calibration_slopes(
        self,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
    ) -> pd.Series | None:
        pred = self._panel_series(predictions)
        realized = self._panel_series(returns)
        if pred is None or realized is None:
            return None

        joined = pd.concat(
            [pred.rename("prediction"), realized.rename("return")],
            axis=1,
            join="inner",
        ).replace([np.inf, -np.inf], np.nan)
        rows: dict[pd.Timestamp, float] = {}
        for date, group in joined.groupby(level="datetime", sort=True):
            clean = group.dropna()
            if len(clean) < self.min_cross_section_size:
                continue
            slope = self._ols_slope(
                clean["prediction"].to_numpy(dtype=float),
                clean["return"].to_numpy(dtype=float),
            )
            if slope is not None and np.isfinite(slope):
                rows[pd.Timestamp(date)] = float(slope)
        return pd.Series(rows, dtype=float, name="calibration_slope").sort_index()

    @classmethod
    def _aligned_temporal_series(
        cls,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
    ) -> pd.DataFrame | None:
        if isinstance(predictions, pd.DataFrame):
            if predictions.shape[1] != 1:
                return None
            predictions = predictions.iloc[:, 0]
        if isinstance(returns, pd.DataFrame):
            if returns.shape[1] != 1:
                return None
            returns = returns.iloc[:, 0]
        if not isinstance(predictions.index, pd.DatetimeIndex):
            return None
        if not isinstance(returns.index, pd.DatetimeIndex):
            return None

        pred = pd.to_numeric(predictions, errors="coerce").rename("prediction")
        realized = pd.to_numeric(returns, errors="coerce").rename("return")
        aligned = pd.concat([pred, realized], axis=1, join="inner")
        aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()
        if aligned.index.has_duplicates:
            return None
        return aligned.sort_index()

    @staticmethod
    def _ols_slope(prediction: np.ndarray, realized: np.ndarray) -> float | None:
        if len(prediction) < 2 or float(np.std(prediction)) < 1e-12:
            return None
        design = np.column_stack([np.ones(len(prediction)), prediction])
        try:
            beta, _, _, _ = np.linalg.lstsq(design, realized, rcond=None)
        except np.linalg.LinAlgError:
            return None
        slope = float(beta[1])
        return slope if np.isfinite(slope) else None

    @staticmethod
    def _population_stability_index(
        current: pd.Series,
        baseline: pd.Series,
    ) -> float | None:
        cur = pd.to_numeric(current, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        base = pd.to_numeric(baseline, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(cur) < 10 or len(base) < 10 or base.nunique() < 2:
            return None

        internal = np.quantile(base.to_numpy(dtype=float), np.linspace(0.1, 0.9, 9))
        internal = np.unique(internal[np.isfinite(internal)])
        bins = np.concatenate(([-np.inf], internal, [np.inf]))
        if len(bins) < 3:
            return None

        cur_counts, _ = np.histogram(cur.to_numpy(dtype=float), bins=bins)
        base_counts, _ = np.histogram(base.to_numpy(dtype=float), bins=bins)
        cur_pct = cur_counts.astype(float) / max(float(cur_counts.sum()), 1.0)
        base_pct = base_counts.astype(float) / max(float(base_counts.sum()), 1.0)
        eps = 1e-6
        cur_pct = np.clip(cur_pct, eps, None)
        base_pct = np.clip(base_pct, eps, None)
        return float(np.sum((cur_pct - base_pct) * np.log(cur_pct / base_pct)))

    @staticmethod
    def _inconclusive_check(
        check_name: str,
        threshold: float,
        evidence_window: str,
        action: str,
        *,
        baseline: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> DriftCheck:
        return DriftCheck(
            check_name=check_name,
            measured_value=0.0,
            baseline=float(baseline),
            threshold=threshold,
            severity=DriftSeverity.INCONCLUSIVE,
            evidence_window=evidence_window,
            recommended_action=action,
            details=details or {},
        )

    @staticmethod
    def _not_applicable_check(
        check_name: str,
        threshold: float,
        evidence_window: str,
        reason: str,
        *,
        baseline: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> DriftCheck:
        payload = dict(details or {})
        payload.update({"not_applicable": True, "reason": reason})
        return DriftCheck(
            check_name=check_name,
            measured_value=0.0,
            baseline=float(baseline),
            threshold=threshold,
            severity=DriftSeverity.INCONCLUSIVE,
            evidence_window=evidence_window,
            recommended_action="",
            details=payload,
        )

    @staticmethod
    def _overall_severity(checks: list[DriftCheck]) -> DriftSeverity:
        severity_order = {
            DriftSeverity.OK: 0,
            DriftSeverity.INCONCLUSIVE: 1,
            DriftSeverity.WATCH: 2,
            DriftSeverity.WARNING: 3,
            DriftSeverity.CRITICAL: 4,
        }
        applicable = [
            check
            for check in checks
            if not bool(check.details.get("not_applicable", False))
        ]
        if not applicable:
            return DriftSeverity.INCONCLUSIVE
        return max(
            applicable,
            key=lambda check: severity_order[check.severity],
        ).severity

    @staticmethod
    def _build_summary(
        checks: list[DriftCheck], overall: DriftSeverity
    ) -> str:
        alerts = [
            check
            for check in checks
            if check.severity
            in (DriftSeverity.WATCH, DriftSeverity.WARNING, DriftSeverity.CRITICAL)
        ]
        if alerts:
            return (
                f"{len(alerts)} check(s) raised alerts: "
                + "; ".join(
                    f"{check.check_name}={check.severity.value}" for check in alerts
                )
                + f". Recommended: {alerts[0].recommended_action}"
            )

        inconclusive = [
            check
            for check in checks
            if check.severity == DriftSeverity.INCONCLUSIVE
            and not bool(check.details.get("not_applicable", False))
        ]
        if inconclusive:
            return (
                f"No drift alert, but {len(inconclusive)} applicable check(s) are "
                "inconclusive: "
                + ", ".join(check.check_name for check in inconclusive)
                + "."
            )
        if overall == DriftSeverity.OK:
            return "All applicable checks passed — no drift detected."
        return "No applicable drift checks produced conclusive evidence."

    @staticmethod
    def _dict_to_report(data: dict[str, Any]) -> DriftReport:
        checks = [
            DriftCheck(
                check_name=item["check_name"],
                measured_value=item["measured_value"],
                baseline=item["baseline"],
                threshold=item["threshold"],
                severity=DriftSeverity(item["severity"]),
                evidence_window=item.get("evidence_window", ""),
                recommended_action=item.get("recommended_action", ""),
                details=item.get("details", {}),
            )
            for item in data.get("checks", [])
        ]
        return DriftReport(
            model_version_id=data["model_version_id"],
            data_snapshot_id=data.get("data_snapshot_id", ""),
            market=data.get("market", ""),
            checked_at=data["checked_at"],
            checks=checks,
            overall_severity=DriftSeverity(data["overall_severity"]),
            summary=data.get("summary", ""),
        )
