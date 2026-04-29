import pandas as pd
import pytest

from src.data.validation.consistency_check import ConsistencyChecker, compute_df_diff


def test_compute_df_diff():
    # Setup data
    dates = pd.date_range("2025-01-01", periods=5)
    df1 = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "close": [101.0, 102.0, 103.0, 104.0, 105.0],
            "volume": [1000, 1100, 1200, 1300, 1400],
        },
        index=dates,
    )

    # 1% difference
    df2 = df1 * 1.01

    diffs = compute_df_diff(df1, df2, columns=["open", "close", "volume"])

    # Relative diff should be approx 0.01
    assert pytest.approx(diffs["open"], 0.0001) == 0.01
    assert pytest.approx(diffs["close"], 0.0001) == 0.01
    assert pytest.approx(diffs["volume"], 0.0001) == 0.01


def test_compute_df_diff_with_zeros():
    dates = pd.date_range("2025-01-01", periods=2)
    df1 = pd.DataFrame({"open": [0.0, 100.0]}, index=dates)
    df2 = pd.DataFrame({"open": [0.0, 105.0]}, index=dates)

    diffs = compute_df_diff(df1, df2, columns=["open"])
    # 0.0 is replaced by NaN in denom, so only the second row contributes
    # |100-105|/100 = 0.05
    assert pytest.approx(diffs["open"], 0.0001) == 0.05


def test_consistency_checker():
    checker = ConsistencyChecker(threshold=0.02)

    dates = pd.date_range("2025-01-01", periods=2)
    df1 = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "close": [100.0, 100.0],
            "high": [100.0, 100.0],
            "low": [100.0, 100.0],
            "volume": [100.0, 100.0],
        },
        index=dates,
    )

    # Within threshold (1%)
    df_ok = df1 * 1.01
    report_ok = checker.check(df1, df_ok, "TEST")
    assert report_ok["ok"] is True
    assert len(report_ok["warnings"]) == 0

    # Outside threshold (5%)
    df_bad = df1 * 1.05
    report_bad = checker.check(df1, df_bad, "TEST")
    assert report_bad["ok"] is False
    assert any("open difference too high" in w for w in report_bad["warnings"])
