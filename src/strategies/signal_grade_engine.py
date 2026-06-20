"""Signal Grade Engine — assigns AAA/AA/A/V/VV/VVV grades based on cross-sectional
model ranking, and computes historical signal performance (10-day forward returns).

Design:
- The model produces a score for each stock every prediction period (e.g., 10 days).
- Stocks are ranked cross-sectionally by score.
- Grades are assigned based on rank percentile:
    AAA = Top N (strongest buy)
    AA  = Top 2N
    A   = Top 3N
    V   = Bottom 3N
    VV  = Bottom 2N
    VVV = Bottom N (strongest sell)
- Default N=10, configurable via `step_size`.

Performance tracking:
- For each historical occurrence of each grade, compute the 10-day forward return.
- Accumulate returns per grade to show how well each signal class predicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

__all__ = [
    "SignalGrade",
    "SignalPerformance",
    "SignalProvenance",
    "StockScore",
    "SignalGradeEngine",
    "MIN_OCCURRENCES_FOR_QUALIFICATION",
    "compute_direction_adjusted_hit_rate",
    "compute_confidence_interval_95",
    "determine_qualification",
]

# ---------------------------------------------------------------------------
# Grade definitions
# ---------------------------------------------------------------------------

GRADES = ["AAA", "AA", "A", "V", "VV", "VVV"]

# Chinese display names
GRADE_NAMES = {
    "AAA": "极强买入",
    "AA": "强买入",
    "A": "买入",
    "V": "卖出",
    "VV": "强卖出",
    "VVV": "极强卖出",
}

# Grade weights for scoring: positive for buy signals, negative for sell signals
# Higher absolute value = stronger signal
GRADE_WEIGHTS = {
    "AAA": 3.0,
    "AA": 2.0,
    "A": 1.0,
    "V": -1.0,
    "VV": -2.0,
    "VVV": -3.0,
}


@dataclass
class StockScore:
    """Model prediction effectiveness score for a single stock.

    The score measures how well the model's signals predict actual price
    movements for this specific stock. Higher score = model is more effective.

    Scoring logic:
    - AAA/AA/A (buy signals): positive cumulative return → positive contribution
    - V/VV/VVV (sell signals): negative cumulative return → positive contribution
      (model correctly predicted decline)
    - Weighted by signal strength (AAA=3, AA=2, A=1, V=-1, VV=-2, VVV=-3)
    """

    symbol: str
    market: str
    weighted_score: float  # Overall effectiveness score
    grade_details: dict[str, dict[str, float]]  # Per-grade stats
    total_signals: int  # Total signal occurrences across all grades
    data_start: str  # First signal date
    data_end: str  # Last signal date

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "weighted_score": round(self.weighted_score, 4),
            "grade_details": self.grade_details,
            "total_signals": self.total_signals,
            "data_start": self.data_start,
            "data_end": self.data_end,
        }


@dataclass(frozen=True)
class SignalProvenance:
    """Immutable provenance metadata tracing a signal back to its model run."""

    model_version_id: str
    run_id: str
    prediction_checksum: str
    snapshot_id: str
    validity_expiry: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version_id": self.model_version_id,
            "run_id": self.run_id,
            "prediction_checksum": self.prediction_checksum,
            "snapshot_id": self.snapshot_id,
            "validity_expiry": self.validity_expiry,
        }


@dataclass
class SignalGrade:
    """Signal grade for a single stock on a single date."""

    symbol: str
    date: str
    grade: str  # AAA, AA, A, V, VV, VVV, or "" if not in any tier
    rank: int  # 0-based rank in universe
    total_stocks: int
    score: float
    percentile: float  # 0-100
    provenance: SignalProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "date": self.date,
            "grade": self.grade,
            "rank": self.rank,
            "total_stocks": self.total_stocks,
            "score": round(self.score, 4) if not math.isnan(self.score) else None,
            "percentile": round(self.percentile, 1),
        }
        if self.provenance is not None:
            result["provenance"] = self.provenance.to_dict()
        return result


@dataclass
class SignalPerformance:
    """Historical performance statistics for a signal grade."""

    grade: str
    total_occurrences: int
    positive_count: int
    negative_count: int
    win_rate: float  # positive / total
    mean_return: float  # mean 10-day forward return
    cumulative_return: float  # sum of all 10-day returns (adjusted for holding period overlap)
    median_return: float
    max_return: float
    min_return: float
    avg_score: float  # average model score when this grade was assigned
    provenance: SignalProvenance | None = None
    # Evidence fields (requirements 39-41)
    model_version_id: str = ""
    policy_version: str = ""
    direction_adjusted_hit_rate: float = 0.0
    benchmark_excess_return: float = 0.0
    cost_adjusted_return: float = 0.0
    confidence_interval_95: list[float] = field(default_factory=lambda: [0.0, 0.0])
    qualification_status: str = ""  # "qualified", "unqualified", "excluded", "failed"
    failure_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "grade": self.grade,
            "grade_name": GRADE_NAMES.get(self.grade, ""),
            "total_occurrences": self.total_occurrences,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "win_rate": round(self.win_rate, 4),
            "mean_return": round(self.mean_return, 6),
            "cumulative_return": round(self.cumulative_return, 4),
            "median_return": round(self.median_return, 6),
            "max_return": round(self.max_return, 6),
            "min_return": round(self.min_return, 6),
            "avg_score": round(self.avg_score, 4),
            # Evidence fields
            "model_version_id": self.model_version_id,
            "policy_version": self.policy_version,
            "direction_adjusted_hit_rate": round(self.direction_adjusted_hit_rate, 4),
            "benchmark_excess_return": round(self.benchmark_excess_return, 6),
            "cost_adjusted_return": round(self.cost_adjusted_return, 6),
            "confidence_interval_95": [
                round(self.confidence_interval_95[0], 6),
                round(self.confidence_interval_95[1], 6),
            ],
            "qualification_status": self.qualification_status,
            "failure_reasons": list(self.failure_reasons),
        }
        if self.provenance is not None:
            result["provenance"] = self.provenance.to_dict()
        return result


# ---------------------------------------------------------------------------
# Evidence helpers (requirements 39-41)
# ---------------------------------------------------------------------------

# Minimum observation count for a grade to be considered qualified
MIN_OCCURRENCES_FOR_QUALIFICATION = 5


def compute_direction_adjusted_hit_rate(
    returns: np.ndarray, grade: str
) -> float:
    """Compute hit rate adjusted for signal direction.

    For buy grades (AAA/AA/A), a 'hit' is a positive return.
    For sell grades (VVV/VV/V), a 'hit' is a negative return.
    """
    if len(returns) == 0:
        return 0.0
    if grade in ("AAA", "AA", "A"):
        return float(np.sum(returns > 0) / len(returns))
    if grade in ("V", "VV", "VVV"):
        return float(np.sum(returns < 0) / len(returns))
    return 0.0


def compute_confidence_interval_95(
    returns: np.ndarray,
) -> list[float]:
    """Compute 95% confidence interval for mean return using t-distribution.

    For small samples, uses the t critical value. For n >= 30, approximates
    with z = 1.96.
    Returns [lower, upper].
    """
    n = len(returns)
    if n < 2:
        mean = float(returns.mean()) if n == 1 else 0.0
        return [mean, mean]
    mean = float(np.mean(returns))
    std_err = float(np.std(returns, ddof=1) / np.sqrt(n))
    # t critical value for 95% CI: use 1.96 for large n, look up for small n
    if n >= 30:
        t_crit = 1.96
    else:
        # Approximate t critical values for common small sample sizes (df = n-1)
        # Two-tailed 95% CI
        _t_table = {
            1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
            6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
            11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
            16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
            21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
            26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
        }
        t_crit = _t_table.get(n - 1, 1.96)
    return [mean - t_crit * std_err, mean + t_crit * std_err]


def determine_qualification(
    total_occurrences: int,
    returns: np.ndarray | None = None,
) -> tuple[str, list[str]]:
    """Determine qualification status and failure reasons.

    Returns (status, failure_reasons).
    Status is one of: "qualified", "unqualified", "excluded", "failed".
    """
    reasons: list[str] = []
    if total_occurrences == 0:
        return "excluded", ["no_signal_occurrences"]
    if total_occurrences < MIN_OCCURRENCES_FOR_QUALIFICATION:
        reasons.append(
            f"insufficient_observations: {total_occurrences} < {MIN_OCCURRENCES_FOR_QUALIFICATION}"
        )
        return "unqualified", reasons
    if returns is not None and len(returns) > 0:
        nan_ratio = float(np.sum(np.isnan(returns)) / len(returns))
        if nan_ratio > 0.5:
            reasons.append(f"high_nan_ratio: {nan_ratio:.1%}")
            return "failed", reasons
    return "qualified", []


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SignalGradeEngine:
    """Computes signal grades and historical performance for stocks.

    Usage::

        engine = SignalGradeEngine(step_size=10)
        # Get current grade for a stock
        grade = engine.get_grade("AAPL", pred_score_series, "2026-06-17")
        # Get historical performance for a stock
        perf = engine.get_performance("AAPL", market="us")
    """

    def __init__(self, step_size: int = 10):
        """
        Parameters
        ----------
        step_size : int
            The minimum unit for grade tiers. Default 10 means:
            AAA=Top10, AA=Top20, A=Top30, V=Bottom30, VV=Bottom20, VVV=Bottom10
            If step_size=20: AAA=Top20, AA=Top40, A=Top60, etc.

        Raises
        ------
        ValueError
            If step_size <= 0.
        """
        if step_size <= 0:
            raise ValueError(f"step_size must be positive, got {step_size}")
        self.step_size = step_size

    # ------------------------------------------------------------------
    # Grade computation
    # ------------------------------------------------------------------

    def compute_grade(
        self,
        symbol: str,
        pred_score: pd.Series,
        date: str | None = None,
    ) -> SignalGrade:
        """Compute the signal grade for a single stock.

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        pred_score : pd.Series
            Cross-sectional model scores indexed by instrument, sorted descending.
        date : str, optional
            Date string for the grade.

        Returns
        -------
        SignalGrade
        """
        if isinstance(pred_score, pd.DataFrame):
            pred_score = pred_score.iloc[:, 0]

        # Filter out NaN values before sorting to prevent NaN stocks
        # from getting incorrect grades (NaN sorts to top with ascending=False)
        pred_score = pred_score.dropna().sort_values(ascending=False)
        total = len(pred_score)

        if total == 0 or symbol not in pred_score.index:
            return SignalGrade(
                symbol=symbol,
                date=date or "",
                grade="",
                rank=-1,
                total_stocks=total,
                score=float("nan"),
                percentile=0.0,
            )

        rank = int(pred_score.index.get_loc(symbol))
        score = float(pred_score.iloc[rank])
        percentile = (1.0 - rank / total) * 100 if total > 0 else 0.0

        grade = self._rank_to_grade(rank, total)

        return SignalGrade(
            symbol=symbol,
            date=date or "",
            grade=grade,
            rank=rank,
            total_stocks=total,
            score=score,
            percentile=percentile,
        )

    def _rank_to_grade(self, rank: int, total: int) -> str:
        """Convert a 0-based rank to a signal grade.

        For small universes (total < 6 * step_size), tiers are scaled
        proportionally to avoid overlap between buy and sell grades.
        """
        n = self.step_size

        # Scale down tiers if universe is too small for 6 non-overlapping tiers
        if total < 6 * n:
            n = max(1, total // 6)

        # Buy grades (top of the ranking)
        if rank < n:
            return "AAA"
        if rank < 2 * n:
            return "AA"
        if rank < 3 * n:
            return "A"

        # Sell grades (bottom of the ranking)
        if rank >= total - n:
            return "VVV"
        if rank >= total - 2 * n:
            return "VV"
        if rank >= total - 3 * n:
            return "V"

        return ""  # Middle zone, no grade

    def get_grade_for_date(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        target_date: str,
        provenance: SignalProvenance | None = None,
    ) -> SignalGrade:
        """Get the signal grade for a stock on a specific date.

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        pred_df : pd.DataFrame
            Full prediction DataFrame with MultiIndex (datetime, instrument).
        target_date : str
            ISO date string to evaluate.
        provenance : SignalProvenance, optional
            Provenance metadata to attach to the resulting grade.

        Returns
        -------
        SignalGrade
        """
        try:
            # Filter to the target date
            dates = pred_df.index.get_level_values("datetime")
            target_dt = pd.Timestamp(target_date)

            # Find the closest date on or before target
            available_dates = dates.unique()
            valid_dates = available_dates[available_dates <= target_dt]
            if len(valid_dates) == 0:
                valid_dates = available_dates

            closest_date = valid_dates.max()
            day_preds = pred_df.xs(closest_date, level="datetime")
            pred_score = day_preds.iloc[:, 0].sort_values(ascending=False)

            grade = self.compute_grade(symbol, pred_score, date=str(closest_date.date()))
            if provenance is not None:
                grade.provenance = provenance
            return grade

        except Exception as exc:
            logger.warning("grade_computation_failed", symbol=symbol, error=str(exc))
            return SignalGrade(
                symbol=symbol, date=target_date, grade="",
                rank=-1, total_stocks=0, score=float("nan"), percentile=0.0,
                provenance=provenance,
            )

    # ------------------------------------------------------------------
    # Historical grades for a stock
    # ------------------------------------------------------------------

    def get_historical_grades(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        start_date: str | None = None,
        end_date: str | None = None,
        frequency_days: int = 10,
    ) -> list[SignalGrade]:
        """Get historical signal grades for a stock at trading frequency.

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        pred_df : pd.DataFrame
            Full prediction DataFrame with MultiIndex (datetime, instrument).
        start_date : str, optional
            Start date filter.
        end_date : str, optional
            End date filter.
        frequency_days : int
            Trading frequency in days. Default 10 = compute grade every 10 trading days.
            This matches the model's prediction horizon (10-day forward return).

        Returns
        -------
        list[SignalGrade]
            List of grades, one per trading period.
        """
        try:
            if symbol not in pred_df.index.get_level_values("instrument").unique():
                return []

            # Get all dates
            dates = pred_df.index.get_level_values("datetime").unique()

            if start_date:
                dates = dates[dates >= pd.Timestamp(start_date)]
            if end_date:
                dates = dates[dates <= pd.Timestamp(end_date)]

            dates = sorted(dates)

            # Sample at frequency_days intervals (every N trading days)
            sampled_dates = dates[::frequency_days]

            grades = []
            for dt in sampled_dates:
                try:
                    day_preds = pred_df.xs(dt, level="datetime")
                    pred_score = day_preds.iloc[:, 0].sort_values(ascending=False)
                    grade = self.compute_grade(symbol, pred_score, date=str(dt.date()))
                    if grade.grade:  # Only include dates where stock has a grade
                        grades.append(grade)
                except Exception:
                    continue

            return grades

        except Exception as exc:
            logger.warning("historical_grades_failed", symbol=symbol, error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Signal performance statistics
    # ------------------------------------------------------------------

    def compute_performance(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        price_df: pd.DataFrame | None = None,
        market: str = "us",
        forward_days: int = 10,
        provenance: SignalProvenance | None = None,
        model_version_id: str = "",
        policy_version: str = "",
        benchmark_return: float = 0.0,
        cost_bps: float = 10.0,
    ) -> dict[str, SignalPerformance]:
        """Compute historical signal performance for a stock.

        For each grade occurrence (at 10-day trading frequency), compute the
        actual forward return over `forward_days` trading days. Then aggregate
        by grade.

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        pred_df : pd.DataFrame
            Full prediction DataFrame with MultiIndex (datetime, instrument).
        price_df : pd.DataFrame, optional
            Price DataFrame with $close column. If None, fetched from Qlib.
        market : str
            Market identifier for Qlib data fetch.
        forward_days : int
            Number of days to look forward for return computation.
        provenance : SignalProvenance, optional
            Provenance metadata to attach to each resulting performance record.
        model_version_id : str
            Model version identifier for evidence tracking.
        policy_version : str
            Grade policy version string.
        benchmark_return : float
            Annualized benchmark return for excess return computation (e.g., 0.10 for 10%).
        cost_bps : float
            Round-trip transaction cost in basis points (default 10 bps).

        Returns
        -------
        dict[str, SignalPerformance]
            Performance stats keyed by grade (AAA, AA, A, V, VV, VVV).
        """
        # Get historical grades at daily frequency
        grades = self.get_historical_grades(symbol, pred_df, frequency_days=1)
        if not grades:
            return {}

        # Get price data for forward return computation
        if price_df is None:
            price_df = self._fetch_prices(symbol, market)

        if price_df is None or price_df.empty:
            return {}

        # Compute forward returns for each grade occurrence
        grade_returns: dict[str, list[float]] = {g: [] for g in GRADES}
        grade_scores: dict[str, list[float]] = {g: [] for g in GRADES}

        # Drop NaN values from price data
        close_prices = price_df.iloc[:, 0] if isinstance(price_df, pd.DataFrame) else price_df
        close_prices = close_prices.dropna()

        for sg in grades:
            if not sg.grade:
                continue

            # Find the price on the grade date
            try:
                grade_date = pd.Timestamp(sg.date)

                # Find price on grade date
                if grade_date in close_prices.index:
                    entry_price = float(close_prices.loc[grade_date])
                else:
                    # Find closest date
                    mask = close_prices.index <= grade_date
                    if mask.any():
                        entry_price = float(close_prices.loc[mask].iloc[-1])
                    else:
                        continue

                # Find price `forward_days` later
                future_dates = close_prices.index[close_prices.index > grade_date]
                if len(future_dates) < forward_days:
                    continue
                exit_price = float(close_prices.iloc[close_prices.index.get_loc(grade_date) + forward_days])

                if entry_price > 0 and not pd.isna(entry_price) and not pd.isna(exit_price):
                    forward_return = (exit_price - entry_price) / entry_price
                    grade_returns[sg.grade].append(forward_return)
                    grade_scores[sg.grade].append(sg.score)

            except Exception:
                continue

        # Aggregate performance per grade
        results: dict[str, SignalPerformance] = {}
        cost_decimal = cost_bps / 10000.0  # convert bps to decimal
        # Per-period benchmark return (annualized → per forward_days period)
        per_period_benchmark = benchmark_return * (forward_days / 252.0) if benchmark_return else 0.0

        for grade in GRADES:
            returns = grade_returns[grade]
            scores = grade_scores[grade]

            if not returns:
                qual_status, fail_reasons = determine_qualification(0)
                results[grade] = SignalPerformance(
                    grade=grade, total_occurrences=0,
                    positive_count=0, negative_count=0,
                    win_rate=0.0, mean_return=0.0, cumulative_return=0.0,
                    median_return=0.0, max_return=0.0, min_return=0.0,
                    avg_score=0.0, provenance=provenance,
                    model_version_id=model_version_id,
                    policy_version=policy_version,
                    direction_adjusted_hit_rate=0.0,
                    benchmark_excess_return=0.0,
                    cost_adjusted_return=0.0,
                    confidence_interval_95=[0.0, 0.0],
                    qualification_status=qual_status,
                    failure_reasons=fail_reasons,
                )
                continue

            # Filter out NaN values
            arr = np.array(returns)
            valid_mask = np.isfinite(arr)
            arr = arr[valid_mask]
            valid_scores = np.array(scores)[valid_mask] if scores else np.array([])

            if len(arr) == 0:
                qual_status, fail_reasons = determine_qualification(0)
                results[grade] = SignalPerformance(
                    grade=grade, total_occurrences=0,
                    positive_count=0, negative_count=0,
                    win_rate=0.0, mean_return=0.0, cumulative_return=0.0,
                    median_return=0.0, max_return=0.0, min_return=0.0,
                    avg_score=0.0, provenance=provenance,
                    model_version_id=model_version_id,
                    policy_version=policy_version,
                    direction_adjusted_hit_rate=0.0,
                    benchmark_excess_return=0.0,
                    cost_adjusted_return=0.0,
                    confidence_interval_95=[0.0, 0.0],
                    qualification_status=qual_status,
                    failure_reasons=fail_reasons,
                )
                continue

            # Adjust cumulative return for holding period overlap
            # Each signal holds for `forward_days` days, so signals overlap.
            # Effective cumulative = sum(returns) / forward_days
            raw_cumulative = float(np.sum(arr))
            adjusted_cumulative = raw_cumulative / forward_days if forward_days > 0 else raw_cumulative

            # Evidence computations
            mean_ret = float(np.mean(arr))
            dir_hit_rate = compute_direction_adjusted_hit_rate(arr, grade)
            ci = compute_confidence_interval_95(arr)
            benchmark_excess = mean_ret - per_period_benchmark
            cost_adj = mean_ret - cost_decimal
            qual_status, fail_reasons = determine_qualification(len(arr), arr)

            results[grade] = SignalPerformance(
                grade=grade,
                total_occurrences=len(arr),
                positive_count=int(np.sum(arr > 0)),
                negative_count=int(np.sum(arr < 0)),
                win_rate=float(np.sum(arr > 0) / len(arr)),
                mean_return=mean_ret,
                cumulative_return=adjusted_cumulative,
                median_return=float(np.median(arr)),
                max_return=float(np.max(arr)),
                min_return=float(np.min(arr)),
                avg_score=float(np.mean(valid_scores)) if len(valid_scores) > 0 else 0.0,
                provenance=provenance,
                model_version_id=model_version_id,
                policy_version=policy_version,
                direction_adjusted_hit_rate=dir_hit_rate,
                benchmark_excess_return=benchmark_excess,
                cost_adjusted_return=cost_adj,
                confidence_interval_95=ci,
                qualification_status=qual_status,
                failure_reasons=fail_reasons,
            )

        return results

    def compute_total_score(self, performance: dict[str, SignalPerformance]) -> dict[str, Any]:
        """Compute a total score describing how well signals predict this stock.

        Scoring logic (uses MEAN return per signal, not cumulative):
        - Buy signals (AAA/AA/A): mean_return > 0 → positive contribution
        - Sell signals (V/VV/VVV): mean_return < 0 → positive contribution (correctly predicted decline)
        - Weighted by signal strength and occurrence count

        Returns:
            dict with total_score, buy_score, sell_score, grade, description
        """
        from src.strategies.signal_grade_engine import GRADE_WEIGHTS

        buy_score = 0.0
        sell_score = 0.0
        buy_count = 0
        sell_count = 0
        total_signals = 0

        for grade, perf in performance.items():
            if perf.total_occurrences == 0:
                continue

            weight = GRADE_WEIGHTS.get(grade, 0)
            total_signals += perf.total_occurrences

            # Use mean_return (average per signal), not cumulative
            mean_ret = perf.mean_return

            if weight > 0:  # Buy signals
                # Positive mean return = good for buy
                buy_score += mean_ret * weight
                buy_count += perf.total_occurrences
            elif weight < 0:  # Sell signals
                # Negative mean return = good for sell (model correctly predicted decline)
                sell_score += abs(mean_ret) * abs(weight)
                sell_count += perf.total_occurrences

        # Normalize by signal count to get per-signal average
        avg_buy_score = buy_score / buy_count if buy_count > 0 else 0.0
        avg_sell_score = sell_score / sell_count if sell_count > 0 else 0.0
        total_score = avg_buy_score + avg_sell_score

        # Grade the total score (stricter thresholds)
        if total_score > 0.03:
            grade = "A+"
            description = "模型对此股票高度有效"
        elif total_score > 0.015:
            grade = "A"
            description = "模型对此股票有效"
        elif total_score > 0.005:
            grade = "B"
            description = "模型对此股票中度有效"
        elif total_score > 0.0:
            grade = "C"
            description = "模型对此股票轻微有效"
        elif total_score > -0.005:
            grade = "D"
            description = "模型对此股票无效"
        else:
            grade = "F"
            description = "模型对此股票反向有效（谨慎使用）"

        return {
            "total_score": round(total_score, 6),
            "buy_score": round(avg_buy_score, 6),
            "sell_score": round(avg_sell_score, 6),
            "grade": grade,
            "description": description,
            "total_signals": total_signals,
            "buy_signals": buy_count,
            "sell_signals": sell_count,
        }

    def _fetch_prices(self, symbol: str, market: str) -> pd.DataFrame | None:
        """Fetch close prices from Qlib."""
        try:
            from qlib.data import D

            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            df = D.features(
                [symbol],
                ["$close"],
                start_time="2020-01-01",
            )
            if df.empty:
                return None

            # Extract single stock
            if hasattr(df.index, 'get_level_values') and 'instrument' in df.index.names:
                df = df.xs(symbol, level="instrument")

            return df

        except Exception as exc:
            logger.warning("price_fetch_failed", symbol=symbol, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Stock scoring (model effectiveness per stock)
    # ------------------------------------------------------------------

    def compute_stock_score(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        market: str = "us",
        forward_days: int = 10,
    ) -> StockScore:
        """Compute the model effectiveness score for a single stock.

        Scoring logic:
        - AAA/AA/A signals: cumulative_return contributes positively
          (model correctly predicted price increase)
        - V/VV/VVV signals: -cumulative_return contributes positively
          (model correctly predicted price decrease)
        - Each grade's contribution is weighted by signal strength

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        pred_df : pd.DataFrame
            Full prediction DataFrame.
        market : str
            Market identifier.
        forward_days : int
            Holding period for return computation.

        Returns
        -------
        StockScore
        """
        # Get performance data
        perf = self.compute_performance(
            symbol=symbol,
            pred_df=pred_df,
            market=market,
            forward_days=forward_days,
        )

        grade_details = {}
        weighted_sum = 0.0
        total_weight = 0.0
        total_signals = 0

        for grade in GRADES:
            p = perf.get(grade)
            if p is None or p.total_occurrences == 0:
                grade_details[grade] = {
                    "occurrences": 0,
                    "win_rate": 0.0,
                    "mean_return": 0.0,
                    "cumulative_return": 0.0,
                    "contribution": 0.0,
                }
                continue

            # For buy signals (AAA/AA/A): positive cumulative = good
            # For sell signals (V/VV/VVV): negative cumulative = good
            # Contribution = cumulative_return * sign(grade_weight)
            # This way, for VVV with -3 weight, a -5% cumulative gives +15% contribution
            grade_weight = GRADE_WEIGHTS[grade]
            if grade_weight > 0:
                # Buy signal: positive return is good
                contribution = p.cumulative_return * grade_weight
            else:
                # Sell signal: negative return is good (flip sign)
                contribution = (-p.cumulative_return) * abs(grade_weight)

            weighted_sum += contribution
            total_weight += abs(grade_weight) * p.total_occurrences
            total_signals += p.total_occurrences

            grade_details[grade] = {
                "occurrences": p.total_occurrences,
                "win_rate": round(p.win_rate, 4),
                "mean_return": round(p.mean_return, 6),
                "cumulative_return": round(p.cumulative_return, 4),
                "contribution": round(contribution, 4),
            }

        # Normalize weighted score
        final_score = weighted_sum / max(total_signals, 1)

        # Get date range
        grades = self.get_historical_grades(symbol, pred_df, frequency_days=1)
        data_start = grades[0].date if grades else ""
        data_end = grades[-1].date if grades else ""

        return StockScore(
            symbol=symbol,
            market=market,
            weighted_score=final_score,
            grade_details=grade_details,
            total_signals=total_signals,
            data_start=data_start,
            data_end=data_end,
        )

    def compute_universe_scores(
        self,
        pred_df: pd.DataFrame,
        market: str = "us",
        forward_days: int = 10,
        top_n: int = 0,
    ) -> list[StockScore]:
        """Compute model effectiveness scores for all stocks in the universe.

        Parameters
        ----------
        pred_df : pd.DataFrame
            Full prediction DataFrame.
        market : str
            Market identifier.
        forward_days : int
            Holding period.
        top_n : int
            If > 0, only compute for top N stocks by absolute weighted score.
            0 = compute for all stocks (slow).

        Returns
        -------
        list[StockScore]
            Sorted by weighted_score descending (best first).
        """
        instruments = pred_df.index.get_level_values("instrument").unique()

        # First pass: quick scan to estimate signal counts
        quick_scores = []
        for symbol in instruments:
            try:
                grades = self.get_historical_grades(symbol, pred_df, frequency_days=1)
                if grades:
                    quick_scores.append((symbol, len(grades)))
            except Exception:
                continue

        # Sort by signal count (more data = more reliable score)
        quick_scores.sort(key=lambda x: x[1], reverse=True)

        # Limit to top_n if specified
        if top_n > 0:
            quick_scores = quick_scores[:top_n]

        # Second pass: compute full scores
        scores = []
        for symbol, _ in quick_scores:
            try:
                score = self.compute_stock_score(
                    symbol=symbol,
                    pred_df=pred_df,
                    market=market,
                    forward_days=forward_days,
                )
                scores.append(score)
            except Exception as exc:
                logger.debug("stock_score_failed", symbol=symbol, error=str(exc))
                continue

        # Sort by weighted score descending
        scores.sort(key=lambda s: s.weighted_score, reverse=True)

        return scores

    # ------------------------------------------------------------------
    # Daily signal data for chart overlay
    # ------------------------------------------------------------------

    def get_daily_signal_series(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get daily signal data for chart overlay.

        Returns a list of data points with:
        - date: ISO date string
        - percentile: 0-100 rank percentile
        - grade: AAA/AA/A/V/VV/VVV or "" if middle zone
        - score: model prediction score
        - rank: 0-based rank
        - total: total stocks in universe

        This is designed for rendering as a colored area/line below the price chart.
        """
        try:
            if symbol not in pred_df.index.get_level_values("instrument").unique():
                return []

            dates = pred_df.index.get_level_values("datetime").unique()

            if start_date:
                dates = dates[dates >= pd.Timestamp(start_date)]
            if end_date:
                dates = dates[dates <= pd.Timestamp(end_date)]

            dates = sorted(dates)
            result = []

            for dt in dates:
                try:
                    day_preds = pred_df.xs(dt, level="datetime")
                    scores = day_preds.iloc[:, 0].sort_values(ascending=False)
                    total = len(scores)

                    if symbol not in scores.index:
                        continue

                    rank = list(scores.index).index(symbol)
                    score = float(scores.iloc[rank])
                    percentile = (1.0 - rank / total) * 100 if total > 0 else 0.0
                    grade = self._rank_to_grade(rank, total)

                    result.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "percentile": round(percentile, 1),
                        "grade": grade,
                        "score": round(score, 4),
                        "rank": rank,
                        "total": total,
                    })
                except Exception:
                    continue

            return result

        except Exception as exc:
            logger.warning("daily_signal_series_failed", symbol=symbol, error=str(exc))
            return []

    # ------------------------------------------------------------------
    # K-line markers for frontend
    # ------------------------------------------------------------------

    def get_kline_markers(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        start_date: str | None = None,
        price_df: pd.DataFrame | None = None,
        market: str = "us",
        forward_days: int = 10,
    ) -> list[dict[str, Any]]:
        """Generate K-line chart markers for all historical signal grades.

        Returns a list of marker dicts compatible with lightweight-charts addMarkers.

        Each marker has:
        - time: ISO date string
        - position: "belowBar" for buy grades, "aboveBar" for sell grades
        - color: green for buy, red for sell
        - shape: "arrowUp" for buy, "arrowDown" for sell
        - text: grade label (AAA, AA, A, V, VV, VVV)
        - tooltip: rich text with identity, timestamp, rank, score, grade,
          qualification status, and forward return when available
        """
        grades = self.get_historical_grades(symbol, pred_df, start_date=start_date)

        # Optionally compute forward returns for tooltip enrichment
        forward_returns: dict[str, float] = {}
        if price_df is not None and not price_df.empty:
            close_prices = price_df.iloc[:, 0] if isinstance(price_df, pd.DataFrame) else price_df
            close_prices = close_prices.dropna()
            for sg in grades:
                if not sg.grade:
                    continue
                try:
                    grade_date = pd.Timestamp(sg.date)
                    if grade_date in close_prices.index:
                        entry_price = float(close_prices.loc[grade_date])
                    else:
                        mask = close_prices.index <= grade_date
                        if mask.any():
                            entry_price = float(close_prices.loc[mask].iloc[-1])
                        else:
                            continue
                    future_dates = close_prices.index[close_prices.index > grade_date]
                    if len(future_dates) >= forward_days:
                        exit_price = float(close_prices.iloc[
                            close_prices.index.get_loc(grade_date) + forward_days
                        ])
                        if entry_price > 0 and not pd.isna(exit_price):
                            forward_returns[sg.date] = (exit_price - entry_price) / entry_price
                except Exception:
                    continue

        grade_colors = {
            "AAA": "#00ff00",  # Bright green
            "AA": "#22c55e",   # Green
            "A": "#86efac",    # Light green
            "V": "#fca5a5",    # Light red
            "VV": "#ef4444",   # Red
            "VVV": "#ff0000",  # Bright red
        }

        grade_sizes = {
            "AAA": 3,
            "AA": 2,
            "A": 1,
            "V": 1,
            "VV": 2,
            "VVV": 3,
        }

        markers = []
        for sg in grades:
            if not sg.grade:
                continue

            is_buy = sg.grade in ("AAA", "AA", "A")
            grade_name = GRADE_NAMES.get(sg.grade, "")

            # Build rich tooltip
            tooltip_parts = [
                f"{symbol} | {sg.date}",
                f"Grade: {sg.grade} ({grade_name})",
                f"Rank: {sg.rank}/{sg.total_stocks} (P{sg.percentile:.0f})",
                f"Score: {sg.score:.4f}",
            ]
            fwd_ret = forward_returns.get(sg.date)
            if fwd_ret is not None:
                tooltip_parts.append(f"{forward_days}d Return: {fwd_ret:+.2%}")
            qualification = "qualified" if sg.grade else "ungraded"
            tooltip_parts.append(f"Status: {qualification}")

            markers.append({
                "time": sg.date,
                "position": "belowBar" if is_buy else "aboveBar",
                "color": grade_colors.get(sg.grade, "#888"),
                "shape": "arrowUp" if is_buy else "arrowDown",
                "text": sg.grade,
                "size": grade_sizes.get(sg.grade, 1),
                "tooltip": " | ".join(tooltip_parts),
            })

        return markers
