from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker import make_daily_rank_target
from src.research.relative_return_target import (
    estimate_trailing_market_beta,
    make_beta_residual_forward_returns,
    make_naive_benchmark_excess_returns,
    prove_naive_rank_invariance,
)


def _stock_frame(values: dict[str, list[float]], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for instrument, series in values.items():
        rows.extend(
            (date, instrument, value)
            for date, value in zip(dates, series, strict=True)
        )
    frame = pd.DataFrame(rows, columns=["datetime", "instrument", "value"])
    return frame.set_index(["datetime", "instrument"])


def _benchmark_frame(values: list[float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [dates, ["QQQ"] * len(dates)],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame({"value": values}, index=index)


def test_naive_benchmark_subtraction_preserves_daily_ranks() -> None:
    dates = pd.date_range("2025-01-02", periods=3, freq="B")
    stock = _stock_frame(
        {
            "A": [0.10, -0.02, 0.05],
            "B": [0.03, 0.04, -0.01],
            "C": [-0.01, 0.01, 0.02],
        },
        dates,
    )
    benchmark = _benchmark_frame([0.02, -0.03, 0.01], dates)

    naive = make_naive_benchmark_excess_returns(stock, benchmark)
    pd.testing.assert_series_equal(
        make_daily_rank_target(stock.sort_index()).sort_index(),
        make_daily_rank_target(naive).sort_index(),
        check_names=False,
    )
    assert prove_naive_rank_invariance(stock, benchmark) == {
        "rank_identity": True,
        "compared_rows": 9,
        "raw_missing_rows": 0,
        "naive_missing_rows": 0,
    }


def test_trailing_beta_is_point_in_time_and_stock_specific() -> None:
    dates = pd.date_range("2025-01-02", periods=8, freq="B")
    market = np.array([0.01, -0.02, 0.03, 0.01, -0.01, 0.02, -0.03, 0.04])
    stock = _stock_frame(
        {
            "A": list(2.0 * market),
            "B": list(0.5 * market),
        },
        dates,
    )
    benchmark = _benchmark_frame(list(market), dates)

    beta = estimate_trailing_market_beta(
        stock,
        benchmark,
        lookback_sessions=5,
        minimum_observations=4,
    )

    assert np.isnan(beta.loc[(dates[2], "A"), "beta"])
    assert beta.loc[(dates[3], "A"), "beta"] == pytest.approx(2.0)
    assert beta.loc[(dates[3], "B"), "beta"] == pytest.approx(0.5)
    assert beta.loc[(dates[-1], "A"), "paired_observations"] == 5

    changed_stock = stock.copy()
    changed_stock.loc[(dates[-1], "A"), "value"] = 10.0
    changed_beta = estimate_trailing_market_beta(
        changed_stock,
        benchmark,
        lookback_sessions=5,
        minimum_observations=4,
    )
    pd.testing.assert_series_equal(
        beta.loc[pd.IndexSlice[: dates[-2], "A"], "beta"],
        changed_beta.loc[pd.IndexSlice[: dates[-2], "A"], "beta"],
    )


def test_beta_residual_can_change_cross_sectional_order() -> None:
    dates = pd.date_range("2025-01-02", periods=5, freq="B")
    stock_forward = _stock_frame(
        {
            "A": [0.15] * 5,
            "B": [0.12] * 5,
        },
        dates,
    )
    benchmark_forward = _benchmark_frame([0.08] * 5, dates)
    beta_index = stock_forward.index
    beta = pd.DataFrame(
        {
            "beta": [
                2.0 if instrument == "A" else 0.5
                for _, instrument in beta_index
            ],
            "paired_observations": [60] * len(beta_index),
        },
        index=beta_index,
    )

    residual = make_beta_residual_forward_returns(
        stock_forward,
        benchmark_forward,
        beta,
    )

    raw_rank = make_daily_rank_target(stock_forward)
    residual_rank = make_daily_rank_target(residual)
    for date in dates:
        assert raw_rank.loc[(date, "A")] > raw_rank.loc[(date, "B")]
        assert residual_rank.loc[(date, "A")] < residual_rank.loc[(date, "B")]


def test_beta_estimator_rejects_invalid_window_contract() -> None:
    dates = pd.date_range("2025-01-02", periods=3, freq="B")
    stock = _stock_frame({"A": [0.01, 0.02, 0.03]}, dates)
    benchmark = _benchmark_frame([0.01, 0.02, 0.03], dates)

    with pytest.raises(ValueError, match="minimum_observations"):
        estimate_trailing_market_beta(
            stock,
            benchmark,
            lookback_sessions=3,
            minimum_observations=4,
        )
