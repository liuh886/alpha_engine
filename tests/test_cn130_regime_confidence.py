from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_cn130_regime_confidence import (
    ConfidenceVariant,
    build_regime_composite,
    choose_sector_4x1,
    market_states,
)


def test_market_states_apply_predeclared_rules() -> None:
    index = pd.date_range("2020-01-01", periods=180, freq="B")
    close = pd.Series(np.linspace(100.0, 140.0, len(index)), index=index)
    states = market_states(close)
    assert states.iloc[-1] == "risk_on"

    falling = pd.Series(np.linspace(140.0, 90.0, len(index)), index=index)
    states = market_states(falling)
    assert states.iloc[-1] == "risk_off"


def _synthetic_day() -> pd.DataFrame:
    rows = []
    for sector_idx, sector in enumerate(["A", "B", "C", "D", "E"]):
        for name_idx in range(3):
            score = 10.0 - sector_idx - name_idx * 0.1
            rows.append(
                {
                    "instrument": f"{sector_idx}{name_idx}",
                    "sector": sector,
                    "score": score,
                    "execution_forward_return": 0.01,
                }
            )
    return pd.DataFrame(rows)


def test_sector_4x1_selects_top_name_in_top_four_sectors() -> None:
    day = _synthetic_day()
    thresholds = {"fourth_sector_score_threshold": 0.0, "sector_gap_threshold": 0.0}
    chosen, exposure, _ = choose_sector_4x1(
        day,
        thresholds,
        ConfidenceVariant("baseline"),
        "neutral",
    )
    assert list(chosen["sector"]) == ["A", "B", "C", "D"]
    assert list(chosen["instrument"]) == ["00", "10", "20", "30"]
    assert exposure == 1.0


def test_risk_off_half_cash_keeps_names_but_halves_exposure() -> None:
    day = _synthetic_day()
    thresholds = {"fourth_sector_score_threshold": 0.0, "sector_gap_threshold": 0.0}
    chosen, exposure, _ = choose_sector_4x1(
        day,
        thresholds,
        ConfidenceVariant("half", risk_off_exposure=0.5),
        "risk_off",
    )
    assert len(chosen) == 4
    assert exposure == 0.5


def test_regime_composite_applies_frozen_signs() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    index = pd.MultiIndex.from_product([dates, ["A", "B"]], names=["datetime", "instrument"])
    factor = pd.Series([1.0, 2.0, 3.0, 1.0], index=index)
    states = pd.Series(["risk_on", "risk_off"], index=dates)
    selected = {
        "risk_on": [{"factor_id": "f", "sign": 1}],
        "risk_off": [{"factor_id": "f", "sign": -1}],
    }
    result = build_regime_composite({"f": factor}, states, selected)
    assert result.loc[(dates[0], "B")] > result.loc[(dates[0], "A")]
    assert result.loc[(dates[1], "B")] > result.loc[(dates[1], "A")]
