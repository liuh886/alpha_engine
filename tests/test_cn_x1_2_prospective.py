from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

from src.research.cn_x1_2_prospective import (
    CANDIDATE_ID,
    _load_frozen_contract,
    _reporting_dates,
    _validate_frozen_signal_identity,
)

ROOT = Path(__file__).resolve().parents[1]


class CalendarRuntime:
    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        assert start == "2026-07-01"
        return pd.bdate_range(start, end)


def test_frozen_prospective_contract_keeps_promoted_signal_identity() -> None:
    spec, candidate, contract = _load_frozen_contract(ROOT)

    assert candidate.candidate_id == CANDIDATE_ID
    assert candidate.calibration.num_boost_round == 100
    assert len(contract["factor_ids"]) == 17
    assert contract["factor_ids"][-3:] == (
        "qlib_alpha158.cntd30",
        "qlib_alpha158.cord5",
        "qlib_alpha158.imin30",
    )


def test_frozen_prospective_contract_rejects_factor_drift() -> None:
    spec, candidate, contract = _load_frozen_contract(ROOT)
    changed = copy.deepcopy(contract)
    changed["expressions"] = (*changed["expressions"][:-1], "Ref($close, 1)")

    with pytest.raises(ValueError, match="frozen factor"):
        _validate_frozen_signal_identity(
            factor_contract=changed,
            calibration_identity=candidate.calibration.identity_manifest(),
            train_start=str(spec.parent.walk_forward["requested_train_start"]),
            regime_rule="two_of_three",
            exposure_policy="breadth_scaled",
        )


def test_frozen_prospective_contract_rejects_calibration_drift() -> None:
    spec, candidate, contract = _load_frozen_contract(ROOT)
    calibration = copy.deepcopy(candidate.calibration.identity_manifest())
    calibration["declared_parameters"]["seed"] = 43

    with pytest.raises(ValueError, match="frozen factor"):
        _validate_frozen_signal_identity(
            factor_contract=contract,
            calibration_identity=calibration,
            train_start=str(spec.parent.walk_forward["requested_train_start"]),
            regime_rule="two_of_three",
            exposure_policy="breadth_scaled",
        )


def test_reporting_dates_exclude_delay_plus_holding_tail() -> None:
    dates = _reporting_dates(CalendarRuntime(), "2026-08-14")
    calendar = pd.bdate_range("2026-07-01", "2026-08-14")

    assert dates[0] == pd.Timestamp("2026-07-01")
    assert dates[-1] == calendar[-12]
    assert len(dates) == len(calendar) - 11
