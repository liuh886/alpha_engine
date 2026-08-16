from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
from src.research.us_skew_exposure_control import (
    HIGH_RISK_EXPOSURE,
    LOOKBACK_SESSIONS,
    NORMAL_EXPOSURE,
    THRESHOLD_QUANTILE,
    _evaluate_scaled,
    _risk_state,
)


class _Runtime:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def features(self, symbols, expressions, start, end):
        assert list(expressions) == ["skew"]
        dates = self.frame.index.get_level_values("datetime")
        mask = (
            dates >= pd.Timestamp(start)
        ) & (dates <= pd.Timestamp(end)) & self.frame.index.get_level_values("instrument").isin(symbols)
        return self.frame.loc[mask].copy()


def test_risk_state_threshold_uses_only_prior_252_sessions() -> None:
    dates = pd.bdate_range("2024-01-02", periods=270)
    symbols = ["A", "B"]
    index = pd.MultiIndex.from_product([dates, symbols], names=["datetime", "instrument"])
    # Median skew gets steadily more negative, so oriented risk rises each day.
    values = np.repeat(-np.arange(len(dates), dtype=float), len(symbols))
    frame = pd.DataFrame({"skew": values}, index=index)

    state = _risk_state(
        _Runtime(frame), symbols, expression="skew", start=str(dates[0].date()), end=str(dates[-1].date())
    )

    first_threshold_date = dates[LOOKBACK_SESSIONS]
    expected_history = np.arange(LOOKBACK_SESSIONS, dtype=float)
    assert state.loc[first_threshold_date, "lagged_trailing_80pct_threshold"] == np.quantile(
        expected_history, THRESHOLD_QUANTILE
    )
    assert state.loc[first_threshold_date, "exposure"] == HIGH_RISK_EXPOSURE
    assert state["lagged_trailing_80pct_threshold"].iloc[:LOOKBACK_SESSIONS].isna().all()


def test_scaled_evaluator_exactly_reproduces_full_exposure_sector_cap() -> None:
    dates = pd.bdate_range("2025-01-02", periods=21)
    names = [f"S{index:02d}" for index in range(20)]
    score_rows = []
    returns = {}
    benchmark = {}
    for day_index, date in enumerate(dates):
        for rank, name in enumerate(names):
            score_rows.append(
                {"datetime": date, "instrument": name, "score": float(100 - rank + day_index / 100)}
            )
        returns[date] = {name: 0.01 + rank / 10000 for rank, name in enumerate(names)}
        benchmark[date] = 0.005
    scores = pd.DataFrame(score_rows)
    sectors = {name: f"sector_{index % 5}" for index, name in enumerate(names)}
    rebalance_dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())][::10]
    exposure = {date: NORMAL_EXPOSURE for date in rebalance_dates}

    exact, exact_periods, _, _, _ = sector_cap._evaluate(
        scores,
        returns,
        benchmark,
        sectors,
        cost_bps=20,
        sector_cap=True,
    )
    reproduced, periods = _evaluate_scaled(
        scores,
        returns,
        benchmark,
        sectors,
        exposure,
        cost_bps=20,
    )

    for key in ("total_return", "benchmark_return", "max_drawdown", "turnover", "costs"):
        assert np.isclose(reproduced[key], exact[key], atol=1e-12, rtol=0.0)
    assert np.allclose(
        periods["net_return"].to_numpy(dtype=float),
        exact_periods["net_return"].to_numpy(dtype=float),
        atol=1e-12,
        rtol=0.0,
    )
