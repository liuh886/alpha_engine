from __future__ import annotations

import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "configs/models/candidates/us_x1_1_candidate_a.yaml"
ACTIVE_MODEL = ROOT / "configs/models/us_x1_1.yaml"
ACTIVE_EXPERIMENT = ROOT / "configs/research_experiments/us_x1_1_risk_control_v1.yaml"


def _load(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def _relative(strategy: float, benchmark: float) -> float:
    return (1.0 + strategy) / (1.0 + benchmark) - 1.0


def test_candidate_identity_runtime_and_promotion_are_explicit() -> None:
    candidate = _load(CANDIDATE)
    model = _load(ACTIVE_MODEL)
    assert candidate["candidate_id"] == "us_x1_1_candidate_a"
    assert candidate["parent_model_id"] == "us_x1_0"
    assert candidate["promoted_model_id"] == "us_x1_1"
    assert candidate["status"] == "promoted_candidate"
    assert candidate["release_status"] == "promoted_as_us_x1_1"
    assert candidate["promotion_record"]["promotion_pr"] == 365
    assert candidate["promotion_record"]["promoted_config"] == (
        "configs/models/us_x1_1.yaml"
    )
    assert candidate["research_only"] is True
    assert candidate["trade_ready"] is False
    assert model["model_id"] == candidate["promoted_model_id"]
    assert candidate["latest_snapshot_binding"]["provider_identity_sha256"] == (
        "2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95"
    )
    assert candidate["legacy_candidate_identity"]["legacy_learning_rate_field"] == 0.03
    assert candidate["model_effective_runtime"]["learning_rate"] == 0.05
    assert candidate["model_effective_runtime"]["max_leaves"] == 31
    assert candidate["model_effective_runtime"]["num_boost_round"] == 200


def test_development_relative_excess_ties_exactly() -> None:
    candidate = _load(CANDIDATE)
    development = candidate["backtest_evidence"]["development"]
    windows = development["windows"]
    strategy = _compound([float(row["total_return"]) for row in windows])
    benchmark = _compound([float(row["benchmark_return"]) for row in windows])
    observed = _relative(strategy, benchmark)
    assert math.isclose(
        observed,
        float(development["compounded_relative_excess_return"]),
        rel_tol=0.0,
        abs_tol=2e-6,
    )
    assert development["positive_excess_windows"] == 4
    assert development["total_windows"] == 4
    assert development["all_window_recurring_names"] == ["AAOI", "AEHR", "BE"]
    assert float(development["strongest_positive_window_share"]) < 0.55
    assert float(development["worst_drawdown"]) < -0.22


def test_candidate_improved_x1_0_and_is_now_historical_source_evidence() -> None:
    candidate = _load(CANDIDATE)
    comparison = candidate["comparison_to_latest_us_x1_0_revision"]
    assert comparison["candidate_a_relative_excess"] > comparison["us_x1_0_relative_excess"]
    assert comparison["candidate_a_worst_drawdown"] > comparison["us_x1_0_worst_drawdown"]
    assert comparison["candidate_a_strongest_window_share"] < comparison["us_x1_0_strongest_window_share"]
    assert comparison["candidate_a_all_window_recurring_name_count"] < comparison["us_x1_0_all_window_recurring_name_count"]
    historical = candidate["historical_candidate_experiment"]
    assert historical["status"] == "superseded_by_formal_baseline_contract"
    assert historical["superseded_by"] == (
        "configs/research_experiments/us_x1_1_risk_control_v1.yaml"
    )
    assert candidate["continuing_research"]["next_candidate_version"] == "US x1.2"
    assert candidate["continuing_research"]["automatic_version_promotion"] is False


def test_active_risk_control_experiment_is_fixed_and_bounded() -> None:
    candidate = _load(CANDIDATE)
    experiment = _load(ACTIVE_EXPERIMENT)
    assert experiment["parent_model_id"] == candidate["promoted_model_id"]
    assert experiment["snapshot"]["provider_identity_sha256"] == candidate[
        "latest_snapshot_binding"
    ]["provider_identity_sha256"]
    fixed = experiment["fixed_model"]
    assert fixed["model_id"] == "us_x1_1"
    assert fixed["features_may_change"] is False
    assert fixed["label_may_change"] is False
    assert fixed["model_parameters_may_change"] is False
    assert fixed["pool_membership_may_change"] is False
    assert experiment["windows"]["development"] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]
    assert experiment["windows"]["reporting_only_consumed"] == ["2026H1"]
    assert experiment["windows"]["reporting_only_may_enter_decision"] is False
    assert [row["variant_id"] for row in experiment["variants"]] == [
        "top20_equal_weight",
        "top15_inverse_vol20_capped",
        "top15_equal_weight_name_cap",
        "top15_sector_cap",
        "top15_qqq_trend_overlay",
    ]
    assert experiment["execution"]["cost_stress_bps"] == [20, 40, 60]
    assert experiment["version_policy"]["automatic_model_update"] is False
    assert experiment["version_policy"]["may_propose_us_x1_2_candidate"] is True
