from __future__ import annotations

import math
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "configs/research_paradigms/xgb_dual_market_improvement_v1.yaml"
IDENTITY_PATH = (
    REPO_ROOT / "configs/research_paradigms/xgb_dual_market_baseline_identity_v1.yaml"
)


def test_improvement_contract_points_to_resolved_identity() -> None:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert payload["status"] == "phase_1_baseline_identity_bound"
    assert payload["baseline_identity_path"].endswith(
        "xgb_dual_market_baseline_identity_v1.yaml"
    )
    assert (
        payload["reported_baselines"]["us"]["provenance_status"]
        == "unresolved_user_reported"
    )
    assert payload["reported_baselines"]["cn"]["provenance_status"] == "baseline_verified"
    assert math.isclose(
        payload["reported_baselines"]["us"]["verified_current_scope_value"],
        0.7372321884377135,
    )
    assert math.isclose(
        payload["reported_baselines"]["cn"]["verified_current_scope_value"],
        0.2018176732282666,
    )


def test_baseline_identity_binds_artifacts_metrics_and_formula() -> None:
    payload = yaml.safe_load(IDENTITY_PATH.read_text(encoding="utf-8"))
    source = payload["source_evidence"]["selected_pool_retest"]

    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert source["pull_request"] == 289
    assert source["workflow_run_id"] == 30707914152
    assert source["us_artifact"]["artifact_id"] == 8820927998
    assert source["cn_artifact"]["artifact_id"] == 8820979579

    for market in ("us", "cn"):
        baseline = payload["markets"][market]["verified_current_baseline"]
        recomputed = (
            (1.0 + baseline["compounded_strategy_return"])
            / (1.0 + baseline["compounded_benchmark_return"])
            - 1.0
        )
        assert math.isclose(
            recomputed,
            baseline["compounded_relative_excess_return"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        assert baseline["promotion_status"] == "rejected"
        assert baseline["trade_ready"] is False

    us = payload["markets"]["us"]
    cn = payload["markets"]["cn"]
    assert us["user_reported_claim"]["exact_artifact_found"] is False
    assert us["user_reported_claim"]["may_be_used_as_optimization_target"] is False
    assert cn["user_reported_claim"]["exact_artifact_found"] is True
    assert cn["user_reported_claim"]["provenance_status"] == "baseline_verified"
    assert math.isclose(
        cn["user_reported_claim"]["absolute_difference_from_verified"],
        abs(0.2018176732282666 - 0.2018),
        rel_tol=0.0,
        abs_tol=1e-15,
    )
