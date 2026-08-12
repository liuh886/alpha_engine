from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.artifacts.us_x1_2_preview import _json_safe, _trade_analytics

ROOT = Path("data/research/model_runs")


def _catalog() -> dict:
    payload = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _run_root() -> Path:
    catalog = _catalog()
    matches = [
        row
        for row in catalog["records"]
        if row.get("model_version_id") == "us_x1_2"
    ]
    assert len(matches) == 1
    return ROOT / Path(matches[0]["manifest_path"]).parent


def _object(name: str) -> dict:
    payload = json.loads((_run_root() / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_active_us_x1_2_preview_is_cataloged_without_crossing_formal_boundary() -> None:
    catalog = _catalog()
    validate_catalog(catalog)
    assert catalog["channel"] == "preview"
    assert [row["model_version_id"] for row in catalog["records"]] == ["us_x1_2"]
    manifest = _object("manifest.json")
    validate_manifest(manifest)
    assert manifest["publication_channel"] == "preview"
    assert manifest["publication_status"] == "ci_validated_preview"
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False


def test_us_x1_2_bundle_retains_performance_positions_trades_prices_and_signals() -> None:
    summary = _object("summary.json")
    performance = _object("performance.json")
    portfolio = _object("portfolio.json")
    trades = _object("trades.json")
    assert summary["baseline_status"] == "active_research_baseline"
    assert summary["formal_acceptance_status"] == "prospective_gate_pending"
    assert len(performance["report"]) >= 60
    assert len(portfolio["positions"]) == len(portfolio["signals"]) * 15
    assert portfolio["latest_signal"]["model_version_id"] == "us_x1_2"
    assert len(portfolio["latest_signal"]["ranked_targets"]) == 15
    priced = [row for row in portfolio["positions"] if row["price"] is not None]
    assert len(priced) > 850
    realized_priced = [
        row for row in priced if row.get("holding_status") != "prospective_unrealized"
    ]
    assert all(row["exit_price"] is not None for row in realized_priced[-15:])
    assert portfolio["latest_signal"]["signal_date"] == portfolio["signals"][-1]["signal_date"]
    assert portfolio["latest_signal"]["signal_state"] == portfolio["signals"][-1]["signal_state"]
    assert len(trades["records"]) > 1_000
    assert any(row["action"] == "BUY" for row in trades["records"])
    assert any(row["action"] == "SELL" for row in trades["records"])
    assert any(row["entry_price"] is not None for row in trades["records"])
    assert any(row["exit_price"] is not None for row in trades["records"])
    assert trades["analytics"]["win_rate"] > 0
    assert trades["analytics"]["alpha_hit_rate"] > 0
    assert trades["analytics"]["quantity_available"] is False
    assert all(row["amount"] is None for row in trades["records"])
    assert all(row["normalized_notional"] >= 0 for row in trades["records"])


def test_us_x1_2_lineage_can_skip_content_identical_refreshes() -> None:
    lineage = _object("lineage.json")
    expected_sources = {
        "source_model_config_sha256": Path("configs/models/us_x1_2.yaml"),
        "builder_source_sha256": Path("src/artifacts/us_x1_2_preview.py"),
        "factor_library_sha256": Path("configs/factor_libraries/ohlcv.yaml"),
        "universe_config_sha256": Path("configs/research_universes/us_selected_equities_v2.yaml"),
        "classification_config_sha256": Path(
            "configs/research_classifications/us87_sector_industry_v1.yaml"
        ),
    }
    expected = {
        field: hashlib.sha256(path.read_bytes()).hexdigest()
        for field, path in expected_sources.items()
    }
    actual = {field: lineage.get(field) for field in expected_sources}
    assert actual == expected
    assert len(lineage["provider_identity_sha256"]) == 64


def test_trade_analytics_and_json_normalization_do_not_fabricate_missing_values() -> None:
    positions = [
        {"realized_return": 0.1, "excess_return": 0.04},
        {"realized_return": -0.05, "excess_return": -0.02},
    ]
    trades = [{"weight_delta": 0.25}, {"weight_delta": -0.25}]
    analytics = _trade_analytics(positions, trades)
    assert analytics["win_rate"] == 0.5
    assert analytics["alpha_hit_rate"] == 0.5
    assert analytics["normalized_notional"] == 0.5
    assert _json_safe({"missing": float("nan")}) == {"missing": None}
