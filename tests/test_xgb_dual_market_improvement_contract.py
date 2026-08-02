from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "configs/research_paradigms/xgb_dual_market_improvement_v1.yaml"
SCRIPT_PATH = REPO_ROOT / "scripts/audit_xgb_baseline_provenance.py"


def _load_auditor() -> ModuleType:
    module_name = "xgb_baseline_auditor"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_dual_market_contract_locks_reported_baselines_and_scopes() -> None:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert payload["issue"] == 338
    assert payload["trade_ready"] is False
    assert payload["objective"]["automatic_promotion_allowed"] is False
    assert payload["objective"]["markets_are_independent"] is True

    assert payload["reported_baselines"]["us"]["value"] == 0.8143
    assert payload["reported_baselines"]["us"]["benchmark"] == "QQQ"
    assert payload["reported_baselines"]["cn"]["value"] == 0.2018
    assert payload["reported_baselines"]["cn"]["benchmark"] == "CSI300"

    assert payload["markets"]["us"]["universe_id"] == "us_selected_equities_v2"
    assert payload["markets"]["us"]["exact_candidate_count"] == 87
    assert payload["markets"]["cn"]["universe_id"] == "cn_selected_equities_v3"
    assert payload["markets"]["cn"]["exact_candidate_count"] == 130
    assert payload["markets"]["us"]["reference_assets_may_enter_rank"] is False
    assert payload["markets"]["cn"]["reference_assets_may_enter_rank"] is False


def test_contract_caps_search_and_final_holdout_use() -> None:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    budget = payload["search_budget"]

    assert budget["baseline_replications_per_market"] == 1
    assert budget["maximum_development_variants_per_market"] == 12
    assert budget["maximum_frozen_candidates_per_market"] == 1
    assert budget["maximum_final_challenge_evaluations_per_market"] == 1

    final_stage = payload["stages"][-1]
    assert final_stage["id"] == "phase_4_single_final_challenge"
    assert final_stage["maximum_evaluations_per_frozen_candidate"] == 1


def test_provenance_auditor_finds_candidates_without_verifying_them(tmp_path: Path) -> None:
    module = _load_auditor()
    evidence = tmp_path / "docs/research/historical_result.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        "US XGBoost relative excess 81.43%\nCN XGBoost relative excess 20.18%\n",
        encoding="utf-8",
    )

    report = module.build_report(tmp_path)

    assert report["status"] == "baseline_provenance_audit_completed"
    assert report["markets"]["us"]["status"] == "meaningful_candidates_found"
    assert report["markets"]["cn"]["status"] == "meaningful_candidates_found"
    assert report["markets"]["us"]["classification_counts"] == {
        "economic_metric_candidate": 2
    }
    assert report["markets"]["cn"]["classification_counts"] == {
        "economic_metric_candidate": 2
    }
    assert "only a provenance candidate" in report["interpretation"]
