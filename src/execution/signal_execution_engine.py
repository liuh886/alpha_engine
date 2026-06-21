"""Standalone signal execution engine.

Replaces the Qlib strategy framework with a vectorized execution pipeline
that integrates:

- **Grade-differentiated position sizing** — AAA=3×, AA=2×, A=1× weights
  instead of equal-weight TOP-N.
- **Market regime filtering** — IC decay, volatility spike, and trend
  detection dynamically scale exposure.
- **Short-side utilization** — VVV / VV / V ranked stocks enter a short
  basket to capture downside alpha.

Input: MultiIndex DataFrames (datetime, instrument) with prediction scores
and forward returns.  Same format as ``run_vectorized_backtest()``.

Output: ``BacktestResult`` for direct comparison with the existing
vectorized backtest.

Usage::

    from src.execution.signal_execution_engine import SignalExecutionEngine
    from src.execution.signal_execution_config import SignalExecutionConfig

    config = SignalExecutionConfig(market="cn", rebalance_days=10)
    engine = SignalExecutionEngine(config)
    result = engine.execute(predictions, returns, benchmark_returns)
    print(f"Excess return: {result.excess_return:.2%}")
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from src.execution.grade_weight_assigner import (
    GradeAllocation,
    GradeWeightAssigner,
)
from src.execution.regime_filter import RegimeFilter
from src.execution.signal_execution_config import SignalExecutionConfig
from src.research.vectorized_backtest import BacktestResult, compute_ic_vectorized

logger = structlog.get_logger(__name__)

__all__ = ["SignalExecutionEngine", "ExecutionDiagnostics"]


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class ExecutionDiagnostics:
    """Per-rebalance-date trace for debugging and analysis.

    Collected during execution and returned alongside ``BacktestResult``
    so callers can inspect regime signals, allocations, and turnover.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        date: str,
        regime_factor: float,
        regime_reasons: list[str],
        long_count: int,
        short_count: int,
        turnover: float,
        cost: float,
        port_ret: float,
        bench_ret: float,
        nav: float,
        allocation: GradeAllocation | None = None,
    ) -> None:
        self.records.append(
            {
                "date": date,
                "regime_factor": round(regime_factor, 4),
                "regime_reasons": regime_reasons,
                "long_count": long_count,
                "short_count": short_count,
                "turnover": round(turnover, 6),
                "cost": round(cost, 6),
                "port_return": round(port_ret, 6),
                "bench_return": round(bench_ret, 6),
                "nav": round(nav, 2),
                "long_positions": (
                    {k: round(v, 4) for k, v in allocation.long_positions.items()}
                    if allocation
                    else {}
                ),
                "short_positions": (
                    {k: round(v, 4) for k, v in allocation.short_positions.items()}
                    if allocation
                    else {}
                ),
            }
        )

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.records)

    def summary(self) -> dict[str, Any]:
        """Return aggregate diagnostics."""
        if not self.records:
            return {}
        factors = [r["regime_factor"] for r in self.records]
        turnovers = [r["turnover"] for r in self.records]
        long_counts = [r["long_count"] for r in self.records]
        short_counts = [r["short_count"] for r in self.records]
        return {
            "n_rebalances": len(self.records),
            "mean_regime_factor": round(float(np.mean(factors)), 4),
            "min_regime_factor": round(float(np.min(factors)), 4),
            "mean_turnover": round(float(np.mean(turnovers)), 6),
            "mean_long_count": round(float(np.mean(long_counts)), 1),
            "mean_short_count": round(float(np.mean(short_counts)), 1),
            "cash_days": sum(1 for f in factors if f < 0.05),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SignalExecutionEngine:
    """Standalone signal execution engine.

    Runs the full pipeline: regime filter → grade-weighted allocation →
    turnover-aware portfolio return computation → result aggregation.

    Designed to work with raw DataFrames — no Qlib strategy imports.
    Qlib is only needed for initial data loading (which the caller
    handles before invoking ``execute()``).
    """

    def __init__(self, config: SignalExecutionConfig | None = None):
        self._cfg = config or SignalExecutionConfig()
        self._regime_filter = RegimeFilter(self._cfg) if self._cfg.enable_regime_filter else None
        self._weight_assigner = GradeWeightAssigner(self._cfg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        predictions: pd.DataFrame,
        returns: pd.DataFrame,
        benchmark_returns: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Run the full signal execution pipeline.

        Parameters
        ----------
        predictions : pd.DataFrame
            MultiIndex (datetime, instrument), single score column.
            Produced by ``model.predict(dataset)`` or loaded from pickle.
        returns : pd.DataFrame
            MultiIndex (datetime, instrument), single forward-return column.

            **Important**: Returns must already be forward-looking and
            aligned with prediction dates.  The engine does NOT shift
            returns — ``predictions[t]`` must correspond to
            ``returns[t]`` (the forward return from t to t+horizon).
        benchmark_returns : pd.DataFrame, optional
            Single-level DatetimeIndex, single column.
            CSI300 for CN market, QQQ for US.

        Returns
        -------
        BacktestResult
            Contains all metrics plus time series arrays.
            Compatible with ``run_vectorized_backtest()`` output.
        """
        self._validate_inputs(predictions, returns)

        # Build matrices
        score_matrix = self._build_matrix(predictions)
        return_matrix = self._build_matrix(returns)

        # Common dates
        common_dates = sorted(set(score_matrix.index) & set(return_matrix.index))
        if not common_dates:
            logger.warning("No common dates between predictions and returns")
            return self._empty_result()

        rebalance_dates = common_dates[:: self._cfg.rebalance_days]
        if len(rebalance_dates) < 2:
            logger.warning(
                "Too few rebalance dates",
                n_rebalance_dates=len(rebalance_dates),
            )
            return self._empty_result()

        # Benchmark series
        bench_series: pd.Series | None = None
        if benchmark_returns is not None and len(benchmark_returns.columns) > 0:
            bench_series = benchmark_returns.iloc[:, 0]

        # IC pre-computation (used by regime filter AND result metrics)
        mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(predictions, returns)

        # Diagnostics collector
        diagnostics = ExecutionDiagnostics()

        # --- Main execution loop ---
        capital = self._cfg.initial_capital
        portfolio_values = [capital]
        benchmark_values = [capital]
        period_returns: list[float] = []

        prev_long: dict[str, float] = {}
        prev_short: dict[str, float] = {}

        for i, date in enumerate(rebalance_dates):
            # --- Scores ---
            if date not in score_matrix.index:
                self._record_flat(
                    portfolio_values,
                    benchmark_values,
                    period_returns,
                    bench_series,
                    date,
                )
                diagnostics.record(
                    date=str(date.date()),
                    regime_factor=1.0,
                    regime_reasons=["no_data"],
                    long_count=0,
                    short_count=0,
                    turnover=0.0,
                    cost=0.0,
                    port_ret=0.0,
                    bench_ret=0.0,
                    nav=portfolio_values[-1],
                )
                continue

            scores = score_matrix.loc[date].dropna()
            if scores.empty:
                self._record_flat(
                    portfolio_values,
                    benchmark_values,
                    period_returns,
                    bench_series,
                    date,
                )
                diagnostics.record(
                    date=str(date.date()),
                    regime_factor=1.0,
                    regime_reasons=["empty_scores"],
                    long_count=0,
                    short_count=0,
                    turnover=0.0,
                    cost=0.0,
                    port_ret=0.0,
                    bench_ret=0.0,
                    nav=portfolio_values[-1],
                )
                continue

            # --- Regime filter ---
            regime_factor: float = 1.0
            regime_reasons: list[str] = []
            if self._regime_filter is not None:
                regime_signal = self._regime_filter.evaluate(
                    ic_series=ic_series,
                    return_matrix=return_matrix,
                    benchmark_series=bench_series,
                    date=date,
                )
                regime_factor = regime_signal.exposure_factor
                regime_reasons = regime_signal.reasons

            # --- Grade-weighted allocation ---
            allocation = self._weight_assigner.compute_allocation(
                scores=scores,
                current_date=str(date.date()),
                regime_factor=regime_factor,
            )

            # --- Turnover cost ---
            cost = self._compute_turnover_cost(
                long_positions=allocation.long_positions,
                prev_long=prev_long,
                short_positions=allocation.short_positions,
                prev_short=prev_short,
            )

            # --- Portfolio return ---
            port_ret = self._compute_holding_return(
                long_positions=allocation.long_positions,
                short_positions=allocation.short_positions,
                return_matrix=return_matrix,
                date=date,
            )
            net_ret = port_ret - cost

            # --- Update state ---
            capital *= 1.0 + net_ret
            portfolio_values.append(capital)
            period_returns.append(net_ret)

            prev_long = allocation.long_positions
            prev_short = allocation.short_positions

            # --- Benchmark ---
            bench_ret = 0.0
            if bench_series is not None and date in bench_series.index:
                raw = float(bench_series.loc[date])
                bench_ret = raw if np.isfinite(raw) else 0.0
            benchmark_values.append(benchmark_values[-1] * (1.0 + bench_ret))

            # --- Diagnostics ---
            turnover = self._compute_oneway_turnover(
                allocation.long_positions,
                prev_long,
                allocation.short_positions,
                prev_short,
            )
            diagnostics.record(
                date=str(date.date()),
                regime_factor=regime_factor,
                regime_reasons=regime_reasons,
                long_count=allocation.long_count,
                short_count=allocation.short_count,
                turnover=turnover,
                cost=cost,
                port_ret=net_ret,
                bench_ret=bench_ret,
                nav=capital,
                allocation=allocation,
            )

        # --- Attach diagnostics to result ---
        result = self._build_result(
            portfolio_values=portfolio_values,
            benchmark_values=benchmark_values,
            period_returns=period_returns,
            rebalance_dates=rebalance_dates,
            mean_ic=mean_ic,
            ic_ir=ic_ir,
            pos_ratio=pos_ratio,
            ic_series=ic_series,
        )
        # Store diagnostics as an attribute for caller inspection
        result._diagnostics = diagnostics  # type: ignore[attr-defined]

        logger.info(
            "Execution complete",
            market=self._cfg.market,
            n_rebalances=len(rebalance_dates),
            excess_return=round(result.excess_return, 4),
            sharpe=round(result.sharpe_ratio, 4),
            max_drawdown=round(result.max_drawdown, 4),
            diagnostics=diagnostics.summary(),
        )

        return result

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(predictions: pd.DataFrame, returns: pd.DataFrame) -> None:
        """Validate MultiIndex structure and column presence."""
        if not isinstance(predictions.index, pd.MultiIndex):
            raise ValueError("predictions must have MultiIndex (datetime, instrument)")
        if "datetime" not in predictions.index.names:
            raise ValueError("predictions index must include 'datetime' level")
        if "instrument" not in predictions.index.names:
            raise ValueError("predictions index must include 'instrument' level")
        if len(predictions.columns) == 0:
            raise ValueError("predictions must have at least one column")
        if len(returns.columns) == 0:
            raise ValueError("returns must have at least one column")

    # ------------------------------------------------------------------
    # Matrix construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_matrix(df: pd.DataFrame) -> pd.DataFrame:
        """Pivot MultiIndex DataFrame to (datetime × instrument) matrix."""
        col = df.columns[0]
        return df[col].unstack(level="instrument")

    # ------------------------------------------------------------------
    # Return computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_holding_return(
        long_positions: dict[str, float],
        short_positions: dict[str, float],
        return_matrix: pd.DataFrame,
        date: pd.Timestamp,
    ) -> float:
        """Compute portfolio return for one holding period.

        long_return  = Σ(long_weight[i] × return[i])
        short_return = Σ(short_weight[i] × return[i])
        portfolio_return = long_return - short_return

        - If a shorted stock goes down (negative return): -(−) = +profit.
        - If a shorted stock goes up (positive return): −(+) = −loss.
        """
        if date not in return_matrix.index:
            return 0.0

        day_returns = return_matrix.loc[date].dropna()

        long_ret = 0.0
        for instrument, weight in long_positions.items():
            if instrument in day_returns.index:
                r = float(day_returns[instrument])
                if np.isfinite(r):
                    long_ret += weight * r

        short_ret = 0.0
        for instrument, weight in short_positions.items():
            if instrument in day_returns.index:
                r = float(day_returns[instrument])
                if np.isfinite(r):
                    short_ret += weight * r

        return long_ret - short_ret

    # ------------------------------------------------------------------
    # Turnover cost
    # ------------------------------------------------------------------

    def _compute_turnover_cost(
        self,
        long_positions: dict[str, float],
        prev_long: dict[str, float],
        short_positions: dict[str, float],
        prev_short: dict[str, float],
    ) -> float:
        """Compute transaction cost from weight changes.

        Cost = one-way turnover × avg(buy_cost_bps, sell_cost_bps) / 10000.
        """
        turnover = self._compute_oneway_turnover(
            long_positions,
            prev_long,
            short_positions,
            prev_short,
        )
        avg_cost_bps = (self._cfg.buy_cost_bps + self._cfg.sell_cost_bps) / 2.0
        return turnover * avg_cost_bps / 10000.0

    @staticmethod
    def _compute_oneway_turnover(
        long_positions: dict[str, float],
        prev_long: dict[str, float],
        short_positions: dict[str, float],
        prev_short: dict[str, float],
    ) -> float:
        """Compute one-way turnover = Σ|Δw| / 2."""
        all_symbols = set(long_positions) | set(prev_long) | set(short_positions) | set(prev_short)
        total_change = 0.0
        for s in all_symbols:
            total_change += abs(long_positions.get(s, 0.0) - prev_long.get(s, 0.0))
            total_change += abs(short_positions.get(s, 0.0) - prev_short.get(s, 0.0))
        return total_change / 2.0

    # ------------------------------------------------------------------
    # Result construction
    # ------------------------------------------------------------------

    def _build_result(
        self,
        portfolio_values: list[float],
        benchmark_values: list[float],
        period_returns: list[float],
        rebalance_dates: list[pd.Timestamp],
        mean_ic: float,
        ic_ir: float,
        pos_ratio: float,
        ic_series: list[float],
    ) -> BacktestResult:
        """Aggregate into a ``BacktestResult`` compatible with existing code."""
        port_arr = np.array(portfolio_values, dtype=float)
        bench_arr = np.array(benchmark_values, dtype=float)

        total_return = float(port_arr[-1] / port_arr[0] - 1.0)
        bench_return = float(bench_arr[-1] / bench_arr[0] - 1.0)
        excess_return = total_return - bench_return

        # Max drawdown
        running_max = np.maximum.accumulate(port_arr)
        max_dd = float((port_arr / running_max - 1.0).min())

        # Annualized metrics
        ret_arr = np.array(period_returns, dtype=float)
        periods_per_year = 252.0 / self._cfg.rebalance_days
        ret_std = float(ret_arr.std())
        sharpe = (
            float(ret_arr.mean() / ret_std * np.sqrt(periods_per_year)) if ret_std > 1e-10 else 0.0
        )

        n_periods = len(period_returns)
        years = n_periods * self._cfg.rebalance_days / 252.0
        annual_ret = (
            float((1.0 + total_return) ** (1.0 / years) - 1.0)
            if years > 0 and total_return > -1.0
            else 0.0
        )
        volatility = float(ret_std * np.sqrt(periods_per_year)) if n_periods > 0 else 0.0

        test_start = str(rebalance_dates[0].date()) if rebalance_dates else ""
        test_end = str(rebalance_dates[-1].date()) if rebalance_dates else ""

        return BacktestResult(
            total_return=total_return,
            benchmark_return=bench_return,
            excess_return=excess_return,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            annual_return=annual_ret,
            volatility=volatility,
            mean_ic=mean_ic,
            ic_ir=ic_ir,
            positive_ic_ratio=pos_ratio,
            portfolio_values=portfolio_values,
            benchmark_values=benchmark_values,
            daily_returns=period_returns,
            ic_series=ic_series,
            topk=0,  # Not applicable for grade-based execution
            rebalance_days=self._cfg.rebalance_days,
            n_periods=n_periods,
            test_start=test_start,
            test_end=test_end,
        )

    @staticmethod
    def _empty_result() -> BacktestResult:
        """Return a zeroed-out result."""
        return BacktestResult(
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            annual_return=0.0,
            volatility=0.0,
            mean_ic=0.0,
            ic_ir=0.0,
            positive_ic_ratio=0.0,
        )

    @staticmethod
    def _record_flat(
        portfolio_values: list[float],
        benchmark_values: list[float],
        period_returns: list[float],
        bench_series: pd.Series | None,
        date: pd.Timestamp,
    ) -> None:
        """Record a zero-return period when no data is available."""
        portfolio_values.append(portfolio_values[-1])
        period_returns.append(0.0)
        if bench_series is not None and date in bench_series.index:
            bench_ret = float(bench_series.loc[date])
            if not np.isfinite(bench_ret):
                bench_ret = 0.0
        else:
            bench_ret = 0.0
        benchmark_values.append(benchmark_values[-1] * (1.0 + bench_ret))
