from __future__ import annotations

import json
from pathlib import Path

from src.common.runtime_settings import PROJECT_ROOT
from src.research.us_issue966_minimal_set import select_minimal_feature_set

SPEC = PROJECT_ROOT / "configs/research_experiments/us_issue966_phase6_minimal_set_v1.yaml"
PROVIDER = "c78ade39f63823d2f7089947831387803caae51b53073ae25fed2000f2a6f36c"
WINDOWS = ["2024H1", "2024H2", "2025H1", "2025H2"]
CANDIDATES = [
    "baseline_us_x1_2",
    "us_x1_2_plus_signed_cord",
    "us_x1_2_plus_signed_rank",
    "us_x1_2_plus_cord_rank",
    "us_x1_2_plus_all_three",
]


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _candidate(candidate_id: str, rel20: float, rel60: float, dd: float, rank_ic: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "compounded_relative_excess": rel20,
        "stress_compounded_relative_excess": rel60,
        "worst_drawdown": dd,
        "mean_rank_ic": rank_ic,
    }


def _stage_b() -> dict:
    return {
        "schema_version": "1.1",
        "experiment_id": "us_issue966_phase6_minimal_set_v1",
        "provider_identity_sha256": PROVIDER,
        "observed_provider_identity_sha256": PROVIDER,
        "selection_windows": WINDOWS,
        "status": "completed",
        "runner": "exact_us_ranker_portfolio_v1",
        "candidates": [
            _candidate("baseline_us_x1_2", 1.50, 1.30, -0.25, 0.05),
            _candidate("us_x1_2_plus_signed_cord", 1.90, 1.70, -0.24, 0.055),
            _candidate("us_x1_2_plus_signed_rank", 1.70, 1.45, -0.26, 0.052),
            _candidate("us_x1_2_plus_cord_rank", 1.80, 1.55, -0.27, 0.053),
            _candidate("us_x1_2_plus_all_three", 2.10, 1.90, -0.23, 0.057),
        ],
        "candidate_metadata": {
            "baseline_us_x1_2": {"factor_count": 7},
            "us_x1_2_plus_signed_cord": {"factor_count": 9},
            "us_x1_2_plus_signed_rank": {"factor_count": 9},
            "us_x1_2_plus_cord_rank": {"factor_count": 9},
            "us_x1_2_plus_all_three": {"factor_count": 10},
        },
    }


def _observations(*, make_signed_cord_negative: bool = False) -> list[dict]:
    rows = []
    for candidate_id in CANDIDATES:
        for window in WINDOWS:
            for cost in (20, 60):
                value = 0.05
                if candidate_id == "baseline_us_x1_2":
                    value = 0.03
                if make_signed_cord_negative and candidate_id == "us_x1_2_plus_signed_cord" and window == "2025H2" and cost == 20:
                    value = -0.01
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "window": window,
                        "cost_bps": cost,
                        "relative_excess": value,
                    }
                )
    return rows


def _redundancy() -> dict:
    return {
        "experiment_id": "us_issue966_phase6_minimal_set_v1",
        "provider_identity_sha256": PROVIDER,
        "selection_windows": WINDOWS,
        "candidate_added_factor_ids": {
            "baseline_us_x1_2": [],
            "us_x1_2_plus_signed_cord": [
                "volume_stat_research.signed_volume_balance_10d",
                "qlib_alpha158.cord10",
            ],
            "us_x1_2_plus_signed_rank": [
                "volume_stat_research.signed_volume_balance_10d",
                "qlib_alpha158.rank20",
            ],
            "us_x1_2_plus_cord_rank": ["qlib_alpha158.cord10", "qlib_alpha158.rank20"],
            "us_x1_2_plus_all_three": [
                "volume_stat_research.signed_volume_balance_10d",
                "qlib_alpha158.cord10",
                "qlib_alpha158.rank20",
            ],
        },
        "factors": {
            "volume_stat_research.signed_volume_balance_10d": {
                "max_abs_mean_daily_rank_correlation": 0.69
            },
            "qlib_alpha158.cord10": {"max_abs_mean_daily_rank_correlation": 0.55},
            "qlib_alpha158.rank20": {"max_abs_mean_daily_rank_correlation": 0.76},
        },
    }


def test_phase6_selects_smallest_passing_subset_before_stronger_three_factor_set(tmp_path: Path) -> None:
    decision = select_minimal_feature_set(
        SPEC,
        _write(tmp_path / "stage.json", _stage_b()),
        _write(tmp_path / "observations.json", _observations()),
        _write(tmp_path / "redundancy.json", _redundancy()),
    )

    assert decision["selected_candidate_id"] == "us_x1_2_plus_signed_cord"
    assert decision["selected_factor_count"] == 9
    assert decision["candidate_decisions"]["us_x1_2_plus_all_three"]["pass"] is True
    assert decision["passing_candidate_ids"][0] == "us_x1_2_plus_signed_cord"
    assert decision["fresh_untouched_us_holdout_available"] is False
    assert decision["trade_ready"] is False


def test_phase6_requires_actual_positive_window_not_generic_harness_boolean(tmp_path: Path) -> None:
    decision = select_minimal_feature_set(
        SPEC,
        _write(tmp_path / "stage.json", _stage_b()),
        _write(tmp_path / "observations.json", _observations(make_signed_cord_negative=True)),
        _write(tmp_path / "redundancy.json", _redundancy()),
    )

    signed_cord = decision["candidate_decisions"]["us_x1_2_plus_signed_cord"]
    assert signed_cord["checks"]["all_development_windows_positive_excess"] is False
    assert signed_cord["pass"] is False
    assert decision["selected_candidate_id"] == "us_x1_2_plus_cord_rank"


def test_phase6_rejects_component_above_preregistered_redundancy_limit(tmp_path: Path) -> None:
    redundancy = _redundancy()
    redundancy["factors"]["volume_stat_research.signed_volume_balance_10d"][
        "max_abs_mean_daily_rank_correlation"
    ] = 0.97

    decision = select_minimal_feature_set(
        SPEC,
        _write(tmp_path / "stage.json", _stage_b()),
        _write(tmp_path / "observations.json", _observations()),
        _write(tmp_path / "redundancy.json", redundancy),
    )

    assert decision["candidate_decisions"]["us_x1_2_plus_signed_cord"]["pass"] is False
    assert decision["candidate_decisions"]["us_x1_2_plus_signed_rank"]["pass"] is False
    assert decision["selected_candidate_id"] == "us_x1_2_plus_cord_rank"
