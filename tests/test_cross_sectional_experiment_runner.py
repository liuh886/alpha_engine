from __future__ import annotations

from pathlib import Path

from src.research.cross_sectional_experiment_runner import (
    _factor_expressions,
    load_cross_sectional_experiment_spec,
)


SPEC = Path("configs/research_experiments/us_x1_2_risk_controlled_momentum_v1.yaml")


def test_us_x1_2_mission_is_atomic_and_provider_bound() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)

    assert spec.market == "us"
    assert spec.benchmark == "QQQ"
    assert spec.contract.selection_windows == (
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    )
    assert spec.contract.reporting_windows == ("2026H1",)
    assert spec.contract.provider_identity_sha256 == (
        "66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8"
    )
    assert [candidate.candidate_id for candidate in spec.candidates] == [
        "baseline_7factor",
        "risk_controlled_9factor",
    ]


def test_us_x1_2_challenger_adds_only_two_unique_risk_controlled_factors() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    expressions = _factor_expressions(spec)

    baseline = set(expressions["baseline_7factor"])
    challenger = set(expressions["risk_controlled_9factor"])

    assert len(baseline) == 7
    assert len(challenger) == 9
    assert baseline < challenger
    assert len(challenger - baseline) == 2


def test_us_x1_2_candidates_share_identical_xgb_runtime() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    manifests = [candidate.calibration.identity_manifest() for candidate in spec.candidates]

    assert manifests[0]["identity_sha256"] == manifests[1]["identity_sha256"]
    assert manifests[0]["effective_model_parameters"] == manifests[1][
        "effective_model_parameters"
    ]
