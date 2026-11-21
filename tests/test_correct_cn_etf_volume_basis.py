"""Contracts for the governed CN ETF volume-basis correction tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.data.correct_cn_etf_volume_basis import (
    CORRECTION_ALLOWLIST,
    VolumeBasisCorrectionError,
    _canonical_json,
    correct_cn_etf_volume_basis,
)

SESSION = "2026-11-17"
OTHER_SYMBOL = "000001"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _bars() -> list[dict[str, float | str]]:
    return [
        {"time": "2026-11-13", "open": 1.36, "high": 1.374, "low": 1.358, "close": 1.365, "volume": 2844526.0},
        {"time": "2026-11-16", "open": 1.361, "high": 1.384, "low": 1.359, "close": 1.383, "volume": 2787197.0},
        {"time": SESSION, "open": 1.38, "high": 1.38, "low": 1.367, "close": 1.376, "volume": 249556800.0},
        {"time": "2026-11-18", "open": 1.375, "high": 1.385, "low": 1.374, "close": 1.379, "volume": 2377889.0},
        {"time": "2026-11-19", "open": 1.378, "high": 1.38, "low": 1.368, "close": 1.373, "volume": 2185007.0},
        {"time": "2026-11-20", "open": 1.369, "high": 1.369, "low": 1.356, "close": 1.368, "volume": 3051139.0},
    ]


def _symbol_payload(symbol: str, bars: list[dict[str, float | str]]) -> dict:
    return {
        "schema_version": "1.1",
        "evidence_type": "security_market_evidence",
        "market": "cn",
        "symbol": symbol,
        "factor_series": {"ohlcv.liquidity.volume_vs_ma_5d": [{"time": SESSION, "value": 1.0}]},
        "bars": bars,
        "research_only": True,
        "trade_ready": False,
    }


def _build_root(tmp_path: Path) -> Path:
    evidence = tmp_path / "data" / "research" / "market_evidence" / "cn"
    symbols = evidence / "symbols"
    symbols.mkdir(parents=True)
    rows = []
    for symbol, bars in (
        ("515180", _bars()),
        (OTHER_SYMBOL, [{"time": SESSION, "volume": 123.0}]),
    ):
        encoded = _canonical_json(_symbol_payload(symbol, bars))
        (symbols / f"{symbol}.json").write_bytes(encoded)
        rows.append(
            {
                "symbol": symbol,
                "path": f"symbols/{symbol}.json",
                "sha256": _sha256(encoded),
            }
        )
    catalog = {
        "schema_version": "1.1",
        "evidence_type": "market_evidence_catalog",
        "market": "cn",
        "symbols": rows,
    }
    (evidence / "catalog.json").write_bytes(_canonical_json(catalog))
    return tmp_path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_correction_updates_only_allowlisted_row_and_reseals_catalog(
    tmp_path: Path,
) -> None:
    root = _build_root(tmp_path)
    evidence = root / "data" / "research" / "market_evidence" / "cn"
    other_before = (evidence / "symbols" / f"{OTHER_SYMBOL}.json").read_bytes()
    catalog_before = _read(evidence / "catalog.json")
    receipt_path = tmp_path / "receipts" / "correction.json"

    result = correct_cn_etf_volume_basis(
        root, apply=True, receipt_path=receipt_path
    )

    symbol = _read(evidence / "symbols" / "515180.json")
    corrected = next(bar for bar in symbol["bars"] if bar["time"] == SESSION)
    assert corrected["volume"] == 2495568.0
    # Every other bar is byte-identical.
    original_bars = _bars()
    for expected, actual in zip(original_bars, symbol["bars"], strict=True):
        if expected["time"] != SESSION:
            assert actual == expected
    # The derived factor series is deliberately untouched.
    assert symbol["factor_series"] == _symbol_payload("515180", [])["factor_series"]
    # Another symbol is byte-identical.
    assert (evidence / "symbols" / f"{OTHER_SYMBOL}.json").read_bytes() == other_before

    catalog_after = _read(evidence / "catalog.json")
    symbols_after = {row["symbol"]: row for row in catalog_after["symbols"]}
    symbols_before = {row["symbol"]: row for row in catalog_before["symbols"]}
    assert (
        symbols_before[OTHER_SYMBOL]["sha256"]
        == symbols_after[OTHER_SYMBOL]["sha256"]
    )
    assert symbols_after["515180"]["sha256"] == _sha256(
        (evidence / "symbols" / "515180.json").read_bytes()
    )
    # Non-digest catalog fields are unchanged.
    for row_before, row_after in zip(
        catalog_before["symbols"], catalog_after["symbols"], strict=True
    ):
        assert {
            key: value for key, value in row_before.items() if key != "sha256"
        } == {key: value for key, value in row_after.items() if key != "sha256"}

    receipt = _read(receipt_path)
    assert receipt["applied"] is True
    assert receipt["market"] == "cn"
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    correction = receipt["corrections"][0]
    assert correction["symbol"] == "515180"
    assert correction["session"] == SESSION
    assert correction["before_volume"] == 249556800.0
    assert correction["after_volume"] == 2495568.0
    assert correction["shares_per_lot"] == 100.0
    assert receipt["provider_evidence"]["governed_series_basis"] == (
        "provider_reported_lots"
    )
    assert "factor_series" in receipt["derived_series_note"]
    assert result["receipt_sha256"] == _sha256(receipt_path.read_bytes())


def test_correction_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    evidence = root / "data" / "research" / "market_evidence" / "cn"
    symbol_before = (evidence / "symbols" / "515180.json").read_bytes()
    catalog_before = (evidence / "catalog.json").read_bytes()
    receipt_path = tmp_path / "receipts" / "correction.json"

    result = correct_cn_etf_volume_basis(root, apply=False, receipt_path=receipt_path)

    assert result["applied"] is False
    assert (evidence / "symbols" / "515180.json").read_bytes() == symbol_before
    assert (evidence / "catalog.json").read_bytes() == catalog_before
    assert not receipt_path.exists()


def test_correction_refuses_unknown_symbol(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    allowlist = {"999999": CORRECTION_ALLOWLIST["515180"]}

    with pytest.raises(VolumeBasisCorrectionError, match="absent from the catalog"):
        correct_cn_etf_volume_basis(root, allowlist=allowlist, apply=False)


def test_correction_refuses_missing_session(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    allowlist = {
        "515180": {
            "2026-11-21": {
                "before_volume": 249556800.0,
                "shares_per_lot": 100.0,
                "reason": "test",
            }
        }
    }

    with pytest.raises(VolumeBasisCorrectionError, match="expected exactly one bar"):
        correct_cn_etf_volume_basis(root, allowlist=allowlist, apply=False)


def test_correction_refuses_unexpected_before_value(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    allowlist = {
        "515180": {
            SESSION: {
                "before_volume": 300000000.0,
                "shares_per_lot": 100.0,
                "reason": "test",
            }
        }
    }

    with pytest.raises(VolumeBasisCorrectionError, match="does not match recorded before"):
        correct_cn_etf_volume_basis(root, allowlist=allowlist, apply=False)


def test_correction_refuses_double_apply(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    receipt_path = tmp_path / "receipts" / "correction.json"
    correct_cn_etf_volume_basis(root, apply=True, receipt_path=receipt_path)

    with pytest.raises(VolumeBasisCorrectionError, match="already corrected"):
        correct_cn_etf_volume_basis(root, apply=True, receipt_path=receipt_path)


def test_correction_refuses_stale_catalog_digest(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    evidence = root / "data" / "research" / "market_evidence" / "cn"
    catalog = _read(evidence / "catalog.json")
    catalog["symbols"][0]["sha256"] = "0" * 64
    (evidence / "catalog.json").write_bytes(_canonical_json(catalog))

    with pytest.raises(VolumeBasisCorrectionError, match="catalog digest does not match"):
        correct_cn_etf_volume_basis(root, apply=False)


def test_correction_refuses_implausible_lot_basis(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    evidence = root / "data" / "research" / "market_evidence" / "cn"
    symbol = _read(evidence / "symbols" / "515180.json")
    for bar in symbol["bars"]:
        if bar["time"] == SESSION:
            bar["volume"] = 3000.0
    encoded = _canonical_json(symbol)
    (evidence / "symbols" / "515180.json").write_bytes(encoded)
    catalog = _read(evidence / "catalog.json")
    for row in catalog["symbols"]:
        if row["symbol"] == "515180":
            row["sha256"] = _sha256(encoded)
    (evidence / "catalog.json").write_bytes(_canonical_json(catalog))
    allowlist = {
        "515180": {
            SESSION: {
                "before_volume": 3000.0,
                "shares_per_lot": 100.0,
                "reason": "test",
            }
        }
    }

    with pytest.raises(VolumeBasisCorrectionError, match="implausible lot basis"):
        correct_cn_etf_volume_basis(root, allowlist=allowlist, apply=False)
