"""Model and data drift monitoring (T47.2).

Extends the factor-level DecayMonitor to cover model-level drift:
- Prediction distribution drift (KL divergence, mean/variance shift)
- IC / Rank IC decay at the model level
- Signal calibration (predicted vs realized return alignment)
- Feature distribution shift (PSI, mean shift per feature)

Each check emits measured value, baseline, threshold, severity, evidence
window, and recommended action. Stale or insufficient evidence is inconclusive
rather than passing. Alerts are deduplicated.
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


# ---------------------------------------------------------------------------
# Enums and data classes
# ---------------------------------------------------------------------------


class DriftSeverity(str, Enum):
    """Severity of a drift alert."""

    OK = "ok"  # No drift detected
    INCONCLUSIVE = "inconclusive"  # Insufficient evidence
    WATCH = "watch"  # Early warning — monitor more frequently
    WARNING = "warning"  # Significant drift — consider retraining
    CRITICAL = "critical"  # Severe drift — block new signals


@dataclass
class DriftCheck:
    """A single drift check result."""

    check_name: str  # e.g. "prediction_mean_shift"
    measured_value: float
    baseline: float
    threshold: float
    severity: DriftSeverity
    evidence_window: str  # e.g. "last 60 days"
    recommended_action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftReport:
    """Complete drift monitoring report for one model."""

    model_version_id: str
    data_snapshot_id: str
    market: str
    checked_at: str  # ISO timestamp
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


# ---------------------------------------------------------------------------
# Model Drift Monitor
# ---------------------------------------------------------------------------


class ModelDriftMonitor:
    """Monitor model-level drift across prediction, signal, and feature dimensions.

    Usage::

        monitor = ModelDriftMonitor(market="cn")
        report = monitor.check_model(
            model_version_id="mv_abc",
            predictions=recent_preds,     # Series: datetime × instrument
            returns=recent_returns,        # Series: datetime × instrument
            baseline_predictions=train_preds,  # optional baseline
        )
        if report.overall_severity in (DriftSeverity.WARNING, DriftSeverity.CRITICAL):
            ...  # trigger retraining
    """

    def __init__(
        self,
        market: str = "cn",
        *,
        mean_shift_threshold: float = 0.5,  # std deviations
        std_shift_threshold: float = 0.3,
        psi_threshold: float = 0.25,  # Population Stability Index
        ic_decay_threshold: float = 0.3,  # fraction decline
        calibration_slope_threshold: float = 0.2,  # deviation from 1.0
        min_evidence_days: int = 20,
        artifact_dir: str | Path = "artifacts/drift",
    ) -> None:
        self.market = market.lower()
        self.mean_shift_threshold = mean_shift_threshold
        self.std_shift_threshold = std_shift_threshold
        self.psi_threshold = psi_threshold
        self.ic_decay_threshold = ic_decay_threshold
        self.calibration_slope_threshold = calibration_slope_threshold
        self.min_evidence_days = min_evidence_days
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def check_model(
        self,
        model_version_id: str,
        predictions: pd.DataFrame | pd.Series,
        returns: pd.DataFrame | pd.Series,
        *,
        data_snapshot_id: str = "",
        baseline_predictions: pd.DataFrame | pd.Series | None = None,
        features: pd.DataFrame | None = None,
        baseline_features: pd.DataFrame | None = None,
        prediction_dates: pd.DatetimeIndex | None = None,
    ) -> DriftReport:
        """Run all drift checks for a model.

        Parameters
        ----------
        model_version_id : str
            Model version to check.
        predictions : DataFrame or Series
            Recent model predictions (datetime × instrument).
        returns : DataFrame or Series
            Realized forward returns for the same period.
        data_snapshot_id : str
            Data snapshot identity for evidence binding.
        baseline_predictions : DataFrame or Series, optional
            Training-period predictions for baseline comparison.
        features : DataFrame, optional
            Recent feature values for PSI computation.
        baseline_features : DataFrame, optional
            Training-period feature values for PSI baseline.
        prediction_dates : DatetimeIndex, optional
            Explicit date index for IC computation windows.

        Returns
        -------
        DriftReport
        """
        checks: list[DriftCheck] = []

        # Normalize to 1D Series
        pred_series = self._to_series(predictions)
        ret_series = self._to_series(returns)
        base_series = self._to_series(baseline_predictions) if baseline_predictions is not None else None

        n_obs = len(pred_series.dropna())
        evidence_window = f"{n_obs} observations"

        # If insufficient evidence, all checks are inconclusive
        if n_obs < self.min_evidence_days:
            return DriftReport(
                model_version_id=model_version_id,
                data_snapshot_id=data_snapshot_id,
                market=self.market,
                checked_at=datetime.now(timezone.utc).isoformat(),
                checks=[],
                overall_severity=DriftSeverity.INCONCLUSIVE,
                summary=f"Insufficient evidence: {n_obs} observations < "
                f"{self.min_evidence_days} minimum.",
            )

        # --- Check 1: Prediction mean shift ---
        checks.append(
            self._check_prediction_mean_shift(
                pred_series, base_series, evidence_window
            )
        )

        # --- Check 2: Prediction std shift ---
        checks.append(
            self._check_prediction_std_shift(
                pred_series, base_series, evidence_window
            )
        )

        # --- Check 3: PSI (prediction distribution shift) ---
        if base_series is not None and len(base_series.dropna()) >= self.min_evidence_days:
            checks.append(
                self._check_psi(pred_series, base_series, evidence_window)
            )

        # --- Check 4: IC decay ---
        if len(ret_series.dropna()) >= self.min_evidence_days:
            checks.append(
                self._check_ic_decay(pred_series, ret_series, evidence_window)
            )

        # --- Check 5: Signal calibration ---
        if len(ret_series.dropna()) >= self.min_evidence_days:
            checks.append(
                self._check_calibration(pred_series, ret_series, evidence_window)
            )

        # --- Check 6: Feature drift (PSI per feature) ---
        if features is not None and baseline_features is not None:
            checks.append(
                self._check_feature_drift(
                    features, baseline_features, evidence_window
                )
            )

        # Determine overall severity (worst across all checks)
        severity_order = {
            DriftSeverity.OK: 0,
            DriftSeverity.INCONCLUSIVE: 1,
            DriftSeverity.WATCH: 2,
            DriftSeverity.WARNING: 3,
            DriftSeverity.CRITICAL: 4,
        }
        overall = max(
            checks,
            key=lambda c: severity_order.get(c.severity, 0),
            default=DriftCheck(
                check_name="none",
                measured_value=0,
                baseline=0,
                threshold=0,
                severity=DriftSeverity.OK,
                evidence_window="",
                recommended_action="",
            ),
        )

        # Build summary
        alerts = [c for c in checks if c.severity not in (DriftSeverity.OK, DriftSeverity.INCONCLUSIVE)]
        if not alerts:
            summary = "All checks passed — no drift detected."
        else:
            summary = (
                f"{len(alerts)} check(s) raised alerts: "
                + "; ".join(f"{a.check_name}={a.severity.value}" for a in alerts)
                + f". Recommended: {alerts[0].recommended_action}"
            )

        report = DriftReport(
            model_version_id=model_version_id,
            data_snapshot_id=data_snapshot_id,
            market=self.market,
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            overall_severity=overall.severity,
            summary=summary,
        )

        # Persist report for deduplication
        self._persist_report(report)

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_prediction_mean_shift(
        self,
        pred: pd.Series,
        baseline: pd.Series | None,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if prediction mean has shifted from baseline."""
        current_mean = float(pred.mean())

        if baseline is None or len(baseline.dropna()) < self.min_evidence_days:
            return DriftCheck(
                check_name="prediction_mean_shift",
                measured_value=current_mean,
                baseline=0.0,
                threshold=self.mean_shift_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="Establish baseline with training predictions.",
            )

        baseline_mean = float(baseline.mean())
        baseline_std = float(baseline.std())

        if baseline_std < 1e-12:
            return DriftCheck(
                check_name="prediction_mean_shift",
                measured_value=current_mean,
                baseline=baseline_mean,
                threshold=self.mean_shift_threshold,
                severity=DriftSeverity.OK,
                evidence_window=evidence_window,
                recommended_action="",
            )

        z_score = abs(current_mean - baseline_mean) / baseline_std

        if z_score > self.mean_shift_threshold * 3:
            severity = DriftSeverity.CRITICAL
            action = "Block new signals; immediate retraining required."
        elif z_score > self.mean_shift_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Schedule retraining within 1 week."
        elif z_score > self.mean_shift_threshold:
            severity = DriftSeverity.WATCH
            action = "Monitor more frequently."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="prediction_mean_shift",
            measured_value=round(z_score, 4),
            baseline=round(baseline_mean, 6),
            threshold=self.mean_shift_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "current_mean": round(current_mean, 6),
                "baseline_mean": round(baseline_mean, 6),
                "baseline_std": round(baseline_std, 6),
                "z_score": round(z_score, 4),
            },
        )

    def _check_prediction_std_shift(
        self,
        pred: pd.Series,
        baseline: pd.Series | None,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if prediction variance has shifted from baseline."""
        current_std = float(pred.std())

        if baseline is None or len(baseline.dropna()) < self.min_evidence_days:
            return DriftCheck(
                check_name="prediction_std_shift",
                measured_value=current_std,
                baseline=0.0,
                threshold=self.std_shift_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="Establish baseline with training predictions.",
                details={"current_std": round(current_std, 6)},
            )

        baseline_std = float(baseline.std())

        if baseline_std < 1e-12:
            return DriftCheck(
                check_name="prediction_std_shift",
                measured_value=current_std,
                baseline=baseline_std,
                threshold=self.std_shift_threshold,
                severity=DriftSeverity.OK,
                evidence_window=evidence_window,
                recommended_action="",
            )

        ratio = current_std / baseline_std
        deviation = abs(ratio - 1.0)

        if deviation > self.std_shift_threshold * 3:
            severity = DriftSeverity.WARNING
            action = "Prediction variance has shifted significantly. Schedule retraining."
        elif deviation > self.std_shift_threshold:
            severity = DriftSeverity.WATCH
            action = "Monitor prediction variance trend."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="prediction_std_shift",
            measured_value=round(deviation, 4),
            baseline=round(baseline_std, 6),
            threshold=self.std_shift_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "current_std": round(current_std, 6),
                "baseline_std": round(baseline_std, 6),
                "ratio": round(ratio, 4),
            },
        )

    def _check_psi(
        self,
        pred: pd.Series,
        baseline: pd.Series,
        evidence_window: str,
    ) -> DriftCheck:
        """Compute Population Stability Index between current and baseline predictions."""
        current = pred.dropna()
        base = baseline.dropna()

        if len(current) < 10 or len(base) < 10:
            return DriftCheck(
                check_name="psi",
                measured_value=0.0,
                baseline=0.0,
                threshold=self.psi_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="Insufficient data for PSI computation.",
            )

        # Use decile binning
        try:
            all_vals = np.concatenate([current.values, base.values])
            bins = np.percentile(all_vals, np.linspace(0, 100, 11))
            bins = np.unique(bins)
            if len(bins) < 2:
                return DriftCheck(
                    check_name="psi",
                    measured_value=0.0,
                    baseline=0.0,
                    threshold=self.psi_threshold,
                    severity=DriftSeverity.OK,
                    evidence_window=evidence_window,
                    recommended_action="",
                )

            current_hist, _ = np.histogram(current, bins=bins, density=True)
            base_hist, _ = np.histogram(base, bins=bins, density=True)

            # Add small epsilon to avoid log(0)
            eps = 1e-10
            current_hist = np.clip(current_hist, eps, None)
            base_hist = np.clip(base_hist, eps, None)

            psi = float(np.sum((current_hist - base_hist) * np.log(current_hist / base_hist)))
        except Exception:
            return DriftCheck(
                check_name="psi",
                measured_value=0.0,
                baseline=0.0,
                threshold=self.psi_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="PSI computation failed.",
            )

        if psi > self.psi_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Significant prediction distribution shift. Schedule retraining."
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
            details={"interpretation": "PSI < 0.1: no shift; 0.1-0.25: moderate; >0.25: significant"},
        )

    def _check_ic_decay(
        self,
        pred: pd.Series,
        returns: pd.Series,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if rank IC has decayed relative to expected baseline."""
        # Align predictions and returns on common index
        common_idx = pred.dropna().index.intersection(returns.dropna().index)
        if len(common_idx) < self.min_evidence_days:
            return DriftCheck(
                check_name="ic_decay",
                measured_value=0.0,
                baseline=0.03,  # typical IC baseline
                threshold=self.ic_decay_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action=f"Insufficient observations for IC computation ({len(common_idx)} < {self.min_evidence_days}).",
            )

        p = pred.loc[common_idx]
        r = returns.loc[common_idx]

        # Spearman rank correlation
        try:
            from scipy import stats

            ic, p_value = stats.spearmanr(p, r)
            if not np.isfinite(ic):
                ic = 0.0
        except Exception:
            ic = 0.0

        ic_abs = abs(float(ic))
        baseline_ic = 0.03  # Minimum expected IC

        if ic_abs < baseline_ic * (1 - self.ic_decay_threshold * 2):
            severity = DriftSeverity.WARNING
            action = "IC has decayed significantly. Schedule retraining."
        elif ic_abs < baseline_ic * (1 - self.ic_decay_threshold):
            severity = DriftSeverity.WATCH
            action = "IC declining. Monitor trend."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="ic_decay",
            measured_value=round(ic_abs, 6),
            baseline=baseline_ic,
            threshold=self.ic_decay_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "spearman_ic": round(float(ic), 6),
                "n_obs": len(common_idx),
            },
        )

    def _check_calibration(
        self,
        pred: pd.Series,
        returns: pd.Series,
        evidence_window: str,
    ) -> DriftCheck:
        """Check if predicted scores align with realized returns (calibration slope)."""
        common_idx = pred.dropna().index.intersection(returns.dropna().index)
        if len(common_idx) < self.min_evidence_days:
            return DriftCheck(
                check_name="calibration",
                measured_value=0.0,
                baseline=1.0,
                threshold=self.calibration_slope_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action=f"Insufficient observations ({len(common_idx)} < {self.min_evidence_days}).",
            )

        p = pred.loc[common_idx].values.astype(float)
        r = returns.loc[common_idx].values.astype(float)

        # OLS: returns ~ alpha + beta * prediction
        X = np.column_stack([np.ones(len(p)), p])
        try:
            beta, _, _, _ = np.linalg.lstsq(X, r, rcond=None)
            slope = float(beta[1])
        except np.linalg.LinAlgError:
            slope = 0.0

        deviation = abs(slope - 1.0)

        if deviation > self.calibration_slope_threshold * 3:
            severity = DriftSeverity.CRITICAL
            action = "Predictions are uncalibrated. Block new signals."
        elif deviation > self.calibration_slope_threshold * 2:
            severity = DriftSeverity.WARNING
            action = "Calibration degraded. Schedule retraining."
        elif deviation > self.calibration_slope_threshold:
            severity = DriftSeverity.WATCH
            action = "Calibration slipping. Monitor."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="calibration",
            measured_value=round(deviation, 4),
            baseline=1.0,
            threshold=self.calibration_slope_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "slope": round(slope, 6),
                "expected_slope": 1.0,
            },
        )

    def _check_feature_drift(
        self,
        features: pd.DataFrame,
        baseline_features: pd.DataFrame,
        evidence_window: str,
    ) -> DriftCheck:
        """Check per-feature PSI; report the maximum PSI across features."""
        common_cols = features.columns.intersection(baseline_features.columns)
        if len(common_cols) == 0:
            return DriftCheck(
                check_name="feature_drift",
                measured_value=0.0,
                baseline=0.0,
                threshold=self.psi_threshold,
                severity=DriftSeverity.INCONCLUSIVE,
                evidence_window=evidence_window,
                recommended_action="No common features between current and baseline.",
            )

        max_psi = 0.0
        max_feature = ""
        per_feature_psi: dict[str, float] = {}

        for col in common_cols[:20]:  # Cap at 20 features for performance
            try:
                cur = features[col].dropna()
                base = baseline_features[col].dropna()
                if len(cur) < 10 or len(base) < 10:
                    continue

                all_vals = np.concatenate([cur.values, base.values])
                bins = np.percentile(all_vals, np.linspace(0, 100, 11))
                bins = np.unique(bins)
                if len(bins) < 2:
                    continue

                cur_hist, _ = np.histogram(cur, bins=bins, density=True)
                base_hist, _ = np.histogram(base, bins=bins, density=True)
                eps = 1e-10
                cur_hist = np.clip(cur_hist, eps, None)
                base_hist = np.clip(base_hist, eps, None)
                psi = float(np.sum((cur_hist - base_hist) * np.log(cur_hist / base_hist)))

                per_feature_psi[str(col)] = psi
                if psi > max_psi:
                    max_psi = psi
                    max_feature = str(col)
            except Exception:
                continue

        if max_psi > self.psi_threshold * 2:
            severity = DriftSeverity.WARNING
            action = f"Feature drift in {max_feature} (PSI={max_psi:.4f}). Schedule retraining."
        elif max_psi > self.psi_threshold:
            severity = DriftSeverity.WATCH
            action = f"Feature {max_feature} shows moderate drift."
        else:
            severity = DriftSeverity.OK
            action = ""

        return DriftCheck(
            check_name="feature_drift",
            measured_value=round(max_psi, 6),
            baseline=0.0,
            threshold=self.psi_threshold,
            severity=severity,
            evidence_window=evidence_window,
            recommended_action=action,
            details={
                "max_feature": max_feature,
                "n_features_checked": len(per_feature_psi),
                "per_feature_psi": {
                    k: round(v, 6) for k, v in sorted(
                        per_feature_psi.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:5]
                },
            },
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

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
            key=lambda p: p.stat().st_mtime,
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_series(data: pd.DataFrame | pd.Series | None) -> pd.Series:
        """Normalize predictions/returns to a 1D Series."""
        if data is None:
            return pd.Series(dtype=float)
        if isinstance(data, pd.DataFrame):
            if data.shape[1] == 1:
                return data.iloc[:, 0]
            # Multi-column: flatten
            return data.stack(dropna=True)
        return data

    @staticmethod
    def _dict_to_report(data: dict[str, Any]) -> DriftReport:
        checks = []
        for c in data.get("checks", []):
            checks.append(
                DriftCheck(
                    check_name=c["check_name"],
                    measured_value=c["measured_value"],
                    baseline=c["baseline"],
                    threshold=c["threshold"],
                    severity=DriftSeverity(c["severity"]),
                    evidence_window=c.get("evidence_window", ""),
                    recommended_action=c.get("recommended_action", ""),
                    details=c.get("details", {}),
                )
            )
        return DriftReport(
            model_version_id=data["model_version_id"],
            data_snapshot_id=data.get("data_snapshot_id", ""),
            market=data.get("market", ""),
            checked_at=data["checked_at"],
            checks=checks,
            overall_severity=DriftSeverity(data["overall_severity"]),
            summary=data.get("summary", ""),
        )
