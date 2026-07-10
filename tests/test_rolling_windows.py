from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.research.paradigm import load_research_paradigm_spec
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)


def test_half_year_rolling_windows_use_expanding_train_history() -> None:
    windows = half_year_rolling_windows(
        start_year=2021,
        first_test_year=2024,
        last_test_year=2025,
    )

    assert [window.label for window in windows] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]
    assert windows[0].train_start == "2021-01-01"
    assert windows[0].train_end == "2023-12-31"
    assert windows[0].test_start == "2024-01-01"
    assert windows[0].test_end == "2024-06-30"
    assert windows[-1].train_start == "2021-01-01"
    assert windows[-1].train_end == "2025-06-30"
    assert windows[-1].test_start == "2025-07-01"
    assert windows[-1].test_end == "2025-12-31"


def test_half_year_rolling_windows_reject_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="first_test_year"):
        half_year_rolling_windows(
            start_year=2025,
            first_test_year=2024,
            last_test_year=2026,
        )
    with pytest.raises(ValueError, match="first_test_year"):
        half_year_rolling_windows(
            start_year=2025,
            first_test_year=2025,
            last_test_year=2026,
        )
    with pytest.raises(ValueError, match="last_test_year"):
        half_year_rolling_windows(
            start_year=2021,
            first_test_year=2026,
            last_test_year=2025,
        )


def test_filter_windows_by_available_range_keeps_fully_covered_windows() -> None:
    windows = half_year_rolling_windows(
        start_year=2021,
        first_test_year=2024,
        last_test_year=2026,
    )

    kept = filter_windows_by_available_range(
        windows,
        available_start="2021-01-01",
        available_end="2025-06-30",
    )

    assert [window.label for window in kept] == ["2024H1", "2024H2", "2025H1"]
    assert all(window.test_end <= "2025-06-30" for window in kept)


def test_canonical_us_spec_keeps_three_window_stability_minimum() -> None:
    spec = load_research_paradigm_spec(
        Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")
    )
    assert int(spec.walk_forward["min_windows"]) == 3


def test_purge_training_tail_removes_holding_period_and_preserves_return_attrs() -> None:
    dates = pd.date_range("2023-12-01", periods=15, freq="B")
    index = pd.MultiIndex.from_product(
        [dates, ["A", "B"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature": range(len(index))}, index=index)
    returns = pd.DataFrame({"return": [0.01] * len(index)}, index=index)
    returns.attrs.update(
        {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": "Ref($close, -10) / $close - 1",
        }
    )

    purged_features, purged_returns = purge_training_tail(
        features,
        returns,
        holding_days=10,
    )

    expected_dates = set(dates[:5])
    assert set(purged_features.index.get_level_values("datetime")) == expected_dates
    assert set(purged_returns.index.get_level_values("datetime")) == expected_dates
    assert purged_returns.attrs == returns.attrs
