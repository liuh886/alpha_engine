"""Unit tests for src/core/labels.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.labels import (
    add_bucket_labels,
    add_cross_sectional_rank,
    build_excess_return_labels,
    compute_excess_return,
)


@pytest.fixture
def sample_data() -> tuple[pd.DataFrame, pd.Series]:
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    tickers = ["A", "B", "C", "D", "E"]
    rng = np.random.default_rng(42)
    stock_returns = pd.DataFrame(
        rng.uniform(-0.05, 0.05, size=(3, 5)),
        index=dates,
        columns=tickers,
    )
    bench_returns = pd.Series(
        rng.uniform(-0.02, 0.02, size=3),
        index=dates,
        name="bench",
    )
    return stock_returns, bench_returns


def _one_day_returns(values: list[float], tickers: list[str] | None = None) -> pd.DataFrame:
    tickers = tickers or [f"S{i:03d}" for i in range(len(values))]
    return pd.DataFrame(
        [values],
        index=pd.DatetimeIndex(["2024-01-02"], name="date"),
        columns=tickers,
    )


def test_compute_excess_return_shape_and_columns(sample_data):
    stocks, bench = sample_data
    result = compute_excess_return(stocks, bench)

    assert len(result) == 15
    assert {
        "date",
        "ticker",
        "stock_return",
        "bench_return",
        "future_10d_excess_return",
    }.issubset(result.columns)


def test_compute_excess_return_arithmetic(sample_data):
    stocks, bench = sample_data
    result = compute_excess_return(stocks, bench)
    diff = (
        result["stock_return"] - result["bench_return"] - result["future_10d_excess_return"]
    ).abs()

    assert diff.max() < 1e-10


def test_date_alignment_excludes_missing_bench():
    dates_stock = pd.date_range("2024-01-02", periods=4, freq="B")
    dates_bench = pd.date_range("2024-01-02", periods=3, freq="B")
    stocks = pd.DataFrame(np.ones((4, 2)), index=dates_stock, columns=["X", "Y"])
    bench = pd.Series(np.zeros(3), index=dates_bench)

    result = compute_excess_return(stocks, bench)

    assert result["date"].nunique() == 3


def test_cross_sectional_rank_range_and_within_date(sample_data):
    stocks, bench = sample_data
    df = add_cross_sectional_rank(compute_excess_return(stocks, bench))

    assert df["rank_pct"].dropna().between(0, 1).all()
    assert (df.groupby("date")["rank_pct"].max() == 1.0).all()


@pytest.mark.parametrize(
    ("universe_size", "top_pct", "expected_count"),
    [
        (5, 0.20, 1),
        (5, 0.10, 1),
        (11, 0.10, 2),
        (100, 0.20, 20),
        (100, 0.05, 5),
    ],
)
def test_exact_top_n_count(universe_size, top_pct, expected_count):
    values = [float(i) for i in range(universe_size)]
    stocks = _one_day_returns(values)
    bench = pd.Series([0.0], index=stocks.index)
    result = build_excess_return_labels(stocks, bench, top_pct=(top_pct,))
    label_col = f"label_top{int(top_pct * 100)}pct"

    assert result[label_col].sum() == expected_count


def test_ties_are_deterministic_by_ticker():
    stocks = _one_day_returns([0.10, 0.10, 0.00], tickers=["A", "B", "C"])
    bench = pd.Series([0.0], index=stocks.index)
    result = build_excess_return_labels(stocks, bench, top_pct=(1 / 3,))
    by_ticker = result.set_index("ticker")

    assert by_ticker.loc["A", "label_top33pct"] == 1
    assert by_ticker.loc["B", "label_top33pct"] == 0
    assert by_ticker.loc["C", "label_top33pct"] == 0


def test_nan_return_is_not_labeled_winner():
    stocks = _one_day_returns([np.nan, 0.20, 0.10], tickers=["A", "B", "C"])
    bench = pd.Series([0.0], index=stocks.index)
    result = build_excess_return_labels(stocks, bench, top_pct=(0.50,))
    by_ticker = result.set_index("ticker")

    assert by_ticker.loc["A", "label_top50pct"] == 0
    assert by_ticker.loc["B", "label_top50pct"] == 1
    assert by_ticker.loc["C", "label_top50pct"] == 0


def test_invalid_top_pct_raises(sample_data):
    stocks, bench = sample_data
    df = add_cross_sectional_rank(compute_excess_return(stocks, bench))

    with pytest.raises(ValueError, match="top_pct thresholds"):
        add_bucket_labels(df, top_pct=(0.0, 1.2))


def test_build_excess_return_labels_end_to_end(sample_data):
    stocks, bench = sample_data
    result = build_excess_return_labels(stocks, bench)

    assert {
        "date",
        "ticker",
        "stock_return",
        "bench_return",
        "future_10d_excess_return",
        "rank_pct",
        "label_top20pct",
        "label_top10pct",
        "label_top5pct",
    }.issubset(result.columns)


def test_no_internal_shift_contract(sample_data):
    stocks, bench = sample_data
    result = build_excess_return_labels(stocks, bench)

    assert set(result["date"].unique()).issubset(set(stocks.index))


def test_caller_level_forward_return_timing_contract():
    dates = pd.bdate_range("2024-01-02", periods=11)
    stock_close = pd.DataFrame(
        {
            "A": [100, 500, 100, 100, 100, 100, 100, 100, 100, 100, 110],
            "B": [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 90],
        },
        index=dates,
    )
    bench_close = pd.Series([100] * 11, index=dates)
    stock_fwd = stock_close.pct_change(10).shift(-10).loc[[dates[0]]]
    bench_fwd = bench_close.pct_change(10).shift(-10).loc[[dates[0]]]

    result = build_excess_return_labels(stock_fwd, bench_fwd, top_pct=(0.50,))
    by_ticker = result.set_index("ticker")

    assert by_ticker.loc["A", "future_10d_excess_return"] == pytest.approx(0.10)
    assert by_ticker.loc["B", "future_10d_excess_return"] == pytest.approx(-0.10)
    assert by_ticker.loc["A", "label_top50pct"] == 1
    assert by_ticker.loc["B", "label_top50pct"] == 0
