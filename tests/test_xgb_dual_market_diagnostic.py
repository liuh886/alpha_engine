from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/build_xgb_dual_market_diagnostic.py"
IDENTITY_PATH = (
    REPO_ROOT / "configs/research_paradigms/xgb_dual_market_baseline_identity_v1.yaml"
)
DIAGNOSTIC_PATH = (
    REPO_ROOT / "configs/research_paradigms/xgb_dual_market_diagnostic_v1.yaml"
)


def _load_module() -> ModuleType:
    module_name = "xgb_dual_market_diagnostic"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_diagnostic_classifies_market_specific_failure_modes() -> None:
    module = _load_module()
    identity = module.load_yaml(IDENTITY_PATH)
    diagnostic = module.load_yaml(DIAGNOSTIC_PATH)
    report = module.build_report(identity, diagnostic)

    assert report["status"] == "diagnosis_completed_no_variant_authorization"
    assert report["trade_ready"] is False

    us = report["markets"]["us"]
    assert us["classification"] == "tail_risk_and_concentration_first"
    assert us["strongest_window"]["window"] == "2025H2"
    assert us["worst_drawdown_window"]["window"] == "2025H1"
    assert us["positive_excess_signal_mismatch_count"] == 2
    assert math.isclose(
        us["strongest_window"]["share_of_positive_simple_excess"],
        0.579965941193305,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    cn = report["markets"]["cn"]
    assert cn["classification"] == "ranking_validity_and_exposure_first"
    assert cn["strongest_window"]["window"] == "2025H1"
    assert cn["weakest_window"]["window"] == "2025H2"
    assert cn["positive_excess_signal_mismatch_count"] == 2
    assert {
        mismatch["window"]
        for mismatch in cn["positive_excess_signal_mismatches"]
    } == {"2024H1", "2024H2"}


def test_diagnostic_writes_machine_and_human_readable_outputs(tmp_path: Path) -> None:
    module = _load_module()
    report = module.build_report(
        module.load_yaml(IDENTITY_PATH),
        module.load_yaml(DIAGNOSTIC_PATH),
    )

    json_path, markdown_path = module.write_report(report, tmp_path)

    assert json_path.is_file()
    assert markdown_path.is_file()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "tail_risk_and_concentration_first" in markdown
    assert "ranking_validity_and_exposure_first" in markdown
    assert "Neither path is authorized to consume the final challenge window." in markdown
