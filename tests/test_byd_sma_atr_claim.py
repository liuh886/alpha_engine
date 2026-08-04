from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_sma_atr_claim import (
    CANDIDATES,
    add_claim_features,
    build_candidate_schedule,
    run_candidate,
    run_same_close_diagnostic,
)
from src.research.byd_v1_2_recovery_state import build_research_dataset


def _bars(periods: int = 140) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2025-01-02", periods=periods)
    close = np.linspace(30.0, 60.0, periods)
    close[-3:] = [54.0, 50.0, 46.0]
    open_ = close * 1.01
    bars = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": 2_000_000.0,
        }
    )
    sessions = pd.DataFrame(
        {
            "date": dates,
            "open_research_eligible": True,
            "volume": 2_000_000.0,
        }
    )
    return bars, sessions


def _dataset() -> pd.DataFrame:
    bars, sessions = _bars()
    return add_claim_features(build_research_dataset(bars, sessions))


def test_candidate_family_is_exactly_frozen() -> None:
    assert [spec.name for spec in CANDIDATES] == [
        "claimant_flat_atr32",
        "claimant_core50_atr32",
        "claimant_core75_atr32",
        "claimant_core75_atr36",
        "claimant_core75_confirm2_atr32",
    ]


def test_breakout_window_excludes_current_close() -> None:
    dataset = _dataset()
    date = dataset.index[100]
    expected = dataset["close"].iloc[45:100].max()
    assert np.isclose(dataset.loc[date, "prior_high_55"], expected)
    assert dataset.loc[date, "prior_high_55"] < dataset.loc[date, "close"]
    assert bool(dataset.loc[date, "breakout"])


def test_two_day_confirmation_delays_exit_one_close() -> None:
    dataset = _dataset()
    one_day = build_candidate_schedule(dataset, CANDIDATES[2]).daily
    two_day = build_candidate_schedule(dataset, CANDIDATES[4]).daily
    one_exits = one_day.index[one_day["exit_signal"]]
    two_exits = two_day.index[two_day["exit_signal"]]
    assert len(one_exits) > 0
    assert len(two_exits) > 0
    assert two_exits[-1] > one_exits[-1]
    assert set(one_day["decision_position"].unique()) <= {0.75, 1.0}
    assert set(two_day["decision_position"].unique()) <= {0.75, 1.0}


def test_next_open_execution_differs_from_same_close_diagnostic() -> None:
    dataset = _dataset()
    schedule = build_candidate_schedule(dataset, CANDIDATES[0])
    next_open = run_candidate(dataset, schedule, cost_bps=20.0)
    same_close = run_same_close_diagnostic(dataset, schedule, cost_bps=20.0)
    assert "position_at_open" in next_open.daily
    assert "position_at_close" in same_close.daily
    assert not np.allclose(
        next_open.daily["net_return"].fillna(0.0),
        same_close.daily["net_return"].reindex(next_open.daily.index).fillna(0.0),
    )


def test_trailing_stop_never_uses_future_high() -> None:
    dataset = _dataset()
    schedule = build_candidate_schedule(dataset, CANDIDATES[0]).daily
    active = schedule["decision_position"].eq(1.0)
    for date in schedule.index[active]:
        highest = schedule.loc[date, "highest_close_since_entry"]
        assert highest <= dataset.loc[:date, "close"].max() + 1e-12
