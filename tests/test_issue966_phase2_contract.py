from __future__ import annotations

from pathlib import Path

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cn_x1_2_feature_ablation import (
    DEVELOPMENT_WINDOWS,
    EXPOSURE_POLICY,
    RULE,
    RUNNER_ID,
)
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec
from src.research.ranker_execution import candidate_factor_contracts

US_SPEC = PROJECT_ROOT / "configs/research_experiments/us_issue966_phase2_ablation_v1.yaml"
CN_SPEC = PROJECT_ROOT / "configs/research_experiments/cn_issue966_phase2_ablation_v1.yaml"


def _raw(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_us_phase2_matrix_is_exact_x1_2_feature_only_ablation() -> None:
    spec = load_cross_sectional_experiment_spec(US_SPEC)
    contracts = candidate_factor_contracts(spec)

    assert spec.contract.selection_windows == ("2024H1", "2024H2", "2025H1", "2025H2")
    assert spec.contract.reporting_windows == ()
    assert spec.contract.cutoff == "2026-06-30"
    assert len(contracts["baseline_us_x1_2"]["factor_ids"]) == 7
    assert len(contracts["us_x1_2_plus_signed_volume"]["factor_ids"]) == 8
    assert len(contracts["us_x1_2_plus_cord10"]["factor_ids"]) == 8
    assert len(contracts["us_x1_2_plus_rank20"]["factor_ids"]) == 8
    assert len(contracts["us_x1_2_plus_all_three"]["factor_ids"]) == 10

    raw = _raw(US_SPEC)
    for candidate in raw["candidates"]:
        calibration = candidate["xgb_native"]
        assert calibration["num_boost_round"] == 200
        assert calibration["learning_rate"] == 0.05
        assert calibration["subsample"] == 0.8
        assert calibration["colsample_bytree"] == 0.8
        assert calibration["seed"] == 42
    assert "2026H1" not in raw["windows"]["candidate_selection"]
    # Issue 966 execution triggers were retired (#989); the online-validation
    # hook must stay absent so the ablation cannot re-enter execution paths.
    assert "online_validation" not in raw


def test_cn_phase2_keeps_current_x1_2_signal_and_economic_contract() -> None:
    spec = load_cross_sectional_experiment_spec(CN_SPEC)
    contracts = candidate_factor_contracts(spec)
    raw = _raw(CN_SPEC)

    assert raw["phase2_runner"] == RUNNER_ID
    assert spec.contract.selection_windows == DEVELOPMENT_WINDOWS
    assert spec.contract.cutoff == "2026-06-30"
    assert raw["resolved_non_incremental_mechanisms"]["price_volume_correlation"] == {
        "status": "already_active_in_baseline",
        "factor_id": "qlib_alpha158.cord5",
        "action": "no_duplicate_ablation",
    }
    assert len(contracts["baseline_cn_x1_2"]["factor_ids"]) == 17
    assert "qlib_alpha158.cord5" in contracts["baseline_cn_x1_2"]["factor_ids"]
    assert len(contracts["cn_x1_2_plus_signed_volume"]["factor_ids"]) == 18
    assert len(contracts["cn_x1_2_plus_rank20"]["factor_ids"]) == 18
    assert len(contracts["cn_x1_2_plus_signed_volume_rank20"]["factor_ids"]) == 19

    for candidate in raw["candidates"]:
        assert candidate["regime_rule"] == RULE
        assert candidate["exposure_policy"] == EXPOSURE_POLICY
        calibration = candidate["xgb_native"]
        assert calibration["num_boost_round"] == 100
        assert calibration["learning_rate"] == 0.05
        assert calibration["subsample"] == 1.0
        assert calibration["colsample_bytree"] == 1.0
        assert calibration["seed"] == 42

    assert raw["execution"]["exact_portfolio"]["sectors"] == 4
    assert raw["execution"]["exact_portfolio"]["names_per_sector"] == 1
    assert raw["execution"]["exact_portfolio"]["execution_delay_sessions"] == 1
    assert raw["execution"]["cost_stress_bps"] == [20, 60]
    assert "2026H2" not in raw["windows"]["candidate_selection"]
