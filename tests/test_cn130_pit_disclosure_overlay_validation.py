from __future__ import annotations

import pandas as pd

from scripts.run_cn130_pit_disclosure_overlay_validation import (
    calibration_gate,
    validation_gate,
    window_increment,
)


def _summary(
    relative: float,
    windows: list[float],
    *,
    drawdown: float = -0.2,
    leave_name: float = 0.1,
    leave_sector: float = 0.1,
    turnover: float = 10.0,
    sector_share: float = 0.4,
) -> dict[str, object]:
    return {
        "relative_excess": relative,
        "max_drawdown": drawdown,
        "positive_windows": sum(value > 0 for value in windows),
        "worst_window_relative_excess": min(windows),
        "leave_one_name_relative_excess": leave_name,
        "leave_one_sector_relative_excess": leave_sector,
        "turnover": turnover,
        "maximum_sector_absolute_contribution_share": sector_share,
        "window_results": [
            {"window": f"W{index}", "relative_excess": value}
            for index, value in enumerate(windows)
        ],
    }


def test_window_increment_is_overlay_minus_baseline() -> None:
    baseline = _summary(0.2, [0.01, 0.02, 0.03])
    overlay = _summary(0.3, [0.03, 0.01, 0.08])

    result = window_increment(baseline, overlay)

    assert result["incremental_relative_excess"].tolist() == [0.02, -0.01, 0.05]


def test_calibration_gate_accepts_consistent_incremental_overlay() -> None:
    baseline20 = _summary(
        -0.30,
        [-0.17, 0.01, -0.17],
        drawdown=-0.45,
        leave_name=-0.25,
        leave_sector=-0.23,
        turnover=32.0,
    )
    overlay20 = _summary(
        -0.02,
        [-0.12, 0.09, 0.02],
        drawdown=-0.26,
        leave_name=-0.01,
        leave_sector=-0.09,
        turnover=32.0,
    )
    baseline40 = _summary(-0.31, [-0.18, 0.0, -0.18])
    overlay40 = _summary(-0.04, [-0.14, 0.07, 0.01])
    increments = window_increment(baseline20, overlay20)

    assert calibration_gate(
        baseline20, overlay20, baseline40, overlay40, increments
    )


def test_validation_gate_requires_preserved_four_positive_windows() -> None:
    baseline20 = _summary(0.60, [0.10, 0.12, 0.08, 0.09])
    overlay20 = _summary(0.70, [0.12, 0.15, 0.09, 0.11])
    baseline40 = _summary(0.55, [0.09, 0.11, 0.07, 0.08])
    overlay40 = _summary(0.64, [0.11, 0.14, 0.08, 0.10])
    increments = window_increment(baseline20, overlay20)

    assert validation_gate(
        baseline20, overlay20, baseline40, overlay40, increments
    )

    failed = dict(overlay20)
    failed["positive_windows"] = 3
    assert not validation_gate(
        baseline20, failed, baseline40, overlay40, increments
    )


def test_validation_gate_rejects_nonpositive_leave_one() -> None:
    baseline20 = _summary(0.60, [0.10, 0.12, 0.08, 0.09])
    overlay20 = _summary(
        0.70,
        [0.12, 0.15, 0.09, 0.11],
        leave_name=-0.01,
    )
    baseline40 = _summary(0.55, [0.09, 0.11, 0.07, 0.08])
    overlay40 = _summary(0.64, [0.11, 0.14, 0.08, 0.10])
    increments = pd.DataFrame(
        {"incremental_relative_excess": [0.02, 0.03, 0.01, 0.02]}
    )

    assert not validation_gate(
        baseline20, overlay20, baseline40, overlay40, increments
    )
