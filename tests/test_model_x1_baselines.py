from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_model_x1_baselines.py"
REGISTRY = ROOT / "configs/models/model_registry_v1.yaml"
BYD_V12 = "byd_v1_2_convex_momentum_budget_v1"
BYD_V13 = "byd_v1_3_recovery_event_low_vol_confirmation_v1"


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
    assert payload["active_baselines"]["us"] == "us_x1_2"
    assert payload["active_baselines"]["cn"] == "cn_x1_1"
    assert payload["active_baselines"]["byd"] == BYD_V13

    assert payload["models"]["us_x1_0"]["superseded_by"] == "us_x1_1"
    us_x1_1 = payload["models"]["us_x1_1"]
    assert us_x1_1["status"] == "historical_baseline_superseded"
    assert us_x1_1["superseded_by"] == "us_x1_2"

    us_x1_2 = payload["models"]["us_x1_2"]
    assert us_x1_2["display_name"] == "US x1.2"
    assert us_x1_2["status"] == "baseline_research_active"
    assert us_x1_2["source_candidate"] == "r11_sampled"
    assert us_x1_2["promotion_authority"] == "explicit_user_direction_2026_08_11"
    assert us_x1_2["prospective_acceptance_pending"] is True
    assert us_x1_2["trade_ready"] is False

    assert payload["models"]["cn_x1_0"]["superseded_by"] == "cn_x1_1"
    assert payload["models"]["cn_x1_1"]["status"] == "accepted_formal_baseline"

    byd_v12 = payload["models"][BYD_V12]
    assert byd_v12["status"] == "historical_baseline_superseded"
    assert byd_v12["superseded_by"] == BYD_V13
    byd_v13 = payload["models"][BYD_V13]
    assert byd_v13["status"] == "accepted_formal_baseline"
    assert byd_v13["promotion_authority"] == "explicit_user_direction_2026_08_10"
    assert byd_v13["trade_ready"] is False

    assert payload["versioning_policy"]["immutable_released_versions"] is True
    assert payload["versioning_policy"]["final_holdout_reuse_for_selection_allowed"] is False


def test_model_configs_notebooks_and_frozen_specs_tie() -> None:
    module = _load_validator()
    result = module.validate_registry(ROOT)
    assert result["status"] == "baseline_model_registry_valid"
    assert result["active_baselines"] == {
        "us": "us_x1_2",
        "cn": "cn_x1_1",
        "byd": BYD_V13,
    }
    assert [item["model_id"] for item in result["models"]] == [
        "cn_x1_0",
        "cn_x1_1",
        "us_x1_0",
        "us_x1_1",
        "us_x1_2",
    ]
    cn_x1_1 = next(item for item in result["models"] if item["model_id"] == "cn_x1_1")
    assert cn_x1_1["evidence_completeness"] == "complete"
    us_x1_2 = next(item for item in result["models"] if item["model_id"] == "us_x1_2")
    assert us_x1_2["selected_candidate"] == "r11_sampled"
    assert us_x1_2["prospective_acceptance_pending"] is True
    assert result["additional_registered_models"] == [
        "byd_dividend_sleeve_v1_0",
        BYD_V12,
        BYD_V13,
    ]
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
