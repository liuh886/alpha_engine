from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

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


def test_active_strategy_catalog_owns_current_x1_identities() -> None:
    catalog = load_active_strategy_catalog(ACTIVE_CATALOG)
    assert catalog.by_strategy_id["us_x"].model_version_id == "us_x1_3"
    assert catalog.by_strategy_id["cn_x"].model_version_id == "cn_x1_1"
    assert catalog.by_strategy_id["us_x"].historical_evidence_access == "public"
    assert catalog.by_strategy_id["cn_x"].historical_evidence_access == "public"


def test_model_configs_notebooks_and_frozen_specs_tie() -> None:
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
        "us_x1_3",
    ]
    cn_x1_1 = next(item for item in result["models"] if item["model_id"] == "cn_x1_1")
    assert cn_x1_1["evidence_completeness"] == "complete"
    us_x1_2 = next(item for item in result["models"] if item["model_id"] == "us_x1_3")
    assert us_x1_2["selected_candidate"] == "r11_sampled"
    assert us_x1_2["prospective_acceptance_pending"] is True
    assert all(item["trade_ready"] is False for item in result["models"])


def test_us_x1_2_receipt_keeps_failed_prospective_gate_explicit() -> None:
    receipt = json.loads(
        (ROOT / "data/research/experiment_receipts/us_x1_2_certification_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["selected_development_winner"] == "r11_sampled"
    assert receipt["determinism"]["exact"] is True
    assert receipt["fresh_partial_challenge"]["all_gates_pass"] is False
    assert receipt["governance"]["formal_acceptance_supported"] is False
    assert receipt["governance"]["active_baseline_remains"] == "us_x1_1"


def test_cn_registry_accepts_append_only_publication_cutoff_extension() -> None:
    module = _load_validator()
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_1.yaml").read_text())
    package = json.loads(
        (ROOT / "data/research/formal_backtests/cn_x1_1.json").read_text(
            encoding="utf-8"
        )
    )
    package["evidence_cutoff"] = "2026-08-07"
    module._validate_cn_formal_extension(package, config)


def test_cn_registry_rejects_frozen_evidence_truncation() -> None:
    module = _load_validator()
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_1.yaml").read_text())
    package = json.loads(
        (ROOT / "data/research/formal_backtests/cn_x1_1.json").read_text(
            encoding="utf-8"
        )
    )
    package["report"] = package["report"][:-1]
    with pytest.raises(ValueError, match="frozen report prefix"):
        module._validate_cn_formal_extension(package, config)
