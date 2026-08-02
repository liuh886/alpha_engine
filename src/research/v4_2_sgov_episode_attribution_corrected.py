"""Accepted trough-aligned correction for the SGOV episode attribution.

The exploratory implementation measured the challenger's maximum drawdown all
the way to its eventual recovery. When that recovery extended beyond the next
baseline drawdown, later stress could be counted against an earlier episode.
The accepted method compares both strategies at the same baseline trough and
keeps recovery lag as a separate dimension.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_sgov_episode_attribution import (
    attribute_sgov_drawdown_episodes,
    evaluate_prospective_monitor_gate,
)


def attribute_sgov_drawdown_episodes_at_baseline_trough(
    baseline: StrategyResult,
    challenger: StrategyResult,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return non-overlapping trough protection and separate recovery lag."""

    episodes, _ = attribute_sgov_drawdown_episodes(
        baseline,
        challenger,
        contract,
    )
    if episodes.empty:
        return episodes, {
            "prospective_monitor_authorized": False,
            "decision": "retain_descriptive_drawdown_profile_only",
            "reason": "no_drawdown_episodes",
            "methodology": "baseline_trough_aligned",
        }

    episodes = episodes.copy()
    episodes["challenger_drawdown_at_baseline_trough"] = (
        episodes["baseline_max_drawdown"]
        + episodes["relative_return_at_baseline_trough"]
    )
    episodes["drawdown_improvement"] = episodes[
        "relative_return_at_baseline_trough"
    ]
    episodes["drawdown_improvement_pp"] = (
        episodes["drawdown_improvement"] * 100.0
    )

    gate = evaluate_prospective_monitor_gate(
        episodes,
        baseline,
        challenger,
        contract,
    )
    gate["methodology"] = "baseline_trough_aligned"
    gate["methodology_correction"] = (
        "The gate compares both strategies at the same baseline trough. "
        "The challenger's later recovery path is evaluated only through the "
        "separate recovery-lag check, preventing subsequent baseline episodes "
        "from being counted twice."
    )
    return episodes, gate
