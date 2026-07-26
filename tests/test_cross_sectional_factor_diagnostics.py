"""Tests for broad-IC versus concentrated-tail diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.cross_sectional_factor_diagnostics import (
    diagnose_cross_sectional_score,
)


def _frames(
    *,
    dates: tuple[str, ...] = ("2025-01-02", "2025-01-16"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(dates), [f"S{i:02d}" for i in range(40)]],
        names=["datetime", "instrument"],
    )
    scores = pd.DataFrame(
        {"score": np.tile(np.arange(40, dtype=float), len(dates))},
        index=index,
    )
    returns = pd.DataFrame(
        {"return": np.tile(np.arange(40, dtype=float) / 100.0, len(dates))},
        index=index,
    )
    returns.attrs["provenance"] = "raw_forward_return"
    returns.attrs["horizon"] = 10
    returns.attrs["expression"] = "Ref($close, -10) / $close - 1"
    return scores, returns


def test_diagnostics_measure_broad_ic_and_exact_tails() -> None:
    scores, returns = _frames()

    report = diagnose_cross_sectional_score(
        scores,
        returns,
        rebalance_dates=("2025-01-02", "2025-01-16"),
    )

    original = report["orientations"]["original"]
    inverted = report["orientations"]["inverted"]
    assert original["daily"]["mean_rank_ic"] == pytest.approx(1.0)
    assert original["rebalance"]["fixed_tails"]["3"]["mean_spread"] == pytest.approx(0.37)
    assert original["rebalance"]["fixed_tails"]["3"]["mean_selected_realized_percentile"] > 0.9
    assert inverted["daily"]["mean_rank_ic"] == pytest.approx(-1.0)
    assert inverted["rebalance"]["fixed_tails"]["3"]["mean_spread"] == pytest.approx(-0.37)
    assert report["trade_ready"] is False
    assert report["oos_selected_orientation_not_deployable"] is True


def test_tail_membership_is_frozen_before_return_availability() -> None:
    scores, returns = _frames(dates=("2025-01-02",))
    returns.loc[(pd.Timestamp("2025-01-02"), "S39"), "return"] = np.nan

    with pytest.raises(ValueError, match="selected tails lack finite raw returns"):
        diagnose_cross_sectional_score(
            scores,
            returns,
            rebalance_dates=("2025-01-02",),
        )


@pytest.mark.parametrize(
    ("attr", "value", "message"),
    [
        ("provenance", "processed_daily_rank_target", "provenance"),
        ("horizon", 5, "horizon"),
        ("expression", "", "expression"),
    ],
)
def test_diagnostics_require_canonical_raw_return_provenance(
    attr: str,
    value: object,
    message: str,
) -> None:
    scores, returns = _frames()
    returns.attrs[attr] = value

    with pytest.raises(ValueError, match=message):
        diagnose_cross_sectional_score(
            scores,
            returns,
            rebalance_dates=("2025-01-02",),
        )


def test_rebalance_dates_fail_closed_when_cross_section_is_too_small() -> None:
    scores, returns = _frames(dates=("2025-01-02",))
    instruments = scores.index.get_level_values("instrument")
    scores = scores.loc[instruments.isin([f"S{i:02d}" for i in range(10)])]

    with pytest.raises(ValueError, match="need at least"):
        diagnose_cross_sectional_score(
            scores,
            returns,
            rebalance_dates=("2025-01-02",),
        )
