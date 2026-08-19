from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.artifacts.us_x1_3_preview import _json_safe, _trade_analytics
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.model_contract import load_performance_semantics

ROOT = Path("data/research/model_runs")
ACTIVE_CATALOG = Path("configs/strategies/registry.json")
MODEL_CONFIG = Path("configs/models/us_x1_3.yaml")


def _catalog() -> dict:
    payload = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _x1_3_record() -> dict:
    catalog = _catalog()
    matches = [
        row
        for row in catalog["records"]
        if row.get("model_version_id") == "us_x1_3"
    ]
    assert len(matches) == 1, "US x1.3 preview must be present exactly once"
    return matches[0]


def _run_root() -> Path:
    record = _x1_3_record()
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
    assert record["model_version_id"] == "us_x1_3"
    manifest = _object("manifest.json")
    validate_manifest(manifest)
    assert manifest["publication_channel"] == "preview"
    assert manifest["publication_status"] == "ci_validated_preview"
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False


def test_us_x1_3_bundle_retains_performance_positions_trades_prices_and_signals() -> None:
    summary = _object("summary.json")
    performance = _object("performance.json")
    portfolio = _object("portfolio.json")
    trades = _object("trades.json")
    assert summary["baseline_status"] == "active_research_baseline"
    assert summary["formal_acceptance_status"] == "prospective_gate_pending"
    assert len(performance["report"]) >= 60
    positions = portfolio["positions"]
    signals = portfolio["signals"]
    assert len(positions) == len(signals) * 15
    latest = portfolio["latest_signal"]
    assert latest["model_version_id"] == "us_x1_3"
    assert len(latest["ranked_targets"]) == 15

    priced = [row for row in positions if row["price"] is not None]
    unpriced = [row for row in positions if row["price"] is None]
    assert all(row.get("window_role") != "prospective_unrealized" for row in unpriced)
    assert all(row.get("realized_return") is not None for row in unpriced)

    latest_positions = [
        row for row in positions if row.get("date") == latest["signal_date"]
    ]
    assert len(latest_positions) == 15
    assert all(row["price"] is not None for row in latest_positions)

    realized_priced = [
        row for row in priced if row.get("holding_status") != "prospective_unrealized"
    ]
    assert all(row["exit_price"] is not None for row in realized_priced[-15:])
    assert latest["signal_date"] == signals[-1]["signal_date"]
    if latest.get("window_role") == "prospective_unrealized":
        assert latest["signal_state"] == "prospective_unrealized"
    else:
        assert latest["holding_end_date"] is not None
        assert latest["signal_date"] == portfolio["latest_realized_signal"]["signal_date"]
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


def test_us_x1_3_lineage_retains_source_hashes_without_treating_metadata_as_model_drift() -> None:
    lineage = _object("lineage.json")
    expected_sources = {
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
    assert lineage["source_model_config"] == MODEL_CONFIG.as_posix()
    assert len(lineage["source_model_config_sha256"]) == 64
    assert len(lineage["provider_identity_sha256"]) == 64

    active = load_active_strategy_catalog(ACTIVE_CATALOG)
    strategy = active.by_strategy_id["us_x"]
    semantics = load_performance_semantics(strategy)
    assert semantics["holding_end_offset_sessions"] == 10
    assert semantics["cost"]["rate_bps"] == 20.0
    assert semantics["research_only"] is True
    assert semantics["trade_ready"] is False


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


def test_us_x1_3_performance_distinguishes_settled_end_from_optional_mtm() -> None:
    manifest = _object("manifest.json")
    performance = _object("performance.json")
    latest = performance["report"][-1]
    cutoff = manifest["evidence_cutoff"]
    if latest.get("provisional_mtm"):
        assert latest["date"] == cutoff
        assert latest["holding_end_date"] == cutoff
        assert performance["date_range"]["end"] == cutoff
        assert latest["signal_date"] <= latest["date"]
        assert latest["mtm_as_of"] == cutoff
        assert latest["settlement_status"] == "provisional_mtm"
        assert latest["trade_ready"] is False
    else:
        settled_end = latest["holding_end_date"]
        assert settled_end <= cutoff
        assert performance["date_range"]["end"] == settled_end
