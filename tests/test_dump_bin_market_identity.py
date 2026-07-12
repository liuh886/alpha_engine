from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.build_market_providers import build_market_providers
from scripts.dump_bin import dump_all
from src.data.market_provider import (
    load_provider_manifest,
    market_provider_path,
)
from src.data.symbol_identity import infer_data_market, normalize_data_symbol


def _write_csv(
    path: Path,
    *,
    dates: list[str] | None = None,
    closes: list[float] | None = None,
    missing_second_open: bool = False,
) -> None:
    selected_dates = dates or ["2026-06-18", "2026-06-19"]
    selected_closes = closes or [10.5, 11.0]
    if len(selected_dates) != len(selected_closes):
        raise ValueError("dates and closes must have the same length")
    close = np.asarray(selected_closes, dtype=float)
    frame = pd.DataFrame(
        {
            "date": selected_dates,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": np.arange(len(close), dtype=float) + 100.0,
            "amount": close * (np.arange(len(close), dtype=float) + 100.0),
            "factor": np.ones(len(close), dtype=float),
        }
    )
    if missing_second_open and len(frame) > 1:
        frame.loc[1, "open"] = np.nan
    frame.to_csv(path, index=False)


def _read_qlib_values(path: Path) -> np.ndarray:
    values = np.fromfile(path, dtype=np.float32)
    return values[1:]  # drop the int32 start-index header viewed as float32


def test_symbol_identity_normalizes_legacy_cn_numeric_names() -> None:
    assert infer_data_market("69") == "cn"
    assert normalize_data_symbol("cn", 69) == "000069"
    assert normalize_data_symbol("cn", "000069") == "000069"
    assert infer_data_market("00700.HK") == "hk"
    assert infer_data_market("aapl") == "us"


def test_dump_all_writes_all_and_market_specific_instruments(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "69.csv", missing_second_open=True)
    _write_csv(csv_dir / "AAPL.csv")
    _write_csv(csv_dir / "00700.HK.csv")
    provider = tmp_path / "provider"

    dump_all(
        str(csv_dir),
        str(provider),
        include_fields="open,high,low,close,volume,amount,factor",
    )

    all_text = (provider / "instruments" / "all.txt").read_text(encoding="utf-8")
    cn_text = (provider / "instruments" / "cn.txt").read_text(encoding="utf-8")
    us_text = (provider / "instruments" / "us.txt").read_text(encoding="utf-8")
    hk_text = (provider / "instruments" / "hk.txt").read_text(encoding="utf-8")

    assert "000069\t" in all_text and "AAPL\t" in all_text and "00700.HK\t" in all_text
    assert cn_text.startswith("000069\t")
    assert us_text.startswith("AAPL\t")
    assert hk_text.startswith("00700.HK\t")
    assert (provider / "features" / "000069" / "open.day.bin").is_file()
    assert (provider / "features" / "aapl" / "close.day.bin").is_file()
    assert not (provider / "features" / "AAPL").exists()

    values = np.fromfile(
        provider / "features" / "000069" / "open.day.bin",
        dtype=np.float32,
    )
    assert values[0] == 0.0  # Qlib start-index header
    assert values[1] == 10.0
    assert np.isnan(values[2])


def test_dump_all_rejects_normalized_symbol_collisions(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _write_csv(csv_dir / "69.csv")
    _write_csv(csv_dir / "000069.csv")

    with pytest.raises(ValueError, match="collide after normalization"):
        dump_all(str(csv_dir), str(tmp_path / "provider"), include_fields="close")


def test_market_providers_use_only_their_own_sessions_and_symbols(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "data" / "csv_source"
    csv_dir.mkdir(parents=True)

    cn_dates = [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
        "2026-01-13",
        "2026-01-14",
        "2026-01-15",
        "2026-01-16",
        "2026-01-19",
        "2026-01-20",
    ]
    us_dates = [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
        "2026-01-13",
        "2026-01-14",
        "2026-01-15",
        "2026-01-16",
        "2026-01-20",
        "2026-01-21",
    ]
    cn_close = [100.0 + index for index in range(len(cn_dates))]
    us_close = [200.0 + index for index in range(len(us_dates))]
    _write_csv(csv_dir / "000069.csv", dates=cn_dates, closes=cn_close)
    _write_csv(csv_dir / "AAPL.csv", dates=us_dates, closes=us_close)

    manifests = build_market_providers(
        repository_root=tmp_path,
        csv_dir=csv_dir,
        markets=["cn", "us"],
    )

    cn_provider = market_provider_path(tmp_path, "cn")
    us_provider = market_provider_path(tmp_path, "us")
    assert (cn_provider / "calendars" / "day.txt").read_text(
        encoding="utf-8"
    ).splitlines() == cn_dates
    assert (us_provider / "calendars" / "day.txt").read_text(
        encoding="utf-8"
    ).splitlines() == us_dates
    assert "AAPL" not in (cn_provider / "instruments" / "cn.txt").read_text(
        encoding="utf-8"
    )
    assert "000069" not in (us_provider / "instruments" / "us.txt").read_text(
        encoding="utf-8"
    )

    cn_values = _read_qlib_values(
        cn_provider / "features" / "000069" / "close.day.bin"
    )
    us_values = _read_qlib_values(
        us_provider / "features" / "aapl" / "close.day.bin"
    )
    assert cn_dates[10] == "2026-01-19"
    assert us_dates[10] == "2026-01-20"
    assert np.isclose(cn_values[10] / cn_values[0] - 1.0, cn_close[10] / cn_close[0] - 1.0)
    assert np.isclose(us_values[10] / us_values[0] - 1.0, us_close[10] / us_close[0] - 1.0)
    assert manifests["cn"]["provider_identity_sha256"] != manifests["us"][
        "provider_identity_sha256"
    ]


def test_provider_manifest_detects_feature_mutation(tmp_path: Path) -> None:
    csv_dir = tmp_path / "data" / "csv_source"
    csv_dir.mkdir(parents=True)
    _write_csv(csv_dir / "AAPL.csv")
    build_market_providers(
        repository_root=tmp_path,
        csv_dir=csv_dir,
        markets=["us"],
    )
    provider = market_provider_path(tmp_path, "us")
    assert load_provider_manifest(provider, expected_market="us") is not None

    feature = provider / "features" / "aapl" / "close.day.bin"
    feature.write_bytes(feature.read_bytes() + b"mutation")
    with pytest.raises(ValueError, match="feature-tree hash mismatch"):
        load_provider_manifest(provider, expected_market="us")


def test_operational_watchlist_has_explicit_cn_strings() -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / "watchlist.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)
    assert payload["cn"]
    assert all(isinstance(symbol, str) for symbol in payload["cn"])
    assert all(len(symbol) == 6 for symbol in payload["cn"] if symbol.isdigit())
    assert len(payload["cn"]) == len(set(payload["cn"]))
