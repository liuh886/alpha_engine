from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.v4_30_skew_state0_information import (
    HORIZONS,
    SKEW_HIGH_QUANTILE,
    SKEW_WINDOW,
    build_skew_trace,
    build_state0_forward_paths,
    information_gate,
    summarize_state0_information,
)


def _index(count: int = 380) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-02", periods=count, freq="B")


def _daily(count: int = 380) -> pd.DataFrame:
    index = _index(count)
    returns = pd.Series(np.linspace(-0.002, 0.003, count), index=index)
    return pd.DataFrame(
        {
            "position_state": [0] * count,
            "QQQ_next_open_return": returns,
        },
        index=index,
    )


def test_skew_trace_uses_frozen_252_session_80th_percentile() -> None:
    daily = _daily()
    values = np.linspace(100.0, 160.0, len(daily))
    skew = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_skew_trace(daily, skew)

    assert pd.isna(trace["skew_high_threshold"].iloc[SKEW_WINDOW - 2])
    expected = pd.Series(values[:SKEW_WINDOW]).quantile(SKEW_HIGH_QUANTILE)
    assert trace["skew_high_threshold"].iloc[SKEW_WINDOW - 1] == pytest.approx(expected)
    assert trace["skew_high_at_close"].iloc[SKEW_WINDOW - 1]


def test_skew_trace_does_not_forward_fill_missing_dates() -> None:
    daily = _daily()
    values = np.linspace(100.0, 160.0, len(daily))
    skew = pd.DataFrame({"close": values}, index=daily.index)
    skew = skew.drop(daily.index[-1])
    trace = build_skew_trace(daily, skew)

    assert pd.isna(trace.loc[daily.index[-1], "skew_close"])
    assert not trace.loc[daily.index[-1], "skew_high_at_close"]


def test_forward_paths_start_after_signal_date() -> None:
    daily = _daily()
    values = np.linspace(100.0, 160.0, len(daily))
    skew = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_skew_trace(daily, skew)
    paths = build_state0_forward_paths(daily, trace)

    first = paths.iloc[0]
    signal_date = pd.Timestamp(first["signal_date"])
    location = daily.index.get_loc(signal_date)
    expected = float(
        (1.0 + daily["QQQ_next_open_return"].iloc[location + 1 : location + 1 + HORIZONS[0]])
        .prod()
        - 1.0
    )
    assert first[f"forward_return_{HORIZONS[0]}d"] == pytest.approx(expected)


def test_forward_paths_only_use_executed_state0() -> None:
    daily = _daily()
    daily.loc[daily.index[260:270], "position_state"] = 1
    values = np.linspace(100.0, 160.0, len(daily))
    skew = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_skew_trace(daily, skew)
    paths = build_state0_forward_paths(daily, trace)

    assert not paths["signal_date"].isin(daily.index[260:270]).any()


def test_information_gate_can_pass_diversified_worse_high_skew_paths() -> None:
    dates = pd.date_range("2010-01-04", periods=160, freq="30D")
    rows = []
    for i, date in enumerate(dates):
        high = i % 2 == 0
        rows.append(
            {
                "signal_date": date,
                "year": int(date.year),
                "skew_high": high,
                "skew_close": 150.0 if high else 120.0,
                "skew_high_threshold": 140.0,
                "forward_return_20d": -0.08 if high else 0.03,
                "forward_max_drawdown_20d": -0.10 if high else -0.03,
                "forward_return_60d": -0.12 if high else 0.06,
                "forward_max_drawdown_60d": -0.16 if high else -0.05,
            }
        )
    paths = pd.DataFrame(rows)
    summary = summarize_state0_information(paths)
    gate = information_gate(paths, summary)

    assert gate["portfolio_experiment_authorized"]
    assert all(gate["checks"].values())


def test_frozen_horizons_reject_changes() -> None:
    daily = _daily()
    values = np.linspace(100.0, 160.0, len(daily))
    skew = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_skew_trace(daily, skew)
    with pytest.raises(ValueError, match="frozen horizons"):
        build_state0_forward_paths(daily, trace, horizons=(10, 20))
