from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.artifacts.us_x1_3_preview import _json_safe, _trade_analytics

ROOT = Path("data/research/model_runs")
ACTIVE_CATALOG = Path("configs/strategies/registry.json")
MODEL_CONFIG = Path("configs/models/us_x1_3.yaml")


def _catalog() -> dict:
    payload = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _x1_3_record() -> dict | None:
    catalog = _catalog()
    matches = [
        row
        for row in catalog["records"]
        if row.get("model_version_id") == "us_x1_3"
    ]
    assert len(matches) <= 1
    return matches[0] if matches else None


def _assert_valid_prepublication_cutover() -> None:
    """Prove the repository still carries genuine predecessor preview evidence.

    This state is valid only before Reviewed Formal Backtest Refresh has built the
    successor. We never relabel x1.2 preview bytes as x1.3; after candidate
    generation `_x1_3_record()` becomes non-null and the full publication tests
    below execute normally.
    """
    catalog = _catalog()
    validate_catalog(catalog)
    preview_ids = [row["model_version_id"] for row in catalog["records"]]
    assert "us_x1_3" not in preview_ids
    assert "us_x1_2" in preview_ids

    active = json.loads(ACTIVE_CATALOG.read_text(encoding="utf-8"))
    us_strategy = next(row for row in active["strategies"] if row["strategy_id"] == "us_x")
    assert us_strategy["model_version_id"] == "us_x1_3"
    assert us_strategy["signal_ledger"].endswith("/us_x1_3")

    model = yaml.safe_load(MODEL_CONFIG.read_text(encoding="utf-8"))
    assert model["model_id"] == "us_x1_3"
    assert model["lineage"]["supersedes"] == "us_x1_2"
    assert model["lineage"]["selected_candidate"] == "mvv_plus_pressure"
    assert model["research_only"] is True
    assert model["trade_ready"] is False


def _run_root() -> Path:
    record = _x1_3_record()
    assert record is not None, "US x1.3 preview has not been generated"
    return ROOT / Path(record["manifest_path"]).parent


def _object(name: str) -> dict:
    payload = json.loads((_run_root() / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_active_us_x1_3_preview_is_cataloged_without_crossing_formal_boundary() -> None:
    catalog = _catalog()
    validate_catalog(catalog)
    assert catalog["channel"] == "preview"
    record = _x1_3_record()
    if record is None:
        _assert_valid_prepublication_cutover()
        return
    assert [row["model_version_id"] for row in catalog["records"]] == ["us_x1_3"]
    manifest = _object("manifest.json")
    validate_manifest(manifest)
    assert manifest["publication_channel"] == "preview"
    assert manifest["publication_status"] == "ci_validated_preview"
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False


def test_us_x1_3_bundle_retains_performance_positions_trades_prices_and_signals() -> None:
    if _x1_3_record() is None:
        _assert_valid_prepublication_cutover()
        return
    summary = _object("summary.json")
    performance = _object("performance.json")
    portfolio = _object("portfolio.json")
    trades = _object("trades.json")
    assert summary["baseline_status"] == "active_research_baseline"
    assert summary["formal_acceptance_status"] == "prospective_gate_pending"
    assert len(performance["report"]) >= 60
    assert len(portfolio["positions"]) == len(portfolio["signals"]) * 15
    assert portfolio["latest_signal"]["model_version_id"] == "us_x1_3"
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


def test_us_x1_3_lineage_can_skip_content_identical_refreshes() -> None:
    if _x1_3_record() is None:
        _assert_valid_prepublication_cutover()
        return
    lineage = _object("lineage.json")
    expected_sources = {
        "source_model_config_sha256": Path("configs/models/us_x1_3.yaml"),
        "builder_source_sha256": Path("src/artifacts/us_x1_3_preview.py"),
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


def test_us_x1_3_chart_reaches_evidence_cutoff_with_provisional_mtm() -> None:
    if _x1_3_record() is None:
        _assert_valid_prepublication_cutover()
        return
    manifest = _object("manifest.json")
    performance = _object("performance.json")
    assert performance["report"][-1]["date"] == manifest["evidence_cutoff"]
    assert performance["report"][-1]["holding_end_date"] == manifest["evidence_cutoff"]
    assert performance["date_range"]["end"] == manifest["evidence_cutoff"]
    if performance["report"][-1].get("provisional_mtm"):
        assert performance["report"][-1]["settlement_status"] == "provisional_mtm"
        assert performance["report"][-1]["trade_ready"] is False
