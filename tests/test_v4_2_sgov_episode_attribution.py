from __future__ import annotations

import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_sgov_episode_attribution import (
    attribute_sgov_drawdown_episodes,
    baseline_drawdown_episodes,
)


def _result(name: str, equity_values: list[float], states: list[int]) -> StrategyResult:
    index = pd.date_range("2026-01-02", periods=len(equity_values), freq="B")
    equity = pd.Series(equity_values, index=index, dtype=float)
    returns = equity.pct_change().fillna(0.0)
    daily = pd.DataFrame(
        {
            "equity": equity,
            "net_return": returns,
            "gross_return": returns,
            "transaction_cost": 0.0,
            "position_state": states,
        },
        index=index,
    )
    return StrategyResult(
        name,
        daily,
        pd.DataFrame(),
        {"strategy": name, "cagr": 0.30 if name == "baseline" else 0.27},
    )


def _contract(*, recovery_lag_max: int = 30) -> dict:
    return {
        "analysis": {
            "primary_major_episode_count": 2,
            "chronological_split_fraction": 0.60,
        },
        "prospective_monitor_gate": {
            "major_episode_drawdown_improvement_rate_min": 0.60,
            "median_major_episode_drawdown_improvement_pp_min": 1.00,
            "median_major_episode_recovery_lag_sessions_max": recovery_lag_max,
            "early_major_episode_improvement_rate_min": 0.50,
            "late_major_episode_improvement_rate_min": 0.50,
            "largest_episode_improvement_share_max": 0.60,
            "full_sample_cagr_sacrifice_pp_max": 4.00,
        },
    }


def _pair() -> tuple[StrategyResult, StrategyResult]:
    states = [0, 0, 0, 1, 1, 1, 0, 0, 1, 1]
    baseline = _result(
        "baseline",
        [1.00, 0.95, 0.90, 0.92, 1.01, 1.02, 0.98, 0.96, 1.03, 1.04],
        states,
    )
    challenger = _result(
        "challenger",
        [1.00, 0.97, 0.94, 0.96, 0.99, 1.00, 0.99, 0.98, 1.00, 1.02],
        states,
    )
    return baseline, challenger


def test_baseline_drawdown_episodes_find_peak_trough_and_recovery() -> None:
    baseline, _ = _pair()
    episodes = baseline_drawdown_episodes(baseline)
    assert len(episodes) == 2
    assert episodes.iloc[0]["baseline_max_drawdown"] == pytest.approx(-0.10)
    assert episodes.iloc[0]["baseline_recovered"]
    assert episodes.iloc[1]["baseline_recovered"]


def test_episode_attribution_records_drawdown_benefit_and_recovery_lag() -> None:
    baseline, challenger = _pair()
    episodes, gate = attribute_sgov_drawdown_episodes(
        baseline, challenger, _contract()
    )
    assert len(episodes) == 2
    assert episodes.iloc[0]["drawdown_improvement_pp"] == pytest.approx(4.0)
    assert episodes.iloc[0]["recovery_lag_sessions"] == 1
    assert episodes.iloc[1]["drawdown_improvement_pp"] > 3.0
    assert gate["prospective_monitor_authorized"]
    assert gate["checks"]["cagr_sacrifice"]


def test_gate_fails_when_recovery_lag_exceeds_predeclared_limit() -> None:
    baseline, challenger = _pair()
    _, gate = attribute_sgov_drawdown_episodes(
        baseline, challenger, _contract(recovery_lag_max=0)
    )
    assert not gate["prospective_monitor_authorized"]
    assert not gate["checks"]["major_episode_recovery_lag"]


def test_state_trace_mismatch_is_rejected() -> None:
    baseline, challenger = _pair()
    challenger.daily.loc[challenger.daily.index[-1], "position_state"] = 2
    with pytest.raises(AssertionError, match="exact state trace"):
        attribute_sgov_drawdown_episodes(baseline, challenger, _contract())
