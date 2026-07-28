"""Fail-closed source validation before a market provider is replaced."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.build_market_providers import build_market_provider


def _bars(*, valid: bool = True) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": ["2026-07-27", "2026-07-28"],
            "open": [100.0, 102.0],
            "high": [105.0, 107.0],
            "low": [99.0, 101.0],
            "close": [103.0, 105.0],
            "volume": [1_000_000.0, 1_200_000.0],
            "amount": [103_000_000.0, 126_000_000.0],
            "factor": [1.0, 1.0],
        }
    )
    if not valid:
        frame.loc[0, "high"] = 90.0
    return frame


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def test_invalid_source_is_named_and_rejected(tmp_path: Path) -> None:
    source = tmp_path / "csv_source" / "AAPL.csv"
    _write(source, _bars(valid=False))

    with pytest.raises(ValueError, match="AAPL.*preflight validation"):
        build_market_provider(
            csv_dir=source.parent,
            provider_dir=tmp_path / "provider",
            market="us",
        )


def test_missing_date_column_is_named_and_rejected(tmp_path: Path) -> None:
    source = tmp_path / "csv_source" / "AAPL.csv"
    source.parent.mkdir()
    source.write_text("not,a,market,bar\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AAPL.*required date"):
        build_market_provider(
            csv_dir=source.parent,
            provider_dir=tmp_path / "provider",
            market="us",
        )


def test_duplicate_source_dates_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "csv_source" / "AAPL.csv"
    duplicate = _bars()
    duplicate.loc[1, "date"] = duplicate.loc[0, "date"]
    _write(source, duplicate)

    with pytest.raises(ValueError, match="AAPL.*duplicate dates"):
        build_market_provider(
            csv_dir=source.parent,
            provider_dir=tmp_path / "provider",
            market="us",
        )


def test_preflight_failure_preserves_existing_provider(tmp_path: Path) -> None:
    source = tmp_path / "csv_source" / "AAPL.csv"
    provider = tmp_path / "provider"
    _write(source, _bars())
    build_market_provider(
        csv_dir=source.parent,
        provider_dir=provider,
        market="us",
    )
    manifest = provider / "provider_manifest.json"
    before = manifest.read_bytes()

    _write(source, _bars(valid=False))
    with pytest.raises(ValueError, match="AAPL"):
        build_market_provider(
            csv_dir=source.parent,
            provider_dir=provider,
            market="us",
        )

    assert manifest.read_bytes() == before
