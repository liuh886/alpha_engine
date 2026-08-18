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
    assert catalog.by_strategy_id["cn_x"].model_version_id == "cn_x1_2"
    assert catalog.by_strategy_id["us_x"].historical_evidence_access == "public"
    assert catalog.by_strategy_id["cn_x"].historical_evidence_access == "public"


def test_active_model_configs_and_formal_evidence_tie_to_catalog() -> None:
    module = _load_validator()
    result = module.validate_registry(ROOT)
    assert result["status"] == "active_x1_baselines_valid"
    assert result["active_strategy_catalog"] == "configs/strategies/registry.json"
    assert result["active_baselines"] == {
        "us": "us_x1_3",
        "cn": "cn_x1_2",
    }
    assert [item["model_id"] for item in result["models"]] == [
        "cn_x1_2",
        "us_x1_3",
    ]
    cn = result["models"][0]
    assert cn["promotion_authority"] == "explicit_user_direction_2026_08_14"
    assert cn["formal_acceptance_supported"] is False
    assert cn["failed_gate"] == "2026h1_drawdown_worsening_within_3pp"
    assert cn["formal_bundle_transition"] == "maintained_append_only_formal_refresh"
    assert cn["evidence_completeness"] == "complete"
    us = result["models"][1]
    assert us["selected_candidate"] == "mvv_plus_pressure"
    assert us["factor_count"] == 13
    assert us["prospective_acceptance_pending"] is True
    assert all(item["trade_ready"] is False for item in result["models"])
