from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

import scripts.update_data as update_data
from src.data.quality import generate_data_quality_summary
from src.data.update_accounting import DataUpdateFailure


def _write_provider(
    root: Path,
    *,
    calendar: list[str],
    instrument_ends: dict[str, str],
) -> tuple[Path, Path]:
    provider = root / "provider"
    csv_dir = root / "csv"
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir(parents=True)
    csv_dir.mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text(
        "\n".join(calendar) + "\n", encoding="utf-8"
    )
    rows = []
    for symbol, end in instrument_ends.items():
        rows.append(f"{symbol}\t{calendar[0]}\t{end}")
        (csv_dir / f"{symbol}.csv").write_text(
            "date,open,high,low,close,volume,amount,factor\n"
            f"{end},1,1,1,1,1,1,1\n",
            encoding="utf-8",
        )
    (provider / "instruments" / "cn.txt").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    return provider, csv_dir


def test_declared_interval_does_not_require_data_after_requested_end(tmp_path: Path):
    provider, csv_dir = _write_provider(
        tmp_path,
        calendar=["2026-06-17", "2026-06-18", "2026-06-19", "2026-06-30"],
        instrument_ends={"000300": "2026-06-18", "000001": "2026-06-30"},
    )

    current = generate_data_quality_summary(
        dataset_key="watchlist",
        freq="day",
        provider_uri=provider,
        csv_dir=csv_dir,
        markets=["cn"],
    )
    historical = generate_data_quality_summary(
        dataset_key="watchlist",
        freq="day",
        provider_uri=provider,
        csv_dir=csv_dir,
        markets=["cn"],
        requested_start="2026-06-17",
        requested_end="2026-06-18",
    )

    assert current["freshness_scope"]["mode"] == "current_snapshot"
    assert current["markets"]["cn"]["stale_instruments"] == 1
    assert historical["freshness_scope"] == {
        "mode": "declared_interval",
        "requested_start": "2026-06-17",
        "requested_end": "2026-06-18",
        "effective_calendar_start": "2026-06-17",
        "effective_calendar_end": "2026-06-18",
        "provider_calendar_latest": "2026-06-30",
        "calendar_session_count": 2,
    }
    assert historical["markets"]["cn"]["stale_instruments"] == 0
    assert historical["markets"]["cn"]["csv_stale"] == 0
    assert historical["warnings"] == []


def test_declared_interval_still_fails_closed_inside_requested_scope(tmp_path: Path):
    provider, csv_dir = _write_provider(
        tmp_path,
        calendar=["2026-06-17", "2026-06-18", "2026-06-19"],
        instrument_ends={"000300": "2026-06-18", "000001": "2026-06-19"},
    )

    report = generate_data_quality_summary(
        dataset_key="watchlist",
        freq="day",
        provider_uri=provider,
        csv_dir=csv_dir,
        markets=["cn"],
        requested_end="2026-06-19",
    )

    market = report["markets"]["cn"]
    assert market["stale_instruments"] == 1
    assert market["csv_stale"] == 1
    assert market["stale_symbols_sample"] == ["000300"]
    assert market["stale_details_sample"] == [
        {
            "symbol": "000300",
            "series_end": "2026-06-18",
            "required_calendar_end": "2026-06-19",
            "lag_sessions": 1,
            "scope_classification": "missing_declared_interval_terminal_coverage",
            "cause_classification": "unresolved_provider_or_market_status",
            "possible_causes": [
                "provider_failure",
                "benchmark_or_market_calendar_divergence",
                "suspension_or_non_trading_status",
            ],
        }
    ]
    assert report["warnings"] == [
        "market=cn: 1 missing declared interval terminal coverage (end < 2026-06-19)"
    ]


def test_requested_interval_validation_is_fail_closed():
    args = Namespace(start="2026-06-19", end="2026-06-18", full=True)
    with pytest.raises(DataUpdateFailure, match="on or after"):
        update_data._resolve_requested_interval(args)

    incremental = Namespace(start="2026-01-01", end="2026-06-18", full=False)
    with pytest.raises(DataUpdateFailure, match="requires --full"):
        update_data._resolve_requested_interval(incremental)

    invalid = Namespace(start="2026-01-01", end="not-a-date", full=True)
    with pytest.raises(DataUpdateFailure, match="invalid --end"):
        update_data._resolve_requested_interval(invalid)


def test_requested_interval_is_normalised_for_router_requests():
    args = Namespace(start="2026/01/02", end="2026-06-18 15:30", full=True)
    assert update_data._resolve_requested_interval(args) == (
        "2026-01-02",
        "2026-06-18",
    )
