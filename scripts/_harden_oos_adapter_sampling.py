"""Bind adapter evaluation dates to the shared horizon-contained plan.

Deleted before merge.
"""

from __future__ import annotations

from pathlib import Path

WINDOW_POLICY = Path("src/research/window_policy.py")
CN_ADAPTER = Path("src/research/cn_qlib_execution_adapter.py")
US_ADAPTER = Path("src/research/us_qlib_execution_adapter.py")
WINDOW_TESTS = Path("tests/test_window_policy.py")
QLIB_TESTS = Path("tests/test_cn_qlib_ci_integration.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_window_policy() -> None:
    text = WINDOW_POLICY.read_text(encoding="utf-8")
    if "def horizon_eligible_dates_by_window(" not in text:
        addition = '''

def horizon_eligible_dates_by_window(
    plan: WindowSamplingPlan,
    available_dates: pd.DatetimeIndex,
) -> dict[str, pd.DatetimeIndex]:
    """Return daily evaluation dates for every included window.

    Adapters must pass these daily horizon-eligible dates to the fixed-cadence
    evaluator. Passing the already sampled dates would apply ``::cadence`` a
    second time and silently change a 10-session strategy into a much slower
    strategy.

    The helper recomputes dates from the immutable plan evidence and verifies
    that applying the declared cadence reproduces the plan's sampled dates
    exactly. Any divergence fails closed.
    """

    dates_index = _normalized_dates(available_dates)
    dates_index = dates_index[
        dates_index <= pd.Timestamp(plan.requested_test_end)
    ]
    planned_sampled: dict[str, tuple[pd.Timestamp, ...]] = {}
    for date, label in plan.sampled_date_labels:
        planned_sampled.setdefault(label, tuple())
        planned_sampled[label] = (
            *planned_sampled[label],
            pd.Timestamp(date),
        )

    result: dict[str, pd.DatetimeIndex] = {}
    for row in plan.window_rows:
        if row.get("status") != "included":
            continue
        label = str(row["label"])
        effective_end = row.get("effective_test_end")
        if effective_end is None:
            raise ValueError(f"included window {label} has no effective_test_end")
        start = pd.Timestamp(str(row["test_start"]))
        end = pd.Timestamp(str(effective_end))
        window_dates = dates_index[
            (dates_index >= start) & (dates_index <= end)
        ]
        eligible = (
            window_dates[: -plan.horizon_sessions]
            if len(window_dates) > plan.horizon_sessions
            else window_dates[:0]
        )
        if len(eligible) != int(row["horizon_eligible_sessions"]):
            raise ValueError(
                f"window {label} horizon-eligible date count diverged from plan"
            )
        sampled = tuple(
            pd.Timestamp(value)
            for value in eligible[:: plan.cadence_sessions]
        )
        if sampled != planned_sampled.get(label, tuple()):
            raise ValueError(
                f"window {label} sampled dates diverged from shared plan"
            )
        if eligible.empty:
            raise ValueError(f"included window {label} has no evaluation dates")
        result[label] = eligible

    if set(result) != {window.label for window in plan.selected_windows}:
        raise ValueError("selected windows and horizon-eligible dates diverged")
    return result
'''
        text = text.rstrip() + addition + "\n"
    WINDOW_POLICY.write_text(text, encoding="utf-8")


def patch_adapter(path: Path, market: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from src.research.window_policy import build_window_sampling_plan\n",
        """from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
""",
        f"{market} window-policy import",
    )
    text = replace_once(
        text,
        """    windows = list(window_plan.selected_windows)
    window_payload = {
""",
        """    windows = list(window_plan.selected_windows)
    evaluation_dates_by_window = horizon_eligible_dates_by_window(
        window_plan, calendar
    )
    window_payload = {
""",
        f"{market} evaluation-date map",
    )
    text = replace_once(
        text,
        """    for window in windows:
        config = SpecBoundEvaluationContext(
""",
        """    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        evaluation_start = evaluation_dates.min().strftime("%Y-%m-%d")
        evaluation_end = evaluation_dates.max().strftime("%Y-%m-%d")
        config = SpecBoundEvaluationContext(
""",
        f"{market} per-window evaluation dates",
    )
    text = replace_once(
        text,
        """            test_start=window.test_start,
            test_end=window.test_end,
""",
        """            test_start=evaluation_start,
            test_end=evaluation_end,
""",
        f"{market} effective evaluation bounds",
    )
    text = replace_once(
        text,
        """        test_mask = (dates >= pd.Timestamp(window.test_start)) & (
            dates <= pd.Timestamp(window.test_end)
        )
""",
        """        test_mask = dates.isin(evaluation_dates)
""",
        f"{market} horizon-eligible test mask",
    )
    text = replace_once(
        text,
        """            baseline = normalize_qlib_frame_index(baseline)
            baseline.columns = ["score"]
""",
        """            baseline = normalize_qlib_frame_index(baseline)
            baseline_dates = baseline.index.get_level_values("datetime")
            baseline = baseline.loc[baseline_dates.isin(evaluation_dates)].copy()
            baseline.columns = ["score"]
""",
        f"{market} baseline date filter",
    )
    text = replace_once(
        text,
        """    runtime_metadata["survived_windows"] = survived_windows
""",
        """    runtime_metadata["evaluation_dates_by_window"] = {
        label: [date.strftime("%Y-%m-%d") for date in dates]
        for label, dates in evaluation_dates_by_window.items()
    }
    runtime_metadata["survived_windows"] = survived_windows
""",
        f"{market} evaluation-date evidence",
    )
    path.write_text(text, encoding="utf-8")


def patch_window_tests() -> None:
    text = WINDOW_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """    build_window_sampling_plan,
    complete_boundary_windows,
""",
        """    build_window_sampling_plan,
    complete_boundary_windows,
    horizon_eligible_dates_by_window,
""",
        "window helper test import",
    )
    if "test_adapter_evaluation_dates_reproduce_plan_sampling" not in text:
        addition = '''

def test_adapter_evaluation_dates_reproduce_plan_sampling() -> None:
    dates = pd.bdate_range("2024-01-01", "2026-06-18")
    plan = _plan(
        policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial=20,
    )
    evaluation = horizon_eligible_dates_by_window(plan, dates)

    assert set(evaluation) == {
        window.label for window in plan.selected_windows
    }
    for label, eligible in evaluation.items():
        assert len(eligible) == next(
            row["horizon_eligible_sessions"]
            for row in plan.window_rows
            if row["label"] == label
        )
        sampled = tuple(eligible[:: plan.cadence_sessions])
        expected = tuple(
            pd.Timestamp(date)
            for date, sampled_label in plan.sampled_date_labels
            if sampled_label == label
        )
        assert sampled == expected
        assert eligible[-1] <= pd.Timestamp(plan.requested_test_end)
'''
        text = text.rstrip() + addition + "\n"
    WINDOW_TESTS.write_text(text, encoding="utf-8")


def patch_qlib_integration_test() -> None:
    text = QLIB_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """    assert len(windows["windows"]) >= 3
    assert (run_dir / "walk_forward_stability.json").is_file()
""",
        """    included_windows = [
        row for row in windows["windows"] if row["status"] == "included"
    ]
    assert len(included_windows) >= 3
    assert windows["complete_minimum_satisfied"] is True
    assert windows["partial_windows_count_toward_min"] is False
    assert windows["sampled_rebalance_dates"] == sum(
        row["sampled_sessions"] for row in included_windows
    )
    for row in included_windows:
        artifact = run_dir / "windows" / (
            f"{spec.experiment_id}_{row['label']}.json"
        )
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        candidates = payload["comparison_report"]["candidates"]
        assert candidates
        assert all(
            int(candidate["n_periods"]) <= int(row["sampled_sessions"])
            for candidate in candidates
        )
        assert max(int(candidate["n_periods"]) for candidate in candidates) == int(
            row["sampled_sessions"]
        )
        assert payload["config"]["test_end"] <= row["effective_test_end"]
    assert (run_dir / "walk_forward_stability.json").is_file()
""",
        "real Qlib sampling assertions",
    )
    QLIB_TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_window_policy()
    patch_adapter(CN_ADAPTER, "CN")
    patch_adapter(US_ADAPTER, "US")
    patch_window_tests()
    patch_qlib_integration_test()


if __name__ == "__main__":
    main()
