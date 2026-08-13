from __future__ import annotations

from datetime import datetime, timezone

from src.research.market_session_clock import completed_market_date


def test_us_in_progress_session_is_excluded() -> None:
    assert completed_market_date(
        "us",
        "2026-08-13",
        now_utc=datetime(2026, 8, 13, 17, 30, tzinfo=timezone.utc),
    ) == "2026-08-12"


def test_us_session_is_admitted_after_regular_close() -> None:
    assert completed_market_date(
        "us",
        "2026-08-13",
        now_utc=datetime(2026, 8, 13, 20, 1, tzinfo=timezone.utc),
    ) == "2026-08-13"


def test_cn_in_progress_session_is_excluded() -> None:
    assert completed_market_date(
        "cn",
        "2026-08-13",
        now_utc=datetime(2026, 8, 13, 6, 30, tzinfo=timezone.utc),
    ) == "2026-08-12"


def test_cn_session_is_admitted_after_regular_close() -> None:
    assert completed_market_date(
        "cn",
        "2026-08-13",
        now_utc=datetime(2026, 8, 13, 7, 1, tzinfo=timezone.utc),
    ) == "2026-08-13"
