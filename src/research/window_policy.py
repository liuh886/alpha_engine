"""Versioned OOS-window policy and session-aware sampling plans.

The planner separates two decisions that must not be conflated:

* ``min_windows`` is a hard minimum of complete half-year OOS windows;
* an eligible partial final window may be appended as extra evidence, but it
  never helps satisfy ``min_windows``.

All session-aware consumers use this module so readiness evidence, execution
windows, and factor-diagnostic sampling share one boundary and horizon policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.research.rolling_windows import RollingResearchWindow, half_year_rolling_windows

WINDOW_POLICY_SCHEMA_VERSION = "1.0"
COMPLETE_WINDOWS_ONLY = "complete_windows_only"
ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW = (
    "allow_horizon_contained_partial_final_window"
)
ALLOWED_PARTIAL_WINDOW_POLICIES = frozenset(
    {
        COMPLETE_WINDOWS_ONLY,
        ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
    }
)
MIN_WINDOWS_COUNT_POLICY = "complete_windows_only"


@dataclass(frozen=True)
class WindowBoundaryDecision:
    """One natural half-year boundary and its contract-level disposition."""

    label: str
    train_start: str
    train_end: str
    test_start: str
    natural_test_end: str
    requested_test_end: str
    effective_test_end: str | None
    complete: bool
    boundary_status: str
    boundary_reason: str
    counts_toward_min_windows: bool

    def selected_window(self) -> RollingResearchWindow | None:
        """Return the effective execution window when the boundary is selected."""

        if self.effective_test_end is None or not self.boundary_status.startswith(
            "candidate_"
        ):
            return None
        return RollingResearchWindow(
            label=self.label,
            train_start=self.train_start,
            train_end=self.train_end,
            test_start=self.test_start,
            test_end=self.effective_test_end,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "natural_test_end": self.natural_test_end,
            "requested_test_end": self.requested_test_end,
            "effective_test_end": self.effective_test_end,
            "complete": self.complete,
            "boundary_status": self.boundary_status,
            "boundary_reason": self.boundary_reason,
            "counts_toward_min_windows": self.counts_toward_min_windows,
        }


@dataclass(frozen=True)
class WindowSamplingPlan:
    """Immutable session-aware OOS execution and diagnostic plan."""

    policy: str
    requested_test_end: str
    min_complete_windows: int
    min_partial_window_eligible_sessions: int | None
    horizon_sessions: int
    cadence_sessions: int
    complete_window_count: int
    partial_window_count: int
    window_rows: tuple[dict[str, Any], ...]
    selected_windows: tuple[RollingResearchWindow, ...]
    sampled_date_labels: tuple[tuple[str, str], ...]

    @property
    def date_map(self) -> dict[pd.Timestamp, str]:
        return {
            pd.Timestamp(date): label for date, label in self.sampled_date_labels
        }

    @property
    def complete_minimum_satisfied(self) -> bool:
        return self.complete_window_count >= self.min_complete_windows

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WINDOW_POLICY_SCHEMA_VERSION,
            "partial_window_policy": self.policy,
            "min_windows_count_policy": MIN_WINDOWS_COUNT_POLICY,
            "requested_test_end": self.requested_test_end,
            "requested_min_complete_windows": self.min_complete_windows,
            "min_partial_window_eligible_sessions": (
                self.min_partial_window_eligible_sessions
            ),
            "horizon_sessions": self.horizon_sessions,
            "cadence_sessions": self.cadence_sessions,
            "complete_window_count": self.complete_window_count,
            "partial_window_count": self.partial_window_count,
            "complete_minimum_satisfied": self.complete_minimum_satisfied,
            "sampled_rebalance_dates": len(self.sampled_date_labels),
            "windows": [dict(row) for row in self.window_rows],
        }


def validate_partial_window_contract(
    *,
    policy: str,
    min_partial_window_eligible_sessions: int | None,
    cadence_sessions: int,
) -> None:
    """Validate the explicit partial-window portion of a research contract."""

    if policy not in ALLOWED_PARTIAL_WINDOW_POLICIES:
        raise ValueError(
            "walk_forward.partial_window_policy must be one of "
            f"{sorted(ALLOWED_PARTIAL_WINDOW_POLICIES)}"
        )
    if cadence_sessions <= 0:
        raise ValueError("cadence_sessions must be positive")
    if policy == COMPLETE_WINDOWS_ONLY:
        if min_partial_window_eligible_sessions is not None:
            raise ValueError(
                "walk_forward.min_partial_window_eligible_sessions must be omitted "
                "when partial_window_policy is complete_windows_only"
            )
        return
    if min_partial_window_eligible_sessions is None:
        raise ValueError(
            "walk_forward.min_partial_window_eligible_sessions is required when "
            "partial final windows are allowed"
        )
    if min_partial_window_eligible_sessions < cadence_sessions:
        raise ValueError(
            "walk_forward.min_partial_window_eligible_sessions must be at least "
            "strategy.rebalance_days"
        )


def build_window_boundary_decisions(
    aligned_start: str,
    requested_test_end: str,
    *,
    first_test_year: int,
    last_test_year: int,
    partial_window_policy: str,
) -> tuple[WindowBoundaryDecision, ...]:
    """Build auditable complete/partial/future half-year boundary decisions."""

    validate_partial_window_contract(
        policy=partial_window_policy,
        min_partial_window_eligible_sessions=(
            None
            if partial_window_policy == COMPLETE_WINDOWS_ONLY
            else 1
        ),
        cadence_sessions=1,
    )
    aligned_ts = pd.Timestamp(aligned_start)
    requested_end_ts = pd.Timestamp(requested_test_end)
    if aligned_ts > requested_end_ts:
        return ()

    aligned_year = int(aligned_start[:4])
    start_year = min(aligned_year, first_test_year - 1)
    natural_windows = half_year_rolling_windows(
        start_year=start_year,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    decisions: list[WindowBoundaryDecision] = []
    for window in natural_windows:
        effective_train = max(pd.Timestamp(window.train_start), aligned_ts)
        train_end = pd.Timestamp(window.train_end)
        test_start = pd.Timestamp(window.test_start)
        natural_end = pd.Timestamp(window.test_end)

        if effective_train >= train_end:
            status = "excluded_empty_training_period"
            reason = "effective train_start is not before train_end"
            effective_end: str | None = None
            complete = natural_end <= requested_end_ts
            counts = False
        elif test_start > requested_end_ts:
            status = "excluded_not_started"
            reason = "test_start is after requested_test_end"
            effective_end = None
            complete = False
            counts = False
        elif natural_end <= requested_end_ts:
            status = "candidate_complete"
            reason = "natural half-year end is within requested_test_end"
            effective_end = window.test_end
            complete = True
            counts = True
        elif partial_window_policy == COMPLETE_WINDOWS_ONLY:
            status = "excluded_partial_by_policy"
            reason = "partial final window excluded by complete_windows_only policy"
            effective_end = requested_test_end
            complete = False
            counts = False
        else:
            status = "candidate_partial_final"
            reason = "partial final window allowed subject to session eligibility"
            effective_end = requested_test_end
            complete = False
            counts = False

        decisions.append(
            WindowBoundaryDecision(
                label=window.label,
                train_start=effective_train.strftime("%Y-%m-%d"),
                train_end=window.train_end,
                test_start=window.test_start,
                natural_test_end=window.test_end,
                requested_test_end=requested_test_end,
                effective_test_end=effective_end,
                complete=complete,
                boundary_status=status,
                boundary_reason=reason,
                counts_toward_min_windows=counts,
            )
        )
    return tuple(decisions)


def complete_boundary_windows(
    aligned_start: str,
    requested_test_end: str,
    *,
    first_test_year: int,
    last_test_year: int,
) -> list[RollingResearchWindow]:
    """Return selected complete windows for boundary-only readiness checks."""

    decisions = build_window_boundary_decisions(
        aligned_start,
        requested_test_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
        partial_window_policy=COMPLETE_WINDOWS_ONLY,
    )
    return [
        window
        for decision in decisions
        if decision.boundary_status == "candidate_complete"
        for window in [decision.selected_window()]
        if window is not None
    ]


def _normalized_dates(values: pd.DatetimeIndex) -> pd.DatetimeIndex:
    dates = {
        pd.Timestamp(value).tz_localize(None).normalize()
        for value in pd.DatetimeIndex(values)
    }
    return pd.DatetimeIndex(sorted(dates))


def build_window_sampling_plan(
    available_dates: pd.DatetimeIndex,
    aligned_start: str,
    requested_test_end: str,
    *,
    first_test_year: int,
    last_test_year: int,
    min_complete_windows: int,
    partial_window_policy: str,
    min_partial_window_eligible_sessions: int | None,
    horizon_sessions: int,
    cadence_sessions: int,
) -> WindowSamplingPlan:
    """Build one session-aware plan shared by execution and diagnostics.

    Complete windows count toward ``min_complete_windows`` only when at least one
    horizon-contained rebalance date can be sampled. A partial final window is
    optional extra evidence and never contributes to the hard minimum.
    """

    if min_complete_windows < 1:
        raise ValueError("min_complete_windows must be positive")
    if horizon_sessions <= 0 or cadence_sessions <= 0:
        raise ValueError("window horizon and cadence must be positive")
    validate_partial_window_contract(
        policy=partial_window_policy,
        min_partial_window_eligible_sessions=min_partial_window_eligible_sessions,
        cadence_sessions=cadence_sessions,
    )
    dates_index = _normalized_dates(available_dates)
    requested_end_ts = pd.Timestamp(requested_test_end)
    dates_index = dates_index[dates_index <= requested_end_ts]
    decisions = build_window_boundary_decisions(
        aligned_start,
        requested_test_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
        partial_window_policy=partial_window_policy,
    )

    window_rows: list[dict[str, Any]] = []
    selected_windows: list[RollingResearchWindow] = []
    sampled_date_labels: list[tuple[str, str]] = []
    complete_count = 0
    partial_count = 0

    for decision in decisions:
        row = decision.to_dict()
        selected = decision.selected_window()
        evidence_window = selected
        if evidence_window is None and decision.effective_test_end is not None:
            evidence_window = RollingResearchWindow(
                label=decision.label,
                train_start=decision.train_start,
                train_end=decision.train_end,
                test_start=decision.test_start,
                test_end=decision.effective_test_end,
            )
        if evidence_window is None:
            row.update(
                {
                    "status": "excluded",
                    "inclusion_reason": decision.boundary_reason,
                    "available_sessions": 0,
                    "horizon_eligible_sessions": 0,
                    "excluded_tail_sessions": 0,
                    "label_horizon_sessions": horizon_sessions,
                    "sampled_sessions": 0,
                }
            )
            window_rows.append(row)
            continue

        start_date = pd.Timestamp(evidence_window.test_start)
        end_date = pd.Timestamp(evidence_window.test_end)
        window_dates = dates_index[
            (dates_index >= start_date) & (dates_index <= end_date)
        ]
        horizon_eligible = (
            window_dates[:-horizon_sessions]
            if len(window_dates) > horizon_sessions
            else window_dates[:0]
        )
        sampled = horizon_eligible[::cadence_sessions]
        include = False
        reason = decision.boundary_reason

        if decision.boundary_status == "candidate_complete":
            include = len(sampled) > 0
            if include:
                complete_count += 1
                reason = "horizon-contained sessions available"
            else:
                reason = "complete window has no horizon-contained sampled sessions"
        elif decision.boundary_status == "candidate_partial_final":
            minimum = int(min_partial_window_eligible_sessions or 0)
            include = len(horizon_eligible) >= minimum and len(sampled) > 0
            if include:
                partial_count += 1
                reason = (
                    "partial final window meets declared horizon-eligible "
                    "session minimum"
                )
            else:
                reason = (
                    "partial final window has "
                    f"{len(horizon_eligible)} horizon-eligible sessions; "
                    f"requires at least {minimum}"
                )

        row.update(
            {
                "status": "included" if include else "excluded",
                "inclusion_reason": reason,
                "available_sessions": int(len(window_dates)),
                "horizon_eligible_sessions": int(len(horizon_eligible)),
                "excluded_tail_sessions": int(
                    len(window_dates) - len(horizon_eligible)
                ),
                "label_horizon_sessions": horizon_sessions,
                "sampled_sessions": int(len(sampled)) if include else 0,
            }
        )
        if include:
            if selected is None:
                raise ValueError(
                    f"included window {decision.label} has no selected boundary"
                )
            selected_windows.append(selected)
            sampled_date_labels.extend(
                (pd.Timestamp(date).strftime("%Y-%m-%d"), decision.label)
                for date in sampled
            )
        window_rows.append(row)

    sampled_date_labels.sort(key=lambda item: item[0])
    for (left_date, _), (right_date, _) in zip(
        sampled_date_labels, sampled_date_labels[1:]
    ):
        left_position = dates_index.get_loc(pd.Timestamp(left_date))
        right_position = dates_index.get_loc(pd.Timestamp(right_date))
        if int(right_position) - int(left_position) < cadence_sessions:
            raise ValueError("window sampling produced overlapping rebalance cadence")

    return WindowSamplingPlan(
        policy=partial_window_policy,
        requested_test_end=requested_test_end,
        min_complete_windows=min_complete_windows,
        min_partial_window_eligible_sessions=(
            min_partial_window_eligible_sessions
        ),
        horizon_sessions=horizon_sessions,
        cadence_sessions=cadence_sessions,
        complete_window_count=complete_count,
        partial_window_count=partial_count,
        window_rows=tuple(window_rows),
        selected_windows=tuple(selected_windows),
        sampled_date_labels=tuple(sampled_date_labels),
    )

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

