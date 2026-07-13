from __future__ import annotations

import pandas as pd
import pytest

from src.research.window_policy import (
    ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
    COMPLETE_WINDOWS_ONLY,
    build_window_sampling_plan,
    complete_boundary_windows,
    validate_partial_window_contract,
)


def _plan(
    *,
    policy: str,
    test_end: str = "2026-06-18",
    min_partial: int | None = None,
    available_start: str = "2024-01-01",
):
    return build_window_sampling_plan(
        pd.bdate_range(available_start, test_end),
        "2021-01-01",
        test_end,
        first_test_year=2024,
        last_test_year=2026,
        min_complete_windows=3,
        partial_window_policy=policy,
        min_partial_window_eligible_sessions=min_partial,
        horizon_sessions=10,
        cadence_sessions=10,
    )


def _row(plan, label: str) -> dict:
    return next(row for row in plan.window_rows if row["label"] == label)


def test_complete_windows_only_reproduces_issue_124_boundary() -> None:
    plan = _plan(policy=COMPLETE_WINDOWS_ONLY)

    assert plan.complete_minimum_satisfied is True
    assert plan.complete_window_count == 4
    assert plan.partial_window_count == 0
    assert [window.label for window in plan.selected_windows] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]
    partial = _row(plan, "2026H1")
    assert partial["status"] == "excluded"
    assert partial["boundary_status"] == "excluded_partial_by_policy"
    assert partial["natural_test_end"] == "2026-06-30"
    assert partial["requested_test_end"] == "2026-06-18"
    assert partial["effective_test_end"] == "2026-06-18"
    assert partial["counts_toward_min_windows"] is False
    future = _row(plan, "2026H2")
    assert future["boundary_status"] == "excluded_not_started"


def test_partial_final_window_is_optional_extra_not_minimum_credit() -> None:
    plan = _plan(
        policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial=20,
    )

    assert plan.complete_window_count == 4
    assert plan.partial_window_count == 1
    assert plan.complete_minimum_satisfied is True
    assert [window.label for window in plan.selected_windows][-1] == "2026H1"
    partial = _row(plan, "2026H1")
    assert partial["status"] == "included"
    assert partial["complete"] is False
    assert partial["counts_toward_min_windows"] is False
    assert partial["effective_test_end"] == "2026-06-18"
    assert partial["horizon_eligible_sessions"] >= 20


def test_partial_final_window_below_session_minimum_is_audibly_excluded() -> None:
    plan = build_window_sampling_plan(
        pd.bdate_range("2024-01-01", "2026-01-30"),
        "2021-01-01",
        "2026-01-30",
        first_test_year=2024,
        last_test_year=2026,
        min_complete_windows=3,
        partial_window_policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial_window_eligible_sessions=20,
        horizon_sessions=10,
        cadence_sessions=10,
    )

    assert plan.complete_window_count == 4
    assert plan.partial_window_count == 0
    partial = _row(plan, "2026H1")
    assert partial["status"] == "excluded"
    assert partial["horizon_eligible_sessions"] < 20
    assert "requires at least 20" in partial["inclusion_reason"]


def test_all_sampled_forward_horizons_stay_within_effective_window() -> None:
    dates = pd.bdate_range("2024-01-01", "2026-06-18")
    positions = {pd.Timestamp(date): index for index, date in enumerate(dates)}
    plan = _plan(
        policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial=20,
    )
    included = {
        row["label"]: row for row in plan.window_rows if row["status"] == "included"
    }
    sampled = sorted(plan.date_map)

    for date in sampled:
        future = dates[positions[date] + 10]
        row = included[plan.date_map[date]]
        assert future <= pd.Timestamp(row["effective_test_end"])
        assert future <= pd.Timestamp(plan.requested_test_end)

    sampled_positions = [positions[date] for date in sampled]
    assert all(
        right - left >= 10
        for left, right in zip(sampled_positions, sampled_positions[1:])
    )


def test_minimum_counts_complete_windows_only() -> None:
    plan = build_window_sampling_plan(
        pd.bdate_range("2025-01-01", "2026-06-18"),
        "2024-10-01",
        "2026-06-18",
        first_test_year=2024,
        last_test_year=2026,
        min_complete_windows=4,
        partial_window_policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial_window_eligible_sessions=20,
        horizon_sessions=10,
        cadence_sessions=10,
    )

    assert plan.partial_window_count == 1
    assert plan.complete_window_count == 3
    assert plan.complete_minimum_satisfied is False


def test_boundary_readiness_remains_complete_only() -> None:
    windows = complete_boundary_windows(
        "2021-01-01",
        "2026-06-18",
        first_test_year=2024,
        last_test_year=2026,
    )
    assert [window.label for window in windows] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]


def test_partial_policy_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="partial_window_policy"):
        validate_partial_window_contract(
            policy="implicit",
            min_partial_window_eligible_sessions=None,
            cadence_sessions=10,
        )
    with pytest.raises(ValueError, match="must be omitted"):
        validate_partial_window_contract(
            policy=COMPLETE_WINDOWS_ONLY,
            min_partial_window_eligible_sessions=20,
            cadence_sessions=10,
        )
    with pytest.raises(ValueError, match="is required"):
        validate_partial_window_contract(
            policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
            min_partial_window_eligible_sessions=None,
            cadence_sessions=10,
        )
    with pytest.raises(ValueError, match="at least"):
        validate_partial_window_contract(
            policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
            min_partial_window_eligible_sessions=5,
            cadence_sessions=10,
        )
