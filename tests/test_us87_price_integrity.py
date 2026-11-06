"""US87 price-integrity regression tests: no private data or network calls."""
from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from src.research.cloud_exchange import ExchangeError
from src.research.colab_research_campaign import _common_history
from src.research.us87_price_integrity import (
    _audit_symbol, audit_archive, audit_source, main,
)

SYMBOLS = [f"S{i:03d}" for i in range(87)]


def bar(day: str, close: float) -> dict:
    return {"time": day, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close, "volume": 1000.0}


def source_doc(symbol: str, closes: tuple[float, ...]) -> str:
    bars = [bar(day, close) for day, close in zip(
        ("2026-05-01", "2026-05-04", "2026-05-05"), closes)]
    return json.dumps({"symbol": symbol, "bars": bars})


def fake_files(crwd: bool = True, klac: bool = True) -> dict[str, str]:
    result = {}
    for symbol in [*SYMBOLS, "QQQ"]:
        closes = (100.0, 101.0, 102.0)
        if symbol == "S000" and klac:
            closes = (1000.0, 100.0, 1020.0)
        if symbol == "S001" and crwd:
            closes = (400.0, 100.0, 101.0)
        result[f"data/research/market_evidence/us/symbols/{symbol}.json"] = source_doc(symbol, closes)
    return result


def test_detects_reversed_ten_to_one_and_four_to_one():
    paths = fake_files()
    report = audit_source(read_text=paths.__getitem__, symbols=SYMBOLS,
                          start_date="2026-05-01", end_date="2026-05-05")
    assert report["status"] == "BLOCKED_PRICE_SCALE_INTEGRITY"
    assert [(a["symbol"], a["date"], a["suspected_scale_factor"])
            for a in report["anomalies"]] == [
        ("S000", "2026-05-04", 10),
        ("S000", "2026-05-05", 10),
        ("S001", "2026-05-04", 4)]
    assert report["trade_ready"] is False
    assert report["price_semantics_certified"] is False


def test_clean_data_passes_and_large_ordinary_gain_is_not_assumed_split():
    paths = fake_files(crwd=False, klac=False)
    paths["data/research/market_evidence/us/symbols/S002.json"] = source_doc(
        "S002", (100.0, 180.0, 185.0))
    report = audit_source(read_text=paths.__getitem__, symbols=SYMBOLS,
                          start_date="2026-05-01", end_date="2026-05-05")
    assert report["status"] == "READY_PRICE_SCALE_SCREEN"
    assert report["anomalies"] == []
    assert report["price_semantics_certified"] is False


def test_rejects_unsorted_bars_and_invalid_prices():
    with pytest.raises(ExchangeError, match="duplicate/unsorted"):
        _audit_symbol("S000", [bar("2026-05-04", 100.0),
                                bar("2026-05-04", 100.0)], "2026-05-01", "2026-05-05")
    broken = bar("2026-05-04", 100)
    broken["close"] = 150
    with pytest.raises(ExchangeError, match="inconsistent OHLCV"):
        _audit_symbol("S000", [broken], "2026-05-01", "2026-05-05")


def test_archive_cli_fails_closed_and_preserves_input(tmp_path):
    paths = fake_files()
    archive = tmp_path / "raw-v5.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("files/configs/research_universes/us_selected_equities_v2.yaml",
                   "symbols:\n" + "".join(f"  - {s}\n" for s in SYMBOLS))
        for path, data in paths.items():
            z.writestr("files/" + path, data)
    before = archive.read_bytes()
    output = tmp_path / "audit.json"
    assert main(["--archive", str(archive), "--start-date", "2026-05-01",
                 "--end-date", "2026-05-05", "--report-file", str(output)]) == 10
    assert archive.read_bytes() == before
    assert json.loads(output.read_text())["anomaly_count"] == 3


def test_common_history_blocks_before_any_fitting(tmp_path):
    paths = fake_files()
    root = tmp_path / "stage"
    pool = root / "configs/research_universes/us_selected_equities_v2.yaml"
    pool.parent.mkdir(parents=True)
    pool.write_text("symbols:\n" + "".join(f"  - {s}\n" for s in SYMBOLS))
    for rel, data in paths.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
    spec = {"study": {"train_start": "2026-05-01"}}
    sessions = ["2026-05-01", "2026-05-04", "2026-05-05"]
    with pytest.raises(ExchangeError, match="BLOCKED_PRICE_SCALE_INTEGRITY.*S000"):
        _common_history(spec, root, sessions, date(2026, 5, 5))
    # Only independently corrected source data may qualify later; test illustrates gate.
    paths = fake_files(crwd=False, klac=False)
    for rel, data in paths.items():
        (root / rel).write_text(data)
    outcome = _common_history(spec, root, sessions, date(2026, 5, 5))
    assert outcome["common_sessions"] == 3

def test_upstream_csv_refresh_replaces_dirty_history_instead_of_incremental_append(tmp_path):
    import pandas as pd
    from scripts.data.refresh_selected_pool_prices import _audit_source, _source_needs_refresh
    from src.research.us87_price_integrity import audit_dataframe

    csv = tmp_path / "KLAC.csv"
    rows = [bar(day, close) for day, close in zip(
        ("2026-05-01", "2026-05-04", "2026-05-05"),
        (1000.0, 100.0, 1020.0))]
    for row in rows:
        row["date"] = row.pop("time")
        row["amount"] = row["close"] * row["volume"]
        row["factor"] = 1.0
    pd.DataFrame(rows).to_csv(csv, index=False)

    before = _audit_source(csv, "KLAC", market="us")
    assert before["status"] == "invalid"
    assert "BLOCKED_PRICE_SCALE_INTEGRITY" in before["errors"][0]
    assert _source_needs_refresh(before, cutoff="2026-05-05")
    # A short incremental tail cannot clean contaminated earlier observations.
    assert len(audit_dataframe(pd.read_csv(csv).assign(
        date=lambda d: pd.to_datetime(d["date"])), symbol="KLAC")) == 2

    # Model a properly re-fetched full adjusted-price edition from a provider.
    rows[0].update(open=100, close=100, high=101, low=99)
    rows[2].update(open=102, close=102, high=103.02, low=100.98)
    pd.DataFrame(rows).to_csv(csv, index=False)
    after = _audit_source(csv, "KLAC", market="us")
    assert after["status"] == "ready"
    assert not _source_needs_refresh(after, cutoff="2026-05-05")
