from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.benchmark_residual_trend import (
    compute_benchmark_residual_trend,
)


def _returns_frame(
    values_by_instrument: dict[str, np.ndarray],
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    pieces = []
    for instrument, values in values_by_instrument.items():
        index = pd.MultiIndex.from_arrays(
            [dates, np.repeat(instrument, len(dates))],
            names=["datetime", "instrument"],
        )
        pieces.append(pd.DataFrame({"return": values}, index=index))
    return pd.concat(pieces).sort_index()


def test_residual_trend_recovers_beta_and_positive_alpha() -> None:
    dates = pd.bdate_range("2024-01-02", periods=180)
    benchmark = pd.Series(
        np.tile([-0.01, -0.005, 0.004, 0.012, 0.002], 36),
        index=dates,
        name="return",
    )
    noise = np.tile([-0.002, 0.001, 0.002, -0.001, 0.0], 36)
    stock = 1.5 * benchmark.to_numpy() + 0.0005 + noise
    frame = _returns_frame({"AAA": stock}, dates)

    result = compute_benchmark_residual_trend(
        frame,
        benchmark,
        lookback_sessions=126,
        skip_recent_sessions=10,
    )

    assert result.beta.iloc[-1, 0] == pytest.approx(1.5, abs=0.08)
    assert result.residual_mean.iloc[-1, 0] > 0.0
    assert result.residual_volatility.iloc[-1, 0] > 0.0
    assert result.score.iloc[-1, 0] > 0.0


def test_recent_ten_sessions_cannot_change_current_score() -> None:
    dates = pd.bdate_range("2024-01-02", periods=180)
    benchmark = pd.Series(
        np.sin(np.arange(len(dates)) / 7.0) * 0.01,
        index=dates,
    )
    base = 0.8 * benchmark.to_numpy() + np.cos(np.arange(len(dates))) * 0.002
    shocked = base.copy()
    shocked[-10:] = 0.50

    base_result = compute_benchmark_residual_trend(
        _returns_frame({"AAA": base}, dates),
        benchmark,
        lookback_sessions=126,
        skip_recent_sessions=10,
    )
    shocked_result = compute_benchmark_residual_trend(
        _returns_frame({"AAA": shocked}, dates),
        benchmark,
        lookback_sessions=126,
        skip_recent_sessions=10,
    )

    assert shocked_result.score.iloc[-1, 0] == pytest.approx(
        base_result.score.iloc[-1, 0],
        abs=1e-12,
    )


def test_insufficient_history_and_missing_rows_remain_missing() -> None:
    dates = pd.bdate_range("2024-01-02", periods=150)
    benchmark = pd.Series(
        np.sin(np.arange(len(dates)) / 5.0) * 0.01,
        index=dates,
    )
    stock = 1.1 * benchmark.to_numpy() + np.cos(np.arange(len(dates))) * 0.001
    stock[40] = np.nan

    result = compute_benchmark_residual_trend(
        _returns_frame({"AAA": stock}, dates),
        benchmark,
        lookback_sessions=30,
        skip_recent_sessions=10,
    )

    assert result.score.iloc[:39, 0].isna().all()
    assert np.isfinite(result.score.iloc[49, 0])
    assert result.score.iloc[50:80, 0].isna().all()


def test_flat_residual_window_fails_closed() -> None:
    dates = pd.bdate_range("2024-01-02", periods=80)
    benchmark = pd.Series(
        np.sin(np.arange(len(dates)) / 4.0) * 0.01,
        index=dates,
    )
    stock = 2.0 * benchmark.to_numpy()

    result = compute_benchmark_residual_trend(
        _returns_frame({"AAA": stock}, dates),
        benchmark,
        lookback_sessions=30,
        skip_recent_sessions=5,
    )

    assert result.score.iloc[:, 0].isna().all()
    assert not (result.score.iloc[:, 0] == 0.0).any()


def test_contract_attrs_are_explicit() -> None:
    dates = pd.bdate_range("2024-01-02", periods=60)
    benchmark = pd.Series(
        np.sin(np.arange(len(dates)) / 3.0) * 0.01,
        index=dates,
    )
    stock = benchmark.to_numpy() + np.cos(np.arange(len(dates))) * 0.002

    result = compute_benchmark_residual_trend(
        _returns_frame({"AAA": stock}, dates),
        benchmark,
        benchmark="QQQ",
        lookback_sessions=20,
        skip_recent_sessions=5,
    )

    assert result.score.attrs == {
        "provenance": "historical_benchmark_residual_trend_quality",
        "benchmark": "QQQ",
        "lookback_sessions": 20,
        "skip_recent_sessions": 5,
        "orientation": "higher_residual_trend_quality_is_better",
        "uses_future_returns": False,
        "parameter_search_performed": False,
        "missing_value_policy": "fail_closed_no_fill",
    }
    assert result.beta.attrs == result.score.attrs


@pytest.mark.parametrize(
    ("stock_returns", "benchmark_returns", "message"),
    [
        (
            pd.DataFrame({"return": [0.01]}),
            pd.Series([0.01, -0.01], index=pd.bdate_range("2024-01-02", periods=2)),
            "MultiIndex",
        ),
        (
            _returns_frame(
                {"AAA": np.array([0.01, 0.02])},
                pd.bdate_range("2024-01-02", periods=2),
            ),
            pd.Series([0.0, 0.0], index=pd.bdate_range("2024-01-02", periods=2)),
            "positive finite variance",
        ),
    ],
)
def test_invalid_inputs_fail_closed(
    stock_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        compute_benchmark_residual_trend(
            stock_returns,
            benchmark_returns,
            lookback_sessions=3,
            skip_recent_sessions=1,
        )
