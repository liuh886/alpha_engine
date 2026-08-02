from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.us_raw_adjustment_snapshot import (
    HistoricalRevisionError,
    compare_frozen_prefix,
    derive_adjusted_bars,
    directory_identity,
    enforce_append_only,
    formula_identity_sha256,
    normalize_yahoo_raw,
    validate_raw_contract,
    write_model_bars,
    write_raw_contract,
)


def _yahoo_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "Open": [100.0, 102.0, 105.0],
            "High": [103.0, 106.0, 108.0],
            "Low": [99.0, 101.0, 104.0],
            "Close": [102.0, 105.0, 107.0],
            "Adj Close": [51.0, 52.5, 53.5],
            "Volume": [1000.0, 1100.0, 1200.0],
        }
    ).set_index("Date")


def _raw_contract() -> pd.DataFrame:
    return normalize_yahoo_raw(_yahoo_frame())


def test_normalize_yahoo_raw_retains_raw_and_adjustment_evidence() -> None:
    result = _raw_contract()
    assert list(result.columns) == [
        "date",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "adj_close",
        "volume",
        "adjustment_ratio",
    ]
    assert result["adjustment_ratio"].tolist() == [0.5, 0.5, 0.5]
    assert result["raw_close"].tolist() == [102.0, 105.0, 107.0]
    assert result["adj_close"].tolist() == [51.0, 52.5, 53.5]


def test_derive_adjusted_bars_uses_versioned_formula() -> None:
    result = derive_adjusted_bars(_raw_contract())
    assert list(result.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
    ]
    assert result["open"].tolist() == [50.0, 51.0, 52.5]
    assert result["close"].tolist() == [51.0, 52.5, 53.5]
    assert result["volume"].tolist() == [1000.0, 1100.0, 1200.0]
    assert result["factor"].tolist() == [1.0, 1.0, 1.0]
    assert result["amount"].tolist() == [51000.0, 57750.0, 64200.0]
    assert len(formula_identity_sha256()) == 64


def test_persisted_ratio_must_tie_to_raw_close() -> None:
    raw = _raw_contract()
    raw.loc[0, "adjustment_ratio"] = 0.4
    with pytest.raises(ValueError, match="does not tie"):
        validate_raw_contract(raw)


def test_append_only_prefix_allows_new_dates() -> None:
    previous = _raw_contract()
    current = pd.concat(
        [
            previous,
            pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-07")],
                    "raw_open": [108.0],
                    "raw_high": [110.0],
                    "raw_low": [107.0],
                    "raw_close": [109.0],
                    "adj_close": [54.5],
                    "volume": [1300.0],
                    "adjustment_ratio": [0.5],
                }
            ),
        ],
        ignore_index=True,
    )
    report = enforce_append_only(previous, current)
    assert report["historical_prefix_exact"] is True
    assert report["appended_rows"] == 1


def test_append_only_prefix_rejects_historical_adj_close_revision() -> None:
    previous = _raw_contract()
    current = previous.copy()
    current.loc[0, "adj_close"] += 0.00001
    current.loc[0, "adjustment_ratio"] = (
        current.loc[0, "adj_close"] / current.loc[0, "raw_close"]
    )
    report = compare_frozen_prefix(previous, current)
    assert report["historical_prefix_exact"] is False
    assert report["column_exact_difference_counts"]["adj_close"] == 1
    with pytest.raises(HistoricalRevisionError, match="rewrote"):
        enforce_append_only(previous, current)


def test_canonical_writes_and_directory_identity_are_deterministic(
    tmp_path: Path,
) -> None:
    raw = _raw_contract()
    model = derive_adjusted_bars(raw)
    raw_a = tmp_path / "raw_a" / "AAA.csv"
    raw_b = tmp_path / "raw_b" / "AAA.csv"
    model_a = tmp_path / "model_a" / "AAA.csv"
    model_b = tmp_path / "model_b" / "AAA.csv"

    assert write_raw_contract(raw_a, raw) == write_raw_contract(raw_b, raw)
    assert write_model_bars(model_a, model) == write_model_bars(model_b, model)
    assert raw_a.read_bytes() == raw_b.read_bytes()
    assert model_a.read_bytes() == model_b.read_bytes()
    assert directory_identity(raw_a.parent)["identity_sha256"] == directory_identity(
        raw_b.parent
    )["identity_sha256"]
    assert directory_identity(model_a.parent)["identity_sha256"] == directory_identity(
        model_b.parent
    )["identity_sha256"]
