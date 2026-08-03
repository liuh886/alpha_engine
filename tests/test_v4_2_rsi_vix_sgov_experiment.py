from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.v4_2_rsi_vix_sgov_experiment import (
    _overlay_close_trace,
    _weights_from_overlay,
    wilder_rsi,
)


def _contract() -> dict:
    return {
        "overlay_rules": {
            "activation_rsi_below": 45.0,
            "release_rsi_above": 50.0,
            "release_confirmation_closes": 2,
        },
        "allocations": {
            "base_state_0": {"QQQI": 1.0},
            "base_state_1": {"QQQI": 0.5, "QQQ": 0.5},
            "overlay_state_0": {"QQQI": 0.5, "SGOV": 0.5},
            "overlay_state_1": {"QQQI": 0.25, "QQQ": 0.5, "SGOV": 0.25},
            "state_2_frozen": {"QQQ": 0.25, "TQQQ": 0.75},
        },
        "boundaries": {"transaction_cost_bps_per_turnover_unit": 10.0},
    }


def test_wilder_rsi_matches_known_reference_values() -> None:
    close = pd.Series(
        [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
            46.03,
            46.41,
            46.22,
            45.64,
            46.21,
        ]
    )
    result = wilder_rsi(close, 14)
    assert result.iloc[:14].isna().all()
    assert result.iloc[14] == pytest.approx(70.464135, abs=1e-6)
    assert result.iloc[15] == pytest.approx(66.249619, abs=1e-6)
    assert result.iloc[20] == pytest.approx(62.880718, abs=1e-6)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.0] * 20, 50.0),
        (list(range(1, 21)), 100.0),
        (list(range(20, 0, -1)), 0.0),
    ],
)
def test_wilder_rsi_boundary_paths(values: list[float], expected: float) -> None:
    result = wilder_rsi(pd.Series(values), 14)
    assert result.dropna().iloc[-1] == pytest.approx(expected)


def test_wilder_rsi_fails_closed_across_missing_values() -> None:
    values = pd.Series([float(value) for value in range(20)])
    values.iloc[10] = np.nan
    result = wilder_rsi(values, 5)
    assert pd.isna(result.iloc[10])
    assert pd.isna(result.iloc[11])
    assert result.iloc[16:].notna().all()


def test_joint_overlay_requires_both_rsi_and_vix() -> None:
    index = pd.date_range("2026-01-01", periods=7, freq="B")
    frame = pd.DataFrame(
        {
            "rsi_14": [44.0, 44.0, 44.0, 51.0, 52.0, 52.0, 44.0],
            "vix_stress": [False, True, True, False, False, False, False],
            "vix_easing": [False, False, False, True, True, True, False],
            "vix_normalized": [False, False, False, False, False, True, False],
            "position_state": [0, 0, 1, 1, 1, 2, 1],
        },
        index=index,
    )
    trace = _overlay_close_trace(frame, _contract(), "rsi_vix_adaptive_sgov")
    assert not bool(trace.iloc[0]["overlay_active_at_close"])
    assert bool(trace.iloc[1]["overlay_active_at_close"])
    assert bool(trace.iloc[3]["overlay_active_at_close"])
    assert not bool(trace.iloc[4]["overlay_active_at_close"])

    weights, active_at_open = _weights_from_overlay(frame, trace, _contract())
    assert not bool(active_at_open.iloc[1])
    assert bool(active_at_open.iloc[2])
    assert weights.iloc[2]["SGOV"] == pytest.approx(0.25)
    assert weights.iloc[5]["QQQ"] == pytest.approx(0.25)
    assert weights.iloc[5]["TQQQ"] == pytest.approx(0.75)
    assert weights.iloc[5]["SGOV"] == pytest.approx(0.0)


def test_strict_rsi_boundaries_do_not_trigger() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="B")
    frame = pd.DataFrame(
        {
            "rsi_14": [45.0, 50.0, 50.0],
            "vix_stress": [True, False, False],
            "vix_easing": [False, True, True],
            "vix_normalized": [False, False, False],
            "position_state": [0, 0, 0],
        },
        index=index,
    )
    trace = _overlay_close_trace(frame, _contract(), "rsi_vix_adaptive_sgov")
    assert not trace["overlay_activation"].any()
    assert not trace["overlay_release"].any()


def test_vix_only_and_rsi_only_ablation_are_distinct() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="B")
    frame = pd.DataFrame(
        {
            "rsi_14": [44.0, 44.0, 51.0, 52.0],
            "vix_stress": [False, False, True, False],
            "vix_easing": [False, False, False, True],
            "vix_normalized": [False, False, False, False],
            "position_state": [0, 0, 0, 0],
        },
        index=index,
    )
    rsi = _overlay_close_trace(frame, _contract(), "rsi_only_adaptive_sgov")
    vix = _overlay_close_trace(frame, _contract(), "vix_only_adaptive_sgov")
    assert bool(rsi.iloc[0]["overlay_active_at_close"])
    assert not bool(vix.iloc[0]["overlay_active_at_close"])
    assert bool(vix.iloc[2]["overlay_active_at_close"])
