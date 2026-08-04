from __future__ import annotations

import pandas as pd

from src.research.v4_23_xgb_lambdarank_embargo import embargo_train_end


def test_ten_session_embargo_removes_one_prior_ten_day_group() -> None:
    decision_dates = pd.DatetimeIndex(
        pd.date_range("2015-01-02", periods=12, freq="10B")
    )
    test_start = decision_dates[8]
    train_end = embargo_train_end(
        decision_dates,
        test_start,
        decision_dates[7],
        embargo_sessions=10,
        sample_every_sessions=10,
    )
    assert train_end == decision_dates[6]
    assert decision_dates.get_loc(test_start) - decision_dates.get_loc(train_end) == 2


def test_embargo_respects_earlier_declared_training_end() -> None:
    decision_dates = pd.DatetimeIndex(
        pd.date_range("2015-01-02", periods=12, freq="10B")
    )
    declared = decision_dates[3]
    actual = embargo_train_end(
        decision_dates,
        decision_dates[8],
        declared,
        embargo_sessions=10,
        sample_every_sessions=10,
    )
    assert actual == declared
