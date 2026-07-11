from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.dump_bin import dump_all
from src.data.symbol_identity import infer_data_market, normalize_data_symbol


def _write_csv(path: Path, *, missing_second_open: bool = False) -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-06-18", "2026-06-19"],
            "open": [10.0, np.nan if missing_second_open else 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.0],
            "volume": [100.0, 110.0],
            "amount": [1050.0, 1210.0],
            "factor": [1.0, 1.0],
        }
    )
    frame.to_csv(path, index=False)


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


def test_operational_watchlist_has_explicit_cn_strings() -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / "watchlist.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)
    assert payload["cn"]
    assert all(isinstance(symbol, str) for symbol in payload["cn"])
    assert all(len(symbol) == 6 for symbol in payload["cn"] if symbol.isdigit())
    assert len(payload["cn"]) == len(set(payload["cn"]))
