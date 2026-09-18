"""Incremental dump behavior: appended sessions must preserve existing bytes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.dump_bin import dump_all
from src.research.model_matrix_cache import fingerprint_model_provider


def _write_csv(path: Path, dates: list[str], closes: list[float]) -> None:
    pd.DataFrame({"date": dates, "close": closes}).to_csv(path, index=False)


def _dump(csv_dir: Path, provider: Path) -> None:
    dump_all(
        str(csv_dir),
        str(provider),
        include_fields="close",
        date_field_name="date",
        symbol_field_name="symbol",
    )


def _provider_files(provider: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(provider)): path.read_bytes()
        for path in sorted(provider.rglob("*"))
        if path.is_file()
    }


def _bin_values(provider: Path, symbol: str = "aaa") -> np.ndarray:
    values = np.fromfile(provider / "features" / symbol / "close.day.bin", dtype=np.float32)
    return values[1:]


def test_dump_all_second_run_leaves_files_untouched(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    provider = tmp_path / "provider"

    _dump(csv_dir, provider)
    first_bytes = _provider_files(provider)
    first_mtimes = {
        name: (provider / name).stat().st_mtime_ns for name in first_bytes
    }

    _dump(csv_dir, provider)

    assert _provider_files(provider) == first_bytes
    assert {
        name: (provider / name).stat().st_mtime_ns for name in first_bytes
    } == first_mtimes


def test_dump_all_appends_session_without_rewriting_prefix(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    provider = tmp_path / "provider"
    _dump(csv_dir, provider)

    old_bin = (provider / "features" / "aaa" / "close.day.bin").read_bytes()
    old_calendar = (provider / "calendars" / "day.txt").read_bytes()

    _write_csv(
        csv_dir / "AAA.csv",
        ["2026-01-05", "2026-01-06", "2026-01-07"],
        [10.0, 11.0, 12.5],
    )
    _dump(csv_dir, provider)

    new_bin = (provider / "features" / "aaa" / "close.day.bin").read_bytes()
    assert new_bin.startswith(old_bin)
    assert len(new_bin) == len(old_bin) + 4

    values = _bin_values(provider)
    assert values.tolist() == [10.0, 11.0, 12.5]

    new_calendar = (provider / "calendars" / "day.txt").read_bytes()
    assert new_calendar.startswith(old_calendar)
    assert new_calendar.decode("utf-8").splitlines() == [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
    ]

    instruments = (provider / "instruments" / "us.txt").read_text(encoding="utf-8")
    assert "AAA\t2026-01-05\t2026-01-07" in instruments


def test_dump_all_rewrites_when_history_is_corrected(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    provider = tmp_path / "provider"
    _dump(csv_dir, provider)

    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [99.0, 11.0])
    _dump(csv_dir, provider)

    values = _bin_values(provider)
    assert values[0] == 99.0
    assert values[1] == 11.0


def test_dump_all_new_symbol_keeps_existing_files_as_prefix(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    provider = tmp_path / "provider"
    _dump(csv_dir, provider)

    old_bin = (provider / "features" / "aaa" / "close.day.bin").read_bytes()

    _write_csv(csv_dir / "BBB.csv", ["2026-01-05", "2026-01-06"], [20.0, 21.0])
    _dump(csv_dir, provider)

    new_bin = (provider / "features" / "aaa" / "close.day.bin").read_bytes()
    assert new_bin.startswith(old_bin)
    assert len(new_bin) == len(old_bin)

    bbb = _bin_values(provider, symbol="bbb")
    assert bbb.tolist() == [20.0, 21.0]


def test_dump_append_keeps_scoped_fingerprint_stable(tmp_path: Path) -> None:
    """An appended session outside the retained window must not invalidate the cache."""

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "AAA.csv", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    provider = tmp_path / "provider"
    _dump(csv_dir, provider)

    def _fingerprint() -> str:
        return fingerprint_model_provider(
            provider,
            instrument_file=provider / "instruments" / "us.txt",
            symbols=["AAA"],
            start_time="2026-01-05",
            end_time="2026-01-06",
            lookback_days=0,
            lookahead_days=0,
        )

    first = _fingerprint()

    _write_csv(
        csv_dir / "AAA.csv",
        ["2026-01-05", "2026-01-06", "2026-01-07"],
        [10.0, 11.0, 12.0],
    )
    _dump(csv_dir, provider)

    assert _fingerprint() == first
