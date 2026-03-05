import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_resolve_backtest_window_sets_end_to_latest_calendar():
    from src.common.market import resolve_backtest_window

    calendar = pd.to_datetime(["2025-01-02", "2026-02-03"])
    backtest = {"start_time": "2025-01-01", "end_time": "2025-12-31"}
    updated = resolve_backtest_window(backtest, calendar, default_start="2025-01-01")
    assert updated["start_time"] == "2025-01-01"
    assert updated["end_time"] == "2026-02-03"


def test_resolve_backtest_window_fills_missing_start_and_end():
    from src.common.market import resolve_backtest_window

    calendar = pd.to_datetime(["2025-01-02", "2025-12-31"])
    updated = resolve_backtest_window({}, calendar, default_start="2025-01-01")
    assert updated["start_time"] == "2025-01-01"
    assert updated["end_time"] == "2025-12-31"

