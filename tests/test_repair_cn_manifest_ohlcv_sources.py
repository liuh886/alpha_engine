"""Contracts for isolated, manifest-pinned CN OHLCV repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from scripts.repair_cn_manifest_ohlcv_sources import (
    repair_cn_manifest_ohlcv_sources,
)
from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    FetchResult,
)
from src.data.market_provider import write_provider_manifest
from src.data.router import MarketDataRouter


def _bars(*, invalid: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=10)
    close = pd.Series(range(10), dtype=float) + 10.0
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000.0,
            "amount": close * 1_000.0,
            "factor": 1.0,
        }
    )
    if invalid:
        frame.loc[3, "high"] = frame.loc[3, "close"] - 1.0
    return frame


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _write_manifest(provider_dir: Path, sources: list[Path]) -> Path:
    (provider_dir / "calendars").mkdir(parents=True)
    (provider_dir / "features").mkdir()
    (provider_dir / "instruments").mkdir()
    (provider_dir / "calendars" / "day.txt").write_text(
        "2024-01-02\n",
        encoding="utf-8",
    )
    (provider_dir / "instruments" / "cn.txt").write_text(
        "000001\t2024-01-02\t2024-01-15\n",
        encoding="utf-8",
    )
    write_provider_manifest(
        provider_dir,
        market="cn",
        source_csv_files=sources,
    )
    return provider_dir / "provider_manifest.json"


@dataclass
class _FakeAdapter:
    _name: str
    dates: pd.DatetimeIndex | None = None
    fails: bool = False

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        if self.fails:
            raise DataFetchError("expected provider failure")
        frame = _bars()
        if self.dates is not None:
            frame = frame.loc[
                frame["date"].isin(self.dates)
            ].reset_index(drop=True)
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=f"provider:{req.symbol}",
        )


def _router(*adapters: _FakeAdapter) -> MarketDataRouter:
    return MarketDataRouter(
        adapters=adapters,
        policy={"cn": [adapter.name for adapter in adapters]},
    )


def test_isolated_repair_preserves_inputs_and_records_fallback(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    valid = _write_csv(source_dir / "000001.csv", _bars())
    invalid = _write_csv(source_dir / "000002.csv", _bars(invalid=True))
    original_bytes = {path.name: path.read_bytes() for path in (valid, invalid)}
    manifest_path = _write_manifest(
        tmp_path / "original_provider",
        [valid, invalid],
    )
    output = tmp_path / "repaired"

    result = repair_cn_manifest_ohlcv_sources(
        original_manifest_path=manifest_path,
        source_csv_dirs=[source_dir],
        output_root=output,
        router=_router(
            _FakeAdapter("efinance", fails=True),
            _FakeAdapter("akshare"),
        ),
    )

    assert result["source_count"] == 2
    assert result["invalid_before"] == 1
    assert result["invalid_after"] == 0
    assert result["replacements"][0]["selected_provider"] == "akshare"
    assert len(result["replacements"][0]["attempts"]) == 2
    assert result["research_only"] is True
    assert result["promotion_eligible"] is False
    assert result["trade_ready"] is False
    assert valid.read_bytes() == original_bytes[valid.name]
    assert invalid.read_bytes() == original_bytes[invalid.name]
    assert (
        output / "data" / "providers" / "cn" / "provider_manifest.json"
    ).is_file()
    durable = json.loads(
        (
            output
            / "artifacts"
            / "evidence"
            / "cn_ohlcv_repair"
            / "repair_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert str(tmp_path.resolve()) not in json.dumps(durable)


def test_manifest_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source = _write_csv(source_dir / "000001.csv", _bars())
    manifest_path = _write_manifest(tmp_path / "provider", [source])
    source.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        repair_cn_manifest_ohlcv_sources(
            original_manifest_path=manifest_path,
            source_csv_dirs=[source_dir],
            output_root=tmp_path / "output",
            router=_router(_FakeAdapter("akshare")),
        )


def test_replacement_with_insufficient_coverage_is_rejected_atomically(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source = _write_csv(source_dir / "000002.csv", _bars(invalid=True))
    manifest_path = _write_manifest(tmp_path / "provider", [source])
    output = tmp_path / "output"

    with pytest.raises(RuntimeError, match="overlap"):
        repair_cn_manifest_ohlcv_sources(
            original_manifest_path=manifest_path,
            source_csv_dirs=[source_dir],
            output_root=output,
            router=_router(
                _FakeAdapter(
                    "akshare",
                    dates=pd.bdate_range("2024-01-02", periods=5),
                )
            ),
        )

    assert not output.exists()


def test_nonempty_output_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        repair_cn_manifest_ohlcv_sources(
            original_manifest_path=tmp_path / "provider_manifest.json",
            source_csv_dirs=[tmp_path],
            output_root=output,
        )

    assert marker.read_text(encoding="utf-8") == "keep"
