from __future__ import annotations

import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs/models/model_registry_v1.yaml"
MODEL = ROOT / "configs/models/us_x1_1.yaml"
SPEC = ROOT / "configs/research_paradigms/us_x1_1_frozen_v1.yaml"
EXPERIMENT = ROOT / "configs/research_experiments/us_x1_1_risk_control_v1.yaml"


def _load(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def test_us_x1_1_is_the_active_research_baseline() -> None:
    registry = _load(REGISTRY)
    model = _load(MODEL)
    assert registry["active_baselines"]["us"] == "us_x1_1"
    assert registry["models"]["us_x1_0"]["superseded_by"] == "us_x1_1"
    assert registry["models"]["us_x1_1"]["status"] == (
        "baseline_research_active"
    )
    assert model["model_id"] == "us_x1_1"
    assert model["lineage"]["parent"] == "us_x1_0"
    assert model["lineage"]["adopted_from_candidate"] == (
        "us_x1_1_candidate_a"
    )
    assert model["baseline_decision"]["decision"] == (
        "promote_candidate_a_to_formal_research_baseline"
    )
    assert model["research_only"] is True
    assert model["trade_ready"] is False


def test_us_x1_1_model_and_frozen_spec_match() -> None:
    model = _load(MODEL)
    spec = _load(SPEC)
    calibration = spec["candidate_grid"]["ranker"]["calibrations"]
    assert spec["experiment_id"] == "us_x1_1_frozen_v1"
    assert spec["factor_library"]["groups"] == [
        "momentum_volatility_volume"
    ]
    assert len(calibration) == 1
    assert calibration[0]["n_gain_bins"] == 7
    assert calibration[0]["num_boost_round"] == 200
    assert model["features"]["group"] == "momentum_volatility_volume"
    assert model["model"]["learning_rate"] == 0.05
    assert model["model"]["max_leaves"] == 31
    assert model["provider_binding"][
        "canonical_evidence_provider_identity_sha256"
    ] == "2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95"


def test_us_x1_1_development_economics_tie() -> None:
    model = _load(MODEL)
    development = model["backtest_evidence"]["development"]
    windows = development["windows"]
    strategy = _compound([float(row["total_return"]) for row in windows])
    benchmark = _compound([float(row["benchmark_return"]) for row in windows])
    relative = (1.0 + strategy) / (1.0 + benchmark) - 1.0
    assert math.isclose(
        strategy,
        float(development["compounded_strategy_return"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        benchmark,
        float(development["compounded_benchmark_return"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        relative,
        float(development["compounded_relative_excess_return"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert development["positive_excess_windows"] == "4/4"
    assert development["all_window_recurring_names"] == ["AAOI", "AEHR", "BE"]


def test_next_experiment_starts_from_us_x1_1() -> None:
    experiment = _load(EXPERIMENT)
    assert experiment["parent_model_id"] == "us_x1_1"
    assert experiment["fixed_model"]["model_id"] == "us_x1_1"
    assert experiment["fixed_model"]["features_may_change"] is False
    assert experiment["fixed_model"]["model_parameters_may_change"] is False
    assert experiment["windows"]["reporting_only_consumed"] == ["2026H1"]
    assert experiment["windows"]["reporting_only_may_enter_decision"] is False
    assert [row["variant_id"] for row in experiment["variants"]] == [
        "top20_equal_weight",
        "top15_inverse_vol20_capped",
        "top15_equal_weight_name_cap",
        "top15_sector_cap",
        "top15_qqq_trend_overlay",
    ]
    assert experiment["version_policy"]["may_propose_us_x1_2_candidate"] is True
    assert experiment["version_policy"]["automatic_model_update"] is False
