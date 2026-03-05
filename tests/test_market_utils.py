import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.common.market import resolve_start_date


def test_resolve_start_date_shifts_to_calendar_start():
    calendar = ["2021-01-27", "2021-01-28", "2021-01-29"]
    start, adjusted = resolve_start_date("2021-01-01", calendar)
    assert start == "2021-01-27"
    assert adjusted is True


def test_resolve_start_date_keeps_valid_start():
    calendar = ["2021-01-27", "2021-01-28", "2021-01-29"]
    start, adjusted = resolve_start_date("2021-01-28", calendar)
    assert start == "2021-01-28"
    assert adjusted is False


def test_resolve_start_date_handles_numpy_calendar():
    calendar = np.array(["2021-01-27", "2021-01-28", "2021-01-29"])
    start, adjusted = resolve_start_date("2021-01-01", calendar)
    assert start == "2021-01-27"
    assert adjusted is True


def test_resolve_start_date_shifts_to_next_trading_day():
    calendar = ["2021-01-29", "2021-02-01"]
    start, adjusted = resolve_start_date("2021-01-30", calendar)
    assert start == "2021-02-01"
    assert adjusted is True
