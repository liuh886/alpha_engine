from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
    assert "cn_x" not in catalog.by_strategy_id
    assert catalog.by_strategy_id["us_x"].historical_evidence_access == "public"


def test_active_model_configs_and_formal_evidence_tie_to_catalog() -> None:
    module = _load_validator()
    result = module.validate_registry(ROOT)
    assert result["status"] == "active_x1_baselines_valid"
    assert result["active_strategy_catalog"] == "configs/strategies/registry.json"
    assert result["active_baselines"] == {
        "us": "us_x1_3",
    }
    assert [item["model_id"] for item in result["models"]] == [
        "us_x1_3",
    ]
    us = result["models"][0]
    assert us["selected_candidate"] == "mvv_plus_pressure"
    assert us["factor_count"] == 13
    assert us["prospective_acceptance_pending"] is True
    assert all(item["trade_ready"] is False for item in result["models"])
