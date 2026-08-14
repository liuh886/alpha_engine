"""Focused tests for exact-cutoff market provider building and identity binding."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.build_market_providers import (
    build_market_provider,
    build_market_providers,
    validate_cutoff,
)
from src.data.market_provider import load_provider_manifest, market_provider_path


def _cn_bars(dates: list[str], closes: list[float]) -> pd.DataFrame:
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": np.arange(len(close), dtype=float) + 100.0,
            "amount": close * (np.arange(len(close), dtype=float) + 100.0),
            "factor": np.ones(len(close), dtype=float),
        }
    )


def _write_source(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _staged_bytes_for_cutoff(frame: pd.DataFrame, cutoff: str) -> bytes:
    cutoff_ts = pd.Timestamp(cutoff)
    kept = frame[pd.to_datetime(frame["date"]) <= cutoff_ts]
    buffer = io.StringIO()
    kept.to_csv(buffer, index=False, lineterminator="\n", encoding="utf-8")
    return buffer.getvalue().encode("utf-8")


def _staged_sha256(frame: pd.DataFrame, cutoff: str) -> str:
    return hashlib.sha256(_staged_bytes_for_cutoff(frame, cutoff)).hexdigest()


def _qlib_close_values(provider: Path) -> np.ndarray:
    values = np.fromfile(provider / "features" / "000001" / "close.day.bin", dtype=np.float32)
    return values[1:]  # drop the int32 start-index header viewed as float32


def _write_cn_sources(csv_dir: Path) -> None:
    _write_source(
        csv_dir / "000001.csv",
        _cn_bars(
            ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
            [10.0, 11.0, 20.0, 21.0],
        ),
    )


# ---------------------------------------------------------------------------
# Default (no-cutoff) compatibility
# ---------------------------------------------------------------------------


def test_default_no_cutoff_preserves_manifest_shape(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_cn_sources(csv_dir)

    manifest = build_market_provider(
        csv_dir=csv_dir,
        provider_dir=tmp_path / "provider",
        market="cn",
    )

    assert "cutoff" not in manifest
    assert load_provider_manifest(tmp_path / "provider", expected_market="cn") is not None
    # No-cutoff keeps full upstream sessions (post-cutoff rows are included).
    assert manifest["calendar"]["last_day"] == "2026-07-02"


def test_default_no_cutoff_identity_is_reproducible(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_cn_sources(csv_dir)

    first = build_market_provider(csv_dir=csv_dir, provider_dir=tmp_path / "p1", market="cn")
    second = build_market_provider(csv_dir=csv_dir, provider_dir=tmp_path / "p2", market="cn")
    assert first["provider_identity_sha256"] == second["provider_identity_sha256"]


# ---------------------------------------------------------------------------
# validate_cutoff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["2026/06/30", "2026-6-30", "not-a-date", "2026-06-30T00:00:00"])
def test_validate_cutoff_rejects_non_iso(bad: str) -> None:
    with pytest.raises(ValueError, match="must be a YYYY-MM-DD ISO date"):
        validate_cutoff(bad)


def test_validate_cutoff_rejects_invalid_calendar_date() -> None:
    with pytest.raises(ValueError, match="valid calendar date"):
        validate_cutoff("2026-02-30")


def test_validate_cutoff_accepts_iso_date() -> None:
    assert validate_cutoff("2026-06-30") == pd.Timestamp("2026-06-30")


# ---------------------------------------------------------------------------
# Exact cutoff staging and provider content
# ---------------------------------------------------------------------------


def test_exact_cutoff_builds_only_rows_at_or_before_cutoff(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_cn_sources(csv_dir)
    provider = tmp_path / "provider"

    manifest = build_market_provider(
        csv_dir=csv_dir,
        provider_dir=provider,
        market="cn",
        cutoff="2026-06-30",
    )

    assert manifest["cutoff"] == "2026-06-30"
    assert manifest["calendar"]["last_day"] == "2026-06-02"
    assert manifest["instruments"]["count"] == 1
    days = [
        line.strip()
        for line in (provider / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert days == ["2026-06-01", "2026-06-02"]
    instrument = (provider / "instruments" / "cn.txt").read_text(encoding="utf-8").strip()
    assert instrument.split("\t")[2] == "2026-06-02"
    assert list(_qlib_close_values(provider)) == [10.0, 11.0]


def test_manifest_source_csvs_bind_staged_cutoff_files(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    frame = _cn_bars(
        ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
        [10.0, 11.0, 20.0, 21.0],
    )
    _write_source(csv_dir / "000001.csv", frame)

    manifest = build_market_provider(
        csv_dir=csv_dir,
        provider_dir=tmp_path / "provider",
        market="cn",
        cutoff="2026-06-30",
    )

    assert manifest["source_csvs"][0]["sha256"] == _staged_sha256(frame, "2026-06-30")


def test_post_cutoff_source_mutation_does_not_change_identity(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    provider = tmp_path / "provider"
    _write_cn_sources(csv_dir)

    before = build_market_provider(
        csv_dir=csv_dir, provider_dir=provider, market="cn", cutoff="2026-06-30"
    )
    # Only a post-cutoff bar changes; the staged cutoff file is identical.
    frame = _cn_bars(
        ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
        [10.0, 11.0, 99.0, 21.0],
    )
    _write_source(csv_dir / "000001.csv", frame)
    after = build_market_provider(
        csv_dir=csv_dir, provider_dir=provider, market="cn", cutoff="2026-06-30"
    )
    assert after["provider_identity_sha256"] == before["provider_identity_sha256"]


def test_pre_cutoff_source_mutation_changes_identity(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    provider = tmp_path / "provider"
    _write_cn_sources(csv_dir)

    before = build_market_provider(
        csv_dir=csv_dir, provider_dir=provider, market="cn", cutoff="2026-06-30"
    )
    frame = _cn_bars(
        ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
        [10.5, 11.0, 20.0, 21.0],
    )
    _write_source(csv_dir / "000001.csv", frame)
    after = build_market_provider(
        csv_dir=csv_dir, provider_dir=provider, market="cn", cutoff="2026-06-30"
    )
    assert after["provider_identity_sha256"] != before["provider_identity_sha256"]


def test_no_cutoff_provider_identity_binds_full_upstream(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    provider = tmp_path / "provider"
    _write_cn_sources(csv_dir)

    before = build_market_provider(csv_dir=csv_dir, provider_dir=provider, market="cn")
    frame = _cn_bars(
        ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
        [10.0, 11.0, 99.0, 21.0],
    )
    _write_source(csv_dir / "000001.csv", frame)
    after = build_market_provider(csv_dir=csv_dir, provider_dir=provider, market="cn")
    assert after["provider_identity_sha256"] != before["provider_identity_sha256"]


# ---------------------------------------------------------------------------
# Deterministic LF identity
# ---------------------------------------------------------------------------


def test_cutoff_identity_is_deterministic_and_lf(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_cn_sources(csv_dir)

    first = build_market_provider(
        csv_dir=csv_dir, provider_dir=tmp_path / "p1", market="cn", cutoff="2026-06-30"
    )
    second = build_market_provider(
        csv_dir=csv_dir, provider_dir=tmp_path / "p2", market="cn", cutoff="2026-06-30"
    )
    assert first["provider_identity_sha256"] == second["provider_identity_sha256"]

    # Provider text outputs are LF-only on every platform.
    for provider in (tmp_path / "p1", tmp_path / "p2"):
        calendar_bytes = (provider / "calendars" / "day.txt").read_bytes()
        instrument_bytes = (provider / "instruments" / "cn.txt").read_bytes()
        assert b"\r\n" not in calendar_bytes
        assert b"\r\n" not in instrument_bytes
        assert calendar_bytes.endswith(b"\n")
        assert instrument_bytes.endswith(b"\n")


def test_build_market_providers_passes_cutoff_through(tmp_path: Path) -> None:
    csv_dir = tmp_path / "data" / "csv_source"
    _write_cn_sources(csv_dir)

    manifests = build_market_providers(
        repository_root=tmp_path,
        csv_dir=csv_dir,
        markets=["cn"],
        cutoff="2026-06-30",
    )
    assert manifests["cn"]["cutoff"] == "2026-06-30"
    assert manifests["cn"]["calendar"]["last_day"] == "2026-06-02"
    assert market_provider_path(tmp_path, "cn") / "provider_manifest.json" is not None


# ---------------------------------------------------------------------------
# Invalid / empty cases
# ---------------------------------------------------------------------------


def test_invalid_cutoff_is_rejected_before_destination(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_cn_sources(csv_dir)
    provider = tmp_path / "provider"
    provider.mkdir()
    sentinel = provider / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YYYY-MM-DD ISO date"):
        build_market_provider(
            csv_dir=csv_dir, provider_dir=provider, market="cn", cutoff="2026/06/30"
        )
    assert sentinel.is_file()


def test_empty_symbol_after_cutoff_is_rejected(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_source(
        csv_dir / "000001.csv",
        _cn_bars(["2026-07-01", "2026-07-02"], [20.0, 21.0]),
    )

    with pytest.raises(ValueError, match="000001.*no rows at or before cutoff 2026-06-30"):
        build_market_provider(
            csv_dir=csv_dir,
            provider_dir=tmp_path / "provider",
            market="cn",
            cutoff="2026-06-30",
        )


def test_unsorted_dates_fail_only_in_cutoff_mode(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    _write_source(
        csv_dir / "000001.csv",
        _cn_bars(["2026-06-02", "2026-06-01"], [11.0, 10.0]),
    )

    build_market_provider(csv_dir=csv_dir, provider_dir=tmp_path / "full", market="cn")
    with pytest.raises(ValueError, match="000001.*ascending order"):
        build_market_provider(
            csv_dir=csv_dir,
            provider_dir=tmp_path / "cut",
            market="cn",
            cutoff="2026-06-30",
        )


def test_duplicate_dates_fail_in_cutoff_mode(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_source"
    frame = _cn_bars(["2026-06-01", "2026-06-02"], [10.0, 11.0])
    frame.loc[1, "date"] = frame.loc[0, "date"]
    _write_source(csv_dir / "000001.csv", frame)

    with pytest.raises(ValueError, match="000001.*duplicate dates"):
        build_market_provider(
            csv_dir=csv_dir,
            provider_dir=tmp_path / "provider",
            market="cn",
            cutoff="2026-06-30",
        )
