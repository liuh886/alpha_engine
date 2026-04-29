from __future__ import annotations

from pathlib import Path

import pandas as pd


def test_ensure_calendar_future_file_creates_day_future(tmp_path: Path):
    provider_uri = tmp_path / "watchlist"
    calendars_dir = provider_uri / "calendars"
    calendars_dir.mkdir(parents=True, exist_ok=True)

    (calendars_dir / "day.txt").write_text("2026-01-26\n2026-01-27\n", encoding="utf-8")

    from src.common.future_calendar import ensure_calendar_future_file

    out_path = ensure_calendar_future_file(provider_uri, freq="day", extra_days=1)
    assert out_path == calendars_dir / "day_future.txt"
    assert out_path.exists()

    lines = [ln.strip() for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    boundary = (pd.Timestamp("2026-01-27") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    assert lines[-2:] == ["2026-01-27", boundary]


def test_ensure_calendar_future_file_is_idempotent(tmp_path: Path):
    provider_uri = tmp_path / "watchlist"
    calendars_dir = provider_uri / "calendars"
    calendars_dir.mkdir(parents=True, exist_ok=True)

    (calendars_dir / "day.txt").write_text("2026-01-27\n", encoding="utf-8")

    from src.common.future_calendar import ensure_calendar_future_file

    out_path1 = ensure_calendar_future_file(provider_uri, freq="day", extra_days=1)
    content1 = out_path1.read_text(encoding="utf-8")

    out_path2 = ensure_calendar_future_file(provider_uri, freq="day", extra_days=1)
    content2 = out_path2.read_text(encoding="utf-8")

    assert out_path1 == out_path2
    assert content1 == content2
