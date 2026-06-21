"""Three-pillar market regime detection for dynamic exposure management.

The regime filter combines three independent signals:

1. **IC Decay** — Linear regression on recent cross-sectional ICs.
   A negative slope means the model is losing predictive power.

2. **Volatility Spike** — Short-term vs long-term vol ratio.
   Reuses ``check_volatility_regime`` from ``src/guardrails/rules.py``.

3. **Trend Filter** — Benchmark relative to its moving average.
   Below MA = bearish regime.

All three factors are combined conservatively: the **minimum** exposure
factor wins (i.e., any adverse signal reduces exposure).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.execution.signal_execution_config import SignalExecutionConfig
from src.guardrails.rules import check_volatility_regime

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeSignal:
    """Aggregated output of all three regime filter pillars.

    Attributes
    ----------
    is_favorable : bool
        True when no pillar reports an adverse condition.
    exposure_factor : float
        Multiplier in [0.0, 1.0] applied to all position weights.
        1.0 = full exposure, 0.0 = all cash.
    ic_trend_slope : float
        Slope of linear regression on recent ICs.
    vol_ratio : float
        Short-term / long-term volatility ratio.
    trend_below_ma : bool
        True when benchmark is below its moving average.
    reasons : list[str]
        Human-readable explanations for any adverse conditions.
    """

    is_favorable: bool
    exposure_factor: float
    ic_trend_slope: float
    vol_ratio: float
    trend_below_ma: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regime filter
# ---------------------------------------------------------------------------


class RegimeFilter:
    """Three-pillar market regime detection.

    Pillar 1 — **IC Decay**:
        Fits linear regression to rolling cross-sectional ICs.
        Negative slope beyond ``ic_decay_threshold`` indicates model decay.
        Exposure scales: 1.0 at threshold → 0.0 at 2× threshold.

    Pillar 2 — **Volatility Spike**:
        Reuses ``check_volatility_regime()`` from guardrails.
        When short-term vol exceeds long-term vol, exposure is reduced.

    Pillar 3 — **Trend Filter**:
        Compares benchmark (CSI300) to its MA. Below MA → reduced exposure.
    """

    def __init__(self, config: SignalExecutionConfig):
        self._cfg = config
        self._ic_lookback = config.ic_lookback_days
        self._ic_decay_threshold = config.ic_decay_threshold
        self._vol_ratio_threshold = config.vol_ratio_threshold
        self._trend_ma_window = config.trend_ma_window

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        ic_series: list[float],
        return_matrix: pd.DataFrame,
        benchmark_series: pd.Series | None,
        date: pd.Timestamp,
    ) -> RegimeSignal:
        """Evaluate all three pillars and return an aggregated regime signal.

        Parameters
        ----------
        ic_series : list[float]
            Historical cross-sectional IC values up to the current date,
            ordered chronologically.  Used by the IC decay pillar.
        return_matrix : pd.DataFrame
            Stock return matrix with DatetimeIndex rows and instrument
            columns.  Used by the volatility spike pillar.
        benchmark_series : pd.Series | None
            Benchmark price or cumulative-return series indexed by
            datetime.  Used by the trend filter pillar.
        date : pd.Timestamp
            Current rebalance date.

        Returns
        -------
        RegimeSignal
            Aggregated signal with the conservative (minimum) exposure
            factor across all three pillars.
        """
        reasons: list[str] = []
        factors: list[float] = []

        # --- Pillar 1: IC decay ---
        slope, ic_factor = self._check_ic_decay(ic_series)
        factors.append(ic_factor)
        if ic_factor < 1.0:
            reasons.append(
                f"IC decay: slope={slope:.4f} < threshold={self._ic_decay_threshold}, "
                f"factor={ic_factor:.2f}"
            )

        # --- Pillar 2: Volatility spike ---
        ratio, vol_factor = self._check_vol_spike(return_matrix, date)
        factors.append(vol_factor)
        if vol_factor < 1.0:
            reasons.append(
                f"Vol spike: ratio={ratio:.2f} > threshold={self._vol_ratio_threshold}, "
                f"factor={vol_factor:.2f}"
            )

        # --- Pillar 3: Trend filter ---
        below_ma, trend_factor = self._check_trend(benchmark_series, date)
        factors.append(trend_factor)
        if trend_factor < 1.0:
            reasons.append(
                f"Bear trend: benchmark below MA-{self._trend_ma_window}, "
                f"factor={trend_factor:.2f}"
            )

        # Conservative aggregation: minimum factor wins
        exposure_factor = min(factors) if factors else 1.0

        return RegimeSignal(
            is_favorable=exposure_factor >= 1.0,
            exposure_factor=exposure_factor,
            ic_trend_slope=slope,
            vol_ratio=ratio if ratio != 0 else 1.0,
            trend_below_ma=below_ma,
            reasons=reasons,
        )

    # ------------------------------------------------------------------
    # Pillar implementations
    # ------------------------------------------------------------------

    def _check_ic_decay(self, ic_series: list[float]) -> tuple[float, float]:
        """Fit linear regression to recent ICs.

        Returns
        -------
        (slope, exposure_factor)
            slope : float
                Slope of linear fit (positive = improving).
            exposure_factor : float
                1.0 when slope >= 0, scales linearly to 0.0 when
                slope <= 2 × ic_decay_threshold.
        """
        if len(ic_series) < 10:
            return 0.0, 1.0  # Not enough data → assume favorable

        recent = np.array(ic_series[-self._ic_lookback:], dtype=float)
        x = np.arange(len(recent), dtype=float)
        # Linear regression: y = a + b*x, slope = b
        slope = float(np.polyfit(x, recent, 1)[0])

        if slope >= 0:
            return slope, 1.0

        # Scale: at threshold → 1.0, at 2× threshold → 0.0
        factor = max(0.0, min(1.0, 1.0 - abs(slope / self._ic_decay_threshold)))
        return slope, factor

    def _check_vol_spike(
        self, return_matrix: pd.DataFrame, date: pd.Timestamp
    ) -> tuple[float, float]:
        """Compute cross-sectional average vol20 / vol252 ratio.

        Uses the cross-sectional mean daily return as a proxy for the
        equal-weight portfolio return, then computes volatility over
        short (20-day) and long (252-day) windows.

        Returns
        -------
        (ratio, exposure_factor)
            ratio : float
                vol20 / vol252.  1.0 = normal, > 2.0 = elevated.
            exposure_factor : float
                Scales from 1.0 at threshold down to 0.3 at extremes.
        """
        if date not in return_matrix.index:
            return 1.0, 1.0

        hist = return_matrix.loc[:date]
        if len(hist) < 252:
            return 1.0, 1.0

        # Cross-sectional average daily return (equal-weight portfolio proxy)
        cs_ret = hist.mean(axis=1)
        vol20 = float(cs_ret.tail(20).std())
        vol252 = float(cs_ret.tail(252).std())

        result = check_volatility_regime(
            vol20, vol252, threshold=self._vol_ratio_threshold
        )
        ratio = vol20 / vol252 if vol252 > 1e-10 else 1.0

        if result["passed"]:
            return ratio, 1.0

        # Scale exposure: at threshold → 1.0, at 2× threshold → 0.5
        # Floor at 0.3 to avoid going to zero from a single vol spike
        if ratio <= 0:
            return ratio, 0.3
        factor = max(0.3, min(1.0, self._vol_ratio_threshold / ratio))
        return ratio, factor

    def _check_trend(
        self, benchmark_series: pd.Series | None, date: pd.Timestamp
    ) -> tuple[bool, float]:
        """Check if benchmark is in a downtrend (below its MA).

        Returns
        -------
        (below_ma, exposure_factor)
            below_ma : bool
                True when the current benchmark value is below its MA.
            exposure_factor : float
                1.0 when above MA, scales down as deviation below MA grows.
                Floor at 0.5 (never go to zero on trend alone).
        """
        if benchmark_series is None:
            return False, 1.0

        # Find the benchmark value at or before `date`
        valid_dates = benchmark_series.index[benchmark_series.index <= date]
        if len(valid_dates) < self._trend_ma_window:
            return False, 1.0

        hist = benchmark_series.loc[valid_dates].tail(self._trend_ma_window)
        if len(hist) < self._trend_ma_window:
            return False, 1.0

        ma = float(hist.mean())
        current = float(hist.iloc[-1])

        if current >= ma:
            return False, 1.0

        # How far below MA: each 2% deviation reduces factor by 0.1
        deviation = abs(current - ma) / ma if ma > 0 else 0.0
        # Scale: deviation 0% → 1.0, deviation 10% → 0.5
        factor = max(0.5, min(1.0, 1.0 - deviation * 5))
        return True, factor
