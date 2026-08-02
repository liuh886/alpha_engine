from __future__ import annotations

import math
from pathlib import Path

import yaml

from scripts.run_us_x1_1_native_xgb_grid import (
    BASELINE_ID,
    DECISION_WINDOWS,
    _aggregate_candidate,
    _decision,
    _native_calibrations,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/research_experiments/us_x1_1_native_xgb_calibration_v1.yaml"


def _load_config() -> dict:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _result(
    *,
    total_return: float,
    benchmark_return: float,
    max_drawdown: float,
    icir: float = 0.2,
    rank_ic: float = 0.04,
    spread: float = 0.02,
) -> dict:
    return {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "excess_return": total_return - benchmark_return,
        "max_drawdown": max_drawdown,
        "icir": icir,
        "rank_ic": rank_ic,
        "score_direction": {"top_minus_bottom_spread": spread},
        "top_selected_stocks": ["A", "B", "C"],
    }


def _window_rows(
    *,
    strategy_returns: list[float],
    benchmark_returns: list[float],
    max_drawdown: float,
) -> list[dict]:
    rows: list[dict] = []
    for window, strategy, benchmark in zip(
        DECISION_WINDOWS,
        strategy_returns,
        benchmark_returns,
        strict=True,
    ):
        base = _result(
            total_return=strategy,
            benchmark_return=benchmark,
            max_drawdown=max_drawdown,
        )
        rows.append(
            {
                "window": window,
                "score_rank_correlation_vs_baseline": 0.95,
                "final_top15_overlap_vs_baseline": 0.8,
                "cost_stress": {
                    "20": base,
                    "40": {**base, "total_return": strategy - 0.01},
                    "60": {**base, "total_return": strategy - 0.02},
                },
            }
        )
    return rows


def test_native_grid_is_exactly_pre_registered() -> None:
    calibrations = _native_calibrations(_load_config())
    assert [item[0] for item in calibrations] == [
        "x1_1_effective_baseline",
        "lower_learning_rate_more_rounds",
        "higher_child_weight",
        "row_and_column_sampling",
        "regularized",
        "lower_leaf_capacity",
    ]
    manifests = [item[1].identity_manifest() for item in calibrations]
    assert len({item["identity_sha256"] for item in manifests}) == 6
    assert all(
        item["identity_tie"] == "declared_native_fields_equal_effective_runtime"
        for item in manifests
    )


def test_aggregate_candidate_compounds_cost_stress_and_concentration() -> None:
    rows = _window_rows(
        strategy_returns=[0.20, 0.30, 0.10, 0.40],
        benchmark_returns=[0.10, 0.05, 0.05, 0.10],
        max_drawdown=-0.18,
    )
    aggregate = _aggregate_candidate(
        "candidate",
        "xgb:daily_ranker:candidate",
        {"identity_sha256": "abc"},
        rows,
    )
    strategy = math.prod([1.20, 1.30, 1.10, 1.40]) - 1.0
    benchmark = math.prod([1.10, 1.05, 1.05, 1.10]) - 1.0
    relative = (1.0 + strategy) / (1.0 + benchmark) - 1.0
    assert math.isclose(
        aggregate["cost_stress"]["20"]["compounded_relative_excess_return"],
        relative,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert aggregate["positive_excess_windows"] == 4
    assert aggregate["worst_drawdown"] == -0.18
    assert aggregate["all_window_recurring_names"] == ["A", "B", "C"]


def test_provider_mismatch_forces_data_blocked() -> None:
    baseline = _aggregate_candidate(
        BASELINE_ID,
        "baseline",
        {"identity_sha256": "base"},
        _window_rows(
            strategy_returns=[0.20, 0.30, 0.10, 0.40],
            benchmark_returns=[0.10, 0.05, 0.05, 0.10],
            max_drawdown=-0.27,
        ),
    )
    candidate = _aggregate_candidate(
        "regularized",
        "candidate",
        {"identity_sha256": "candidate"},
        _window_rows(
            strategy_returns=[0.21, 0.31, 0.12, 0.39],
            benchmark_returns=[0.10, 0.05, 0.05, 0.10],
            max_drawdown=-0.20,
        ),
    )
    decision = _decision(
        [baseline, candidate],
        provider_matches_baseline=False,
        deterministic_baseline=True,
    )
    assert decision["decision"] == "data_blocked"
    assert decision["selected_calibration_id"] is None
    assert decision["automatic_model_update"] is False


def test_supported_candidate_can_only_become_reviewed_x1_2_candidate() -> None:
    baseline = _aggregate_candidate(
        BASELINE_ID,
        "baseline",
        {"identity_sha256": "base"},
        _window_rows(
            strategy_returns=[0.20, 0.30, 0.10, 0.40],
            benchmark_returns=[0.10, 0.05, 0.05, 0.10],
            max_drawdown=-0.27,
        ),
    )
    candidate = _aggregate_candidate(
        "regularized",
        "candidate",
        {"identity_sha256": "candidate"},
        _window_rows(
            strategy_returns=[0.21, 0.31, 0.12, 0.39],
            benchmark_returns=[0.10, 0.05, 0.05, 0.10],
            max_drawdown=-0.20,
        ),
    )
    decision = _decision(
        [baseline, candidate],
        provider_matches_baseline=True,
        deterministic_baseline=True,
    )
    assert decision["decision"] == "native_xgb_x1_2_candidate_supported"
    assert decision["selected_calibration_id"] == "regularized"
    assert decision["may_create_reviewed_us_x1_2_candidate"] is True
    assert decision["automatic_model_update"] is False
    assert decision["new_untouched_challenge_required"] is True
