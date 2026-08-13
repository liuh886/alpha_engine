from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from src.artifacts.formal_bundle_reader import load_formal_run
from src.governance.active_strategy_catalog import load_active_strategy_catalog

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_model_x1_baselines.py"
ACTIVE_CATALOG = ROOT / "configs/strategies/registry.json"


def _load_validator() -> ModuleType:
    name = "validate_model_x1_baselines"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _cn_refresh_state() -> dict:
    return load_formal_run(ROOT, "cn_x1_1").refresh_state()


def test_active_strategy_catalog_owns_current_x1_identities() -> None:
    catalog = load_active_strategy_catalog(ACTIVE_CATALOG)
    assert catalog.by_strategy_id["us_x"].model_version_id == "us_x1_3"
    assert catalog.by_strategy_id["cn_x"].model_version_id == "cn_x1_1"
    assert catalog.by_strategy_id["us_x"].historical_evidence_access == "public"
    assert catalog.by_strategy_id["cn_x"].historical_evidence_access == "public"


def test_model_configs_and_evidence_tie_across_lifecycle() -> None:
    module = _load_validator()
    result = module.validate_registry(ROOT)
    assert result["status"] == "x1_lifecycle_valid"
    assert result["active_strategy_catalog"] == "configs/strategies/registry.json"
    assert result["active_baselines"] == {
        "us": "us_x1_3",
        "cn": "cn_x1_1",
    }
    assert [item["model_id"] for item in result["models"]] == [
        "cn_x1_0",
        "cn_x1_1",
        "us_x1_0",
        "us_x1_1",
        "us_x1_2",
        "us_x1_3",
    ]
    cn_x1_1 = next(item for item in result["models"] if item["model_id"] == "cn_x1_1")
    assert cn_x1_1["evidence_completeness"] == "complete"
    us_x1_2 = next(item for item in result["models"] if item["model_id"] == "us_x1_2")
    assert us_x1_2["status"] == "historical_baseline_superseded"
    assert us_x1_2["selected_candidate"] == "r11_sampled"
    us_x1_3 = next(item for item in result["models"] if item["model_id"] == "us_x1_3")
    assert us_x1_3["selected_candidate"] == "mvv_plus_pressure"
    assert us_x1_3["factor_count"] == 13
    assert us_x1_3["prospective_acceptance_pending"] is True
    assert all(item["trade_ready"] is False for item in result["models"])


def test_us_x1_2_receipt_remains_historical_evidence() -> None:
    receipt = json.loads(
        (ROOT / "data/research/experiment_receipts/us_x1_2_certification_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["selected_development_winner"] == "r11_sampled"
    assert receipt["determinism"]["exact"] is True
    assert receipt["fresh_partial_challenge"]["all_gates_pass"] is False
    assert receipt["governance"]["formal_acceptance_supported"] is False


def test_us_x1_3_receipt_is_stage_b_supported_but_not_trade_ready() -> None:
    receipt = json.loads(
        (ROOT / "data/research/experiment_receipts/us_x1_3_stage_b_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["winner"] == "mvv_plus_pressure"
    assert receipt["stage_b_supported"] is True
    assert receipt["supported"] is True
    assert receipt["support_boundary"]["positive_window_count"] == 4
    assert receipt["support_boundary"]["exact_score_reproduction"] is True
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False


def test_cn_registry_accepts_append_only_publication_cutoff_extension() -> None:
    module = _load_validator()
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_1.yaml").read_text())
    package = _cn_refresh_state()
    package["evidence_cutoff"] = "2026-08-13"
    module._validate_cn_formal_extension(package, config)


def test_cn_registry_rejects_frozen_evidence_truncation() -> None:
    module = _load_validator()
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_1.yaml").read_text())
    package = _cn_refresh_state()
    minimum = int(config["backtest_evidence"]["complete_formal_path"]["rebalance_count"])
    package["report"] = package["report"][: minimum - 1]
    with pytest.raises(ValueError, match="frozen report prefix"):
        module._validate_cn_formal_extension(package, config)
