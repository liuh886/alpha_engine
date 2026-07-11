from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import scripts.update_data as update_data
from src.data.symbol_identity import normalize_data_symbol, normalize_data_symbols
from src.research.real_market_acceptance import _resolve_instrument_file


def test_cn_operational_symbols_preserve_leading_zeroes() -> None:
    assert normalize_data_symbol("cn", 69) == "000069"
    assert normalize_data_symbol("cn", "000069") == "000069"
    assert normalize_data_symbol("cn", "SH600000") == "SH600000"
    assert normalize_data_symbols("cn", [69, "000069", 338, "000338"]) == [
        "000069",
        "000338",
    ]


def test_update_universe_normalizes_before_accounting_and_download() -> None:
    universe = update_data.build_selected_universe(
        {"cn": [69, "000069", 338], "us": ["aapl", "AAPL"], "hk": []}
    )

    assert universe == {"cn": ["000069", "000338"], "us": ["AAPL"]}


def test_operational_watchlist_cn_symbols_are_explicit_strings() -> None:
    watchlist = update_data.load_watchlist()

    assert watchlist["cn"]
    assert all(isinstance(symbol, str) for symbol in watchlist["cn"])
    assert all(len(symbol) == 6 for symbol in watchlist["cn"] if symbol.isdigit())


def test_acceptance_prefers_market_instruments_and_falls_back_to_all(tmp_path: Path) -> None:
    instruments = tmp_path / "instruments"
    instruments.mkdir()
    all_path = instruments / "all.txt"
    all_path.write_text("AAPL\t2021-01-01\t2026-06-18\n", encoding="utf-8")

    assert _resolve_instrument_file(tmp_path, "us") == all_path

    market_path = instruments / "us.txt"
    market_path.write_text("MSFT\t2021-01-01\t2026-06-18\n", encoding="utf-8")
    assert _resolve_instrument_file(tmp_path, "us") == market_path


def test_compatibility_provider_stage_preserves_missing_values(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    frame = pd.DataFrame(
        {
            "date": ["2026-06-18", "2026-06-19"],
            "open": [10.0, np.nan],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.0],
            "volume": [100.0, 110.0],
            "amount": [1050.0, 1210.0],
            "factor": [1.0, 1.0],
        }
    )
    frame.to_csv(csv_dir / "000069.csv", index=False)
    provider = tmp_path / "provider"

    update_data.build_provider_stage(
        csv_stage=csv_dir,
        provider_stage=provider,
        universe={"cn": ["000069"]},
    )

    values = np.fromfile(
        provider / "features" / "000069" / "open.day.bin",
        dtype=np.float32,
    )
    assert values[0] == 10.0
    assert np.isnan(values[1])
