"""Governed indicator registry validation; no market-data or trading claims."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.governance.indicator_registry import (
    GENERATED_RELATIVE,
    REGISTRY_RELATIVE,
    REPOSITORY_ROOT,
    load_indicator_registry,
    render_typescript,
    synchronize,
    validate_indicator_registry,
)

FIRST_SET = {
    "instrument_sma_20",
    "instrument_sma_50",
    "instrument_sma_200",
    "instrument_ema_12",
    "instrument_ema_26",
    "instrument_rsi_14",
    "instrument_macd_12_26_9",
    "instrument_bollinger_20_2",
    "instrument_volume_sma_20",
    "market_us_vix",
    "market_us_vix_sma_20",
    "market_cn_rdi_reserved",
}


def _document() -> dict:
    return load_indicator_registry(REPOSITORY_ROOT)


def _entry(document: dict, indicator_id: str) -> dict:
    for entry in document["indicators"]:
        if entry["indicator_id"] == indicator_id:
            return entry
    raise AssertionError(f"missing indicator {indicator_id}")


def test_live_registry_is_valid() -> None:
    document = _document()
    validate_indicator_registry(document)


def test_live_registry_keeps_research_boundaries() -> None:
    document = _document()
    assert document["research_only"] is True
    assert document["trade_ready"] is False
    assert document["policy"]["cross_market_indicator_use_allowed"] is False
    assert document["policy"]["forward_fill_or_interpolation_allowed"] is False
    assert document["policy"]["insufficient_data_emits_value"] is False


def test_first_indicator_set_is_declared() -> None:
    ids = {entry["indicator_id"] for entry in _document()["indicators"]}
    assert ids == FIRST_SET


def test_generated_snapshot_is_in_sync_and_deterministic() -> None:
    document = _document()
    first = render_typescript(document, REPOSITORY_ROOT)
    second = render_typescript(document, REPOSITORY_ROOT)
    assert first == second
    assert synchronize(REPOSITORY_ROOT) == first
    generated = Path(REPOSITORY_ROOT) / GENERATED_RELATIVE
    assert generated.read_text(encoding="utf-8") == first
    assert "INDICATOR_REGISTRY_SOURCE_SHA256" in first


def test_unknown_formula_is_rejected() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["formula"] = "vwap"
    with pytest.raises(ValueError, match="not in the implemented formula catalog"):
        validate_indicator_registry(document)

    document = _document()
    document["formula_catalog"]["vwap"] = {
        "version": "1", "params": ["period"], "outputs": ["value"],
    }
    with pytest.raises(ValueError, match="formula_catalog must list exactly"):
        validate_indicator_registry(document)


def test_unknown_scope_and_status_are_rejected() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["scope"] = "global"
    with pytest.raises(ValueError, match="scope must be instrument or market"):
        validate_indicator_registry(document)

    document = _document()
    _entry(document, "instrument_sma_20")["status"] = "certified"
    with pytest.raises(ValueError, match="status must be governed"):
        validate_indicator_registry(document)


def test_invalid_params_are_rejected() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["params"] = {}
    with pytest.raises(ValueError, match="params must be exactly"):
        validate_indicator_registry(document)

    document = _document()
    _entry(document, "instrument_sma_20")["params"] = {"period": 0}
    with pytest.raises(ValueError, match="positive integer"):
        validate_indicator_registry(document)

    document = _document()
    _entry(document, "instrument_sma_20")["params"] = {"period": 20, "extra": 1}
    with pytest.raises(ValueError, match="params must be exactly"):
        validate_indicator_registry(document)

    document = _document()
    _entry(document, "instrument_macd_12_26_9")["params"] = {
        "fast": 26, "slow": 12, "signal": 9,
    }
    with pytest.raises(ValueError, match="fast must be less than slow"):
        validate_indicator_registry(document)


def test_formula_version_must_match_implementation() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["formula_version"] = "2"
    with pytest.raises(ValueError, match="formula_version must be"):
        validate_indicator_registry(document)


def test_unknown_indicator_fields_are_rejected() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["emits_values"] = False
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_indicator_registry(document)


def test_instrument_scope_cannot_declare_a_market() -> None:
    document = _document()
    _entry(document, "instrument_sma_20")["market"] = "us"
    with pytest.raises(ValueError, match="instrument-scope and must not declare a market"):
        validate_indicator_registry(document)


def test_market_series_cannot_cross_markets() -> None:
    document = _document()
    _entry(document, "market_us_vix_sma_20")["market"] = "cn"
    with pytest.raises(ValueError, match="does not match declared market"):
        validate_indicator_registry(document)


def test_volume_indicator_requires_volume_field() -> None:
    document = _document()
    _entry(document, "instrument_volume_sma_20")["inputs"]["field"] = "close"
    with pytest.raises(ValueError, match="must be 'volume'"):
        validate_indicator_registry(document)


def test_market_indicator_cannot_use_volume_formula() -> None:
    document = _document()
    _entry(document, "market_us_vix_sma_20")["formula"] = "volume_sma"
    with pytest.raises(ValueError, match="cannot apply volume_sma"):
        validate_indicator_registry(document)


def test_reserved_family_cannot_be_governed() -> None:
    document = _document()
    _entry(document, "market_cn_rdi_reserved")["status"] = "governed"
    with pytest.raises(ValueError, match="reserved and cannot be governed"):
        validate_indicator_registry(document)


def test_reserved_family_never_declares_a_formula() -> None:
    document = _document()
    _entry(document, "market_cn_rdi_reserved")["formula"] = "sma"
    with pytest.raises(ValueError, match="must not declare a formula or params"):
        validate_indicator_registry(document)


def test_provenance_is_required() -> None:
    document = _document()
    del _entry(document, "instrument_sma_20")["provenance"]["rationale"]
    with pytest.raises(ValueError, match="provenance is incomplete"):
        validate_indicator_registry(document)


def test_vix_entries_are_market_scope_us_series() -> None:
    document = _document()
    raw = _entry(document, "market_us_vix")
    derived = _entry(document, "market_us_vix_sma_20")
    assert raw["scope"] == "market" and raw["market"] == "us"
    assert raw["kind"] == "series" and raw["formula"] is None
    assert raw["inputs"]["series_id"] == "us:VIX"
    assert derived["market"] == "us"
    assert derived["formula"] == "sma"
    assert derived["params"] == {"period": 20}
    assert derived["inputs"]["series_id"] == "us:VIX"


def test_rdi_placeholder_claims_no_values() -> None:
    rdi = _entry(_document(), "market_cn_rdi_reserved")
    assert rdi["scope"] == "market" and rdi["market"] == "cn"
    assert rdi["kind"] == "reserved"
    assert rdi["status"] == "research_only"
    assert rdi["formula"] is None and rdi["formula_version"] is None
    assert rdi["params"] == {}
    assert rdi["inputs"]["series_id"] == "cn:RDI"


def test_registry_rejects_research_boundary_drift() -> None:
    document = _document()
    document["research_only"] = False
    with pytest.raises(ValueError, match="research_only=true"):
        validate_indicator_registry(document)

    document = _document()
    document["trade_ready"] = True
    with pytest.raises(ValueError, match="trade_ready=false"):
        validate_indicator_registry(document)


def test_stale_generated_snapshot_is_detected(tmp_path: Path) -> None:
    registry = tmp_path / REGISTRY_RELATIVE
    registry.parent.mkdir(parents=True)
    shutil.copyfile(Path(REPOSITORY_ROOT) / REGISTRY_RELATIVE, registry)
    generated = tmp_path / GENERATED_RELATIVE
    generated.parent.mkdir(parents=True)
    generated.write_text("stale\n", encoding="utf-8")

    with pytest.raises(ValueError, match="out of date"):
        synchronize(tmp_path)

    synchronize(tmp_path, write=True)
    synchronize(tmp_path)
    assert "INDICATOR_REGISTRY" in generated.read_text(encoding="utf-8")
