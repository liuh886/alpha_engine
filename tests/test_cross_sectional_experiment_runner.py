from __future__ import annotations

from pathlib import Path

import pytest

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.model_contract import resolve_canonical_factor_ids
from src.research.cn_ranker_exact_portfolio_replay import _candidate_factor_contracts
from src.research.cross_sectional_experiment_runner import (
    _factor_expressions,
    load_cross_sectional_experiment_spec,
)
from src.research.research_receipt import build_factor_lineage


SPEC = Path("configs/research_experiments/us_x1_2_risk_controlled_momentum_v1.yaml")
ALPHA158_SPEC = Path("tests/fixtures/research_experiments/alpha158_runner_v1.yaml")
CN_MIXED_SPEC = Path(
    "configs/research_experiments/cn_x1_2_alpha158_three_mechanism_v1.yaml"
)


def test_us_x1_2_mission_is_atomic_and_provider_bound() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)

    assert spec.market == "us"
    assert spec.benchmark == "QQQ"
    assert spec.raw["snapshot"]["policy"] == "exact_selected_pool_source_rebuild"
    assert spec.raw["snapshot"]["source_dir"] == "data/csv_source"
    assert spec.raw["source_repair"]["approval_manifest"] == (
        "data/source_repairs/us_x1_2_risk_controlled_momentum_v1.json"
    )
    assert spec.contract.selection_windows == (
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    )
    assert spec.contract.reporting_windows == ("2026H1",)
    assert spec.contract.provider_identity_sha256 == (
        "c2b8cc29ad70afde1b4590a03da6f82d4a9fd1e242426bc936333b7f7c3bd39d"
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


def test_alpha158_uses_the_same_cross_sectional_harness_without_formula_copying() -> None:
    spec = load_cross_sectional_experiment_spec(ALPHA158_SPEC)
    expressions = _factor_expressions(spec)
    lineage = build_factor_lineage(ALPHA158_SPEC)

    assert spec.factor_library_path.as_posix().endswith(
        "src/factors/sets/qlib_alpha158.py"
    )
    assert len(expressions["alpha158_baseline"]) == 158
    assert len(set(expressions["alpha158_baseline"])) == 158
    assert expressions["alpha158_baseline"] == expressions["alpha158_challenger"]
    assert lineage is not None
    assert lineage["catalog_id"] == "qlib_alpha158"
    assert lineage["candidates"]["alpha158_baseline"]["factor_count"] == 158
    assert len(lineage["candidates"]["alpha158_baseline"]["factor_ids"]) == 158


def test_cn_mixed_challenger_adds_exactly_three_canonical_alpha158_factors() -> None:
    spec = load_cross_sectional_experiment_spec(CN_MIXED_SPEC)
    contracts = _candidate_factor_contracts(spec)

    baseline = contracts["baseline_cn_x1_1"]
    challenger = contracts["cn_x1_2_alpha158_three_mechanism"]
    expected_additions = (
        "qlib_alpha158.cntd30",
        "qlib_alpha158.cord5",
        "qlib_alpha158.imin30",
    )

    assert len(baseline["factor_ids"]) == 14
    assert len(challenger["factor_ids"]) == 17
    assert challenger["factor_ids"][:14] == baseline["factor_ids"]
    assert challenger["factor_ids"][-3:] == expected_additions
    assert len(challenger["implementation_hashes"]) == 17
    assert all(challenger["implementation_hashes"].values())
    manifests = [candidate.calibration.identity_manifest() for candidate in spec.candidates]
    assert manifests[0]["identity_sha256"] == manifests[1]["identity_sha256"]


def test_mixed_canonical_resolver_rejects_duplicate_factor_ids() -> None:
    with pytest.raises(ValueError, match="factor_ids must not contain duplicates"):
        resolve_canonical_factor_ids(
            root=PROJECT_ROOT,
            library_sources=["src/factors/sets/qlib_alpha158.py"],
            factor_ids=["qlib_alpha158.cntd30", "qlib_alpha158.cntd30"],
        )
