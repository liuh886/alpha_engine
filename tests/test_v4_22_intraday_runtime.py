from __future__ import annotations

import pandas as pd

from scripts.run_qqqi_v4_22_intraday_rank_pilot import _common_calendar


def _bars(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
            "amount": 1.0,
            "factor": 1.0,
        }
    )


def test_common_calendar_removes_nonshared_volatility_sessions():
    bars = {
        "^VIX": _bars(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "^VXN": _bars(["2024-01-02", "2024-01-04"]),
    }
    audit = _common_calendar(bars, "^VIX", "^VXN")
    assert audit["left_rows_before"] == 3
    assert audit["common_rows"] == 2
    assert bars["^VIX"]["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-02",
        "2024-01-04",
    ]
    assert bars["^VXN"]["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-02",
        "2024-01-04",
    ]
