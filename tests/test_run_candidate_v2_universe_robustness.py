"""Market-provider contracts for the candidate_v2 US evidence runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_candidate_v2_universe_robustness import (
    _load_us_provider_symbols,
    _verify_us_provider,
)
from src.data.market_provider import write_provider_manifest


def _build_provider(
    provider: Path,
    *,
    market: str = "us",
    write_manifest: bool = True,
) -> None:
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text(
        "2025-01-02\n2025-01-03\n2025-01-06\n",
        encoding="utf-8",
    )
    (provider / "instruments").mkdir()
    (provider / "instruments" / f"{market}.txt").write_text(
        "AAPL\t2025-01-02\t2025-01-06\n"
        "MSFT\t2025-01-02\t2025-01-06\n"
        "QQQ\t2025-01-02\t2025-01-06\n",
        encoding="utf-8",
    )
    (provider / "features").mkdir()
    if write_manifest:
        write_provider_manifest(
            provider,
            market=market,
            source_csv_files=[],
        )


def test_loads_symbols_only_from_market_specific_us_provider(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)

    assert _load_us_provider_symbols(tmp_path) == ["AAPL", "MSFT"]


def test_never_falls_back_to_mixed_watchlist_provider(tmp_path: Path) -> None:
    watchlist = tmp_path / "data" / "watchlist" / "instruments"
    watchlist.mkdir(parents=True)
    (watchlist / "us.txt").write_text(
        "OLD\t2025-01-02\t2025-01-06\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="instrument metadata not found"):
        _load_us_provider_symbols(tmp_path)
    with pytest.raises(FileNotFoundError, match="provider manifest"):
        _verify_us_provider(tmp_path)


def test_valid_us_provider_manifest_passes(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)

    manifest = _verify_us_provider(tmp_path)

    assert manifest["market"] == "us"
    assert manifest["calendar"]["session_count"] == 3
    assert manifest["provider_identity_sha256"]


def test_wrong_market_manifest_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider, market="cn")

    with pytest.raises(ValueError, match="market mismatch"):
        _verify_us_provider(tmp_path)


def test_provider_file_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)
    (provider / "calendars" / "day.txt").write_text(
        "2025-01-02\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calendar hash mismatch"):
        _verify_us_provider(tmp_path)


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider, write_manifest=False)

    with pytest.raises(FileNotFoundError, match="provider manifest"):
        _verify_us_provider(tmp_path)
