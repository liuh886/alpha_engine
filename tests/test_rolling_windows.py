from __future__ import annotations

import pytest

from src.research.rolling_windows import filter_windows_by_available_range, half_year_rolling_windows


def test_half_year_rolling_windows_use_expanding_train_history() -> None:
    windows = half_year_rolling_windows(start_year=2021, first_test_year=2024, last_test_year=2025)

    assert [window.label for window in windows] == ["2024H1", "2024H2", "2025H1", "2025H2"]
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
        half_year_rolling_windows(start_year=2025, first_test_year=2024, last_test_year=2026)
    with pytest.raises(ValueError, match="last_test_year"):
        half_year_rolling_windows(start_year=2021, first_test_year=2026, last_test_year=2025)


def test_filter_windows_by_available_range_keeps_fully_covered_windows() -> None:
    windows = half_year_rolling_windows(start_year=2021, first_test_year=2024, last_test_year=2026)

    kept = filter_windows_by_available_range(
        windows,
        available_start="2021-01-01",
        available_end="2025-06-30",
    )

    assert [window.label for window in kept] == ["2024H1", "2024H2", "2025H1"]
    assert all(window.test_end <= "2025-06-30" for window in kept)
