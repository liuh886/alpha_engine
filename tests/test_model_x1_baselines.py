from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_model_x1_baselines.py"
REGISTRY = ROOT / "configs/models/model_registry_v1.yaml"


def _load_validator() -> ModuleType:
    name = "validate_model_x1_baselines"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_contains_governed_x1_baselines() -> None:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert payload["trade_ready"] is False
    assert payload["active_baselines"]["us"] == "us_x1_1"
    assert payload["active_baselines"]["cn"] == "cn_x1_1"
    assert payload["active_baselines"]["byd"] == "byd_dividend_sleeve_v1_0"
    assert payload["models"]["us_x1_0"]["superseded_by"] == "us_x1_1"
    assert payload["models"]["cn_x1_0"]["superseded_by"] == "cn_x1_1"
    assert payload["models"]["cn_x1_1"]["display_name"] == "CN x1.1"
    assert payload["models"]["cn_x1_1"]["status"] == "accepted_formal_baseline"
    assert payload["models"]["cn_x1_1"]["trade_ready"] is False
    assert payload["versioning_policy"]["immutable_released_versions"] is True
    assert (
        payload["versioning_policy"]["final_holdout_reuse_for_selection_allowed"]
        is False
    )


def test_model_configs_notebooks_and_frozen_specs_tie() -> None:
    module = _load_validator()
    result = module.validate_registry(ROOT)
    assert result["status"] == "baseline_model_registry_valid"
    assert result["active_baselines"] == {
        "us": "us_x1_1",
        "cn": "cn_x1_1",
        "byd": "byd_dividend_sleeve_v1_0",
    }
    assert [item["model_id"] for item in result["models"]] == [
        "cn_x1_0",
        "cn_x1_1",
        "us_x1_0",
        "us_x1_1",
    ]
    cn_x1_1 = next(item for item in result["models"] if item["model_id"] == "cn_x1_1")
    assert cn_x1_1["evidence_completeness"] == "complete"
    assert result["additional_registered_models"] == [
        "byd_dividend_sleeve_v1_0"
    ]
    assert all(item["trade_ready"] is False for item in result["models"])
