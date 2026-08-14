from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_cn_x1_2_governance_exception.py"
SOURCE = ROOT / "data/research/experiment_receipts/cn_x1_2_alpha158_breadth_scaled_v1.json"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("promote_cn_x1_2_governance_exception", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_retains_failed_gate_and_research_boundary() -> None:
    module = _load_script()
    experiment = json.loads(SOURCE.read_text(encoding="utf-8"))
    promotion = module.build_promotion_receipt(SOURCE)
    assert experiment["decision"].endswith("_rejected")
    assert experiment["development_boundary"]["supported"] is False
    assert promotion["decision"] == "promoted_by_explicit_user_governance_exception"
    assert promotion["preregistered_gate_result"] == {
        "passed": 21,
        "total": 22,
        "supported": False,
        "failed_gates": ["2026h1_drawdown_worsening_within_3pp"],
        "incumbent_2026h1_max_drawdown": -0.07926435673670995,
        "candidate_2026h1_max_drawdown": -0.127254261403144,
        "drawdown_delta_percentage_points": -4.798990466643405,
        "maximum_allowed_worsening_percentage_points": 3.0,
    }
    assert promotion["research_only"] is True
    assert promotion["trade_ready"] is False
    assert promotion["no_2026h2_evidence_consumed"] is True


def test_promotion_fails_closed_if_rejection_is_rewritten(tmp_path: Path) -> None:
    module = _load_script()
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload["development_boundary"]["supported"] = True
    source = tmp_path / "rewritten.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must remain unsupported"):
        module.build_promotion_receipt(source)


def test_promotion_fails_closed_if_failed_gate_is_hidden(tmp_path: Path) -> None:
    module = _load_script()
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rewritten = copy.deepcopy(payload)
    rewritten["development_boundary"]["checks"]["2026h1_drawdown_worsening_within_3pp"] = True
    source = tmp_path / "rewritten.json"
    source.write_text(json.dumps(rewritten), encoding="utf-8")
    with pytest.raises(ValueError, match="failed-gate identity drifted"):
        module.build_promotion_receipt(source)
