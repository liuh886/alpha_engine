"""Factor Decay Monitor — Track factor effectiveness over time.

This module monitors Active factors and model versions for decay:
- IC/ICIR rolling decline
- Contribution turning negative
- Rank correlation instability
- Market regime performance degradation

When decay is detected, factors are automatically flagged as Watch/Downgrade.

Usage:
    monitor = DecayMonitor(market="cn")
    report = monitor.check_all_active_factors()
    monitor.apply_status_changes(report)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

__all__ = ["DecayMonitor", "DecayStatus", "FactorDecayReport"]


class DecayStatus(str, Enum):
    """Factor decay status."""

    HEALTHY = "healthy"  # No decay detected
    WATCH = "watch"  # Early warning signs
    DEGRADED = "degraded"  # Significant decay
    DOWNgrade = "downgrade"  # Should be demoted


@dataclass
class FactorDecayReport:
    """Report on a single factor's decay status.

    Attributes
    ----------
    factor_name : str
        Name of the factor.
    status : DecayStatus
        Current decay status.
    ic_trend : float
        Slope of IC over time (negative = decaying).
    ic_current : float
        Most recent IC value.
    ic_6m_avg : float
        6-month rolling average IC.
    ic_12m_avg : float
        12-month rolling average IC.
    icir_current : float
        Most recent ICIR.
    rank_corr_instability : float
        Standard deviation of rank correlation (higher = more unstable).
    alerts : list[str]
        List of specific decay alerts.
    recommendation : str
        Human-readable recommendation.
    """

    factor_name: str
    status: DecayStatus = DecayStatus.HEALTHY
    ic_trend: float = 0.0
    ic_current: float = 0.0
    ic_6m_avg: float = 0.0
    ic_12m_avg: float = 0.0
    icir_current: float = 0.0
    rank_corr_instability: float = 0.0
    alerts: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "status": self.status.value,
            "ic_trend": round(self.ic_trend, 4),
            "ic_current": round(self.ic_current, 4),
            "ic_6m_avg": round(self.ic_6m_avg, 4),
            "ic_12m_avg": round(self.ic_12m_avg, 4),
            "icir_current": round(self.icir_current, 4),
            "rank_corr_instability": round(self.rank_corr_instability, 4),
            "alerts": self.alerts,
            "recommendation": self.recommendation,
        }


@dataclass
class DecayMonitor:
    """Monitor factors for decay and auto-downgrade.

    Attributes
    ----------
    market : str
        Target market (cn/us).
    lookback_days : int
        Days of history to analyze.
    ic_decline_threshold : float
        IC decline threshold for Watch status.
    icir_threshold : float
        ICIR threshold for degradation.
    rank_corr_instability_threshold : float
        Rank correlation instability threshold.
    """

    market: str = "cn"
    lookback_days: int = 365
    ic_decline_threshold: float = 0.05  # 5% decline
    icir_threshold: float = 0.5
    rank_corr_instability_threshold: float = 0.3

    def check_factor(self, factor_name: str, ic_history: pd.Series) -> FactorDecayReport:
        """Check a single factor for decay.

        Parameters
        ----------
        factor_name : str
            Factor name.
        ic_history : pd.Series
            Time series of IC values (index = date).

        Returns
        -------
        FactorDecayReport
            Decay report for this factor.
        """
        report = FactorDecayReport(factor_name=factor_name)

        if len(ic_history) < 5:
            report.status = DecayStatus.WATCH
            report.alerts.append("insufficient_data")
            report.recommendation = "Need at least 5 data points for decay analysis"
            return report

        # Calculate metrics
        report.ic_current = float(ic_history.iloc[-1])
        report.ic_6m_avg = float(ic_history.tail(126).mean())  # ~6 months
        report.ic_12m_avg = float(ic_history.tail(252).mean())  # ~12 months

        # IC trend (linear regression slope)
        x = np.arange(len(ic_history))
        slope, _ = np.polyfit(x, ic_history.values, 1)
        report.ic_trend = float(slope)

        # ICIR (mean / std)
        std = float(ic_history.std())
        report.icir_current = report.ic_current / std if std > 1e-10 else 0.0

        # Rank correlation instability
        rolling_corr = ic_history.rolling(63).apply(
            lambda x: np.corrcoef(x, np.arange(len(x)))[0, 1] if len(x) > 2 else 0
        )
        report.rank_corr_instability = float(rolling_corr.std())

        # Determine status
        alerts = []

        # Check IC decline
        if report.ic_trend < -self.ic_decline_threshold:
            alerts.append(f"IC declining: slope={report.ic_trend:.4f}")

        # Check ICIR
        if report.icir_current < self.icir_threshold:
            alerts.append(f"ICIR low: {report.icir_current:.4f} < {self.icir_threshold}")

        # Check 6m vs 12m average
        if report.ic_6m_avg < report.ic_12m_avg * 0.7:
            alerts.append(
                f"6m avg ({report.ic_6m_avg:.4f}) < 70% of 12m avg ({report.ic_12m_avg:.4f})"
            )

        # Check rank correlation instability
        if report.rank_corr_instability > self.rank_corr_instability_threshold:
            alerts.append(f"Rank correlation unstable: std={report.rank_corr_instability:.4f}")

        # Check negative IC
        if report.ic_current < 0:
            alerts.append(f"Current IC negative: {report.ic_current:.4f}")

        report.alerts = alerts

        # Determine status
        if len(alerts) >= 3 or report.ic_current < 0:
            report.status = DecayStatus.DOWNgrade
            report.recommendation = "Downgrade: Multiple decay signals or negative IC"
        elif len(alerts) >= 2:
            report.status = DecayStatus.DEGRADED
            report.recommendation = "Degraded: Significant decay detected"
        elif len(alerts) >= 1:
            report.status = DecayStatus.WATCH
            report.recommendation = "Watch: Early warning signs"
        else:
            report.status = DecayStatus.HEALTHY
            report.recommendation = "Healthy: No decay detected"

        return report

    def check_all_active_factors(self) -> list[FactorDecayReport]:
        """Check all Active factors for decay.

        Returns
        -------
        list[FactorDecayReport]
            List of decay reports for all Active factors.
        """
        from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

        registry = FactorRegistry()
        active_factors = registry.list_factors(stage=STAGE_ACTIVE)

        if not active_factors:
            # No active factors - return empty with note
            logger.info("no_active_factors_for_decay_check")
            return []

        # Load IC history from walk-forward results
        ic_history = self._load_ic_history_from_walkforward()

        reports = []
        for factor in active_factors:
            factor_name = factor["name"]
            factor_ic = ic_history.get(factor_name, pd.Series(dtype=float))

            if factor_ic.empty:
                # No history - mark as insufficient data, not healthy
                report = FactorDecayReport(factor_name=factor_name)
                report.status = DecayStatus.WATCH
                report.alerts.append("insufficient_data")
                report.recommendation = "Insufficient IC history for decay analysis"
                reports.append(report)
            else:
                report = self.check_factor(factor_name, factor_ic)
                reports.append(report)

        return reports

    # ------------------------------------------------------------------
    # IC history persistence
    # ------------------------------------------------------------------

    _HISTORY_DIR = Path("artifacts/ic_history")

    @property
    def _history_path(self) -> Path:
        return self._HISTORY_DIR / f"{self.market}_ic_history.json"

    def load_persistent_history(self) -> dict[str, pd.Series]:
        """Load IC history from the persistent artifact file."""
        if not self._history_path.exists():
            return {}
        try:
            with open(self._history_path) as f:
                raw = json.load(f)
            result = {}
            for name, entries in raw.items():
                if entries:
                    dates, ics = zip(*sorted(entries, key=lambda x: x[0]))
                    result[name] = pd.Series(ics, index=pd.to_datetime(dates))
            return result
        except Exception as e:
            logger.warning("failed_to_load_ic_history", error=str(e))
            return {}

    def save_persistent_history(self, ic_data: dict[str, pd.Series]) -> None:
        """Save IC history to the persistent artifact file."""
        self._HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        raw = {}
        for name, series in ic_data.items():
            raw[name] = [[str(d.date()), float(v)] for d, v in series.items()]
        with open(self._history_path, "w") as f:
            json.dump(raw, f, indent=2)
        logger.info("ic_history_saved", path=str(self._history_path), factors=len(raw))

    def build_history(self) -> dict[str, pd.Series]:
        """Build and persist IC history from all available sources.

        Merges existing persistent history with fresh data from:
        1. Factor validation records (per-factor IC)
        2. Walk-forward artifacts (model-level IC)

        Returns the merged IC history.
        """
        # Load existing persistent history
        existing = self.load_persistent_history()

        # Collect fresh data
        fresh = self._collect_fresh_ic_data()

        # Merge: for each factor, union the date→IC entries
        merged: dict[str, dict[str, float]] = {}
        for name, series in existing.items():
            merged[name] = {str(d.date()): float(v) for d, v in series.items()}

        for name, series in fresh.items():
            if name not in merged:
                merged[name] = {}
            for d, v in series.items():
                merged[name][str(d.date())] = float(v)

        # Convert back to Series
        result = {}
        for name, entries in merged.items():
            if entries:
                dates, ics = zip(*sorted(entries.items()))
                result[name] = pd.Series(ics, index=pd.to_datetime(dates))

        self.save_persistent_history(result)
        return result

    def _collect_fresh_ic_data(self) -> dict[str, pd.Series]:
        """Collect IC data from source systems (registry + walk-forward)."""
        ic_data: dict[str, list[tuple[str, float]]] = {}

        # Source 1: Per-factor IC from validation records
        try:
            from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

            registry = FactorRegistry()
            active_factors = registry.list_factors(stage=STAGE_ACTIVE)
            for factor in active_factors:
                validations = registry.get_validations(factor["id"])
                for v in validations:
                    if v.get("ic") is not None and v.get("market", "").lower() == self.market:
                        date = v.get("validated_at", "")
                        if date:
                            fname = factor["name"]
                            if fname not in ic_data:
                                ic_data[fname] = []
                            ic_data[fname].append((date[:10], float(v["ic"])))
        except Exception as e:
            logger.warning("failed_to_load_factor_validations", error=str(e))

        # Source 2: Model-level IC from walk-forward artifacts
        wf_dir = Path("artifacts/walk_forward")
        if wf_dir.exists():
            pattern = f"{self.market}_*.json"
            for f in sorted(wf_dir.glob(pattern)):
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    if data.get("market", self.market).lower() != self.market:
                        continue
                    model_key = f"model_{data.get('model_type', 'lgbm')}"
                    for split in data.get("splits", []):
                        if split.get("status") == "success" and split.get("ic") is not None:
                            date = split.get("test_start", "")
                            ic = split["ic"]
                            if model_key not in ic_data:
                                ic_data[model_key] = []
                            ic_data[model_key].append((date, ic))
                except Exception:
                    continue

        # Convert to Series
        result = {}
        for name, values in ic_data.items():
            if values:
                sorted_values = sorted(values, key=lambda x: x[0])
                dates, ics = zip(*sorted_values)
                result[name] = pd.Series(ics, index=pd.to_datetime(dates))

        return result

    def _load_ic_history_from_walkforward(self) -> dict[str, pd.Series]:
        """Load IC history — tries persistent cache first, then fresh collection.

        Returns dict of {factor_name: pd.Series of IC values over time}.
        """
        # Try persistent history first
        history = self.load_persistent_history()
        if history:
            return history

        # Fall back to fresh collection
        return self._collect_fresh_ic_data()

    def apply_status_changes(self, reports: list[FactorDecayReport]) -> dict[str, int]:
        """Apply status changes to factors based on decay reports.

        Parameters
        ----------
        reports : list[FactorDecayReport]
            Decay reports from check_all_active_factors().

        Returns
        -------
        dict[str, int]
            Count of status changes by type.
        """
        from src.research.factor_registry import (
            STAGE_RETIRED,
            STAGE_WATCH,
            FactorRegistry,
        )

        registry = FactorRegistry()
        changes = {"watch": 0, "downgrade": 0, "healthy": 0}

        for report in reports:
            # Find factor by name
            factors = registry.list_factors()
            factor = next((f for f in factors if f["name"] == report.factor_name), None)
            if not factor:
                continue

            factor_id = factor["id"]

            if report.status == DecayStatus.DOWNgrade:
                # Downgrade to Retired
                registry.update_stage(factor_id, STAGE_RETIRED)
                changes["downgrade"] += 1
                logger.info(
                    "factor_downgraded", factor=report.factor_name, reason=report.recommendation
                )
            elif report.status in (DecayStatus.WATCH, DecayStatus.DEGRADED):
                # Move to Watch
                registry.update_stage(factor_id, STAGE_WATCH)
                changes["watch"] += 1
                logger.info(
                    "factor_moved_to_watch", factor=report.factor_name, status=report.status.value
                )
            else:
                changes["healthy"] += 1

        return changes

    def generate_report(self, reports: list[FactorDecayReport]) -> dict[str, Any]:
        """Generate a summary report of all factor decay statuses.

        Parameters
        ----------
        reports : list[FactorDecayReport]
            Decay reports.

        Returns
        -------
        dict[str, Any]
            Summary report.
        """
        status_counts = {}
        for status in DecayStatus:
            status_counts[status.value] = sum(1 for r in reports if r.status == status)

        return {
            "market": self.market,
            "timestamp": datetime.now().isoformat(),
            "total_factors": len(reports),
            "status_distribution": status_counts,
            "factors_needing_attention": [
                r.to_dict()
                for r in reports
                if r.status in (DecayStatus.WATCH, DecayStatus.DEGRADED, DecayStatus.DOWNgrade)
            ],
            "recommendations": [
                {
                    "factor": r.factor_name,
                    "status": r.status.value,
                    "recommendation": r.recommendation,
                }
                for r in reports
                if r.status != DecayStatus.HEALTHY
            ],
        }
