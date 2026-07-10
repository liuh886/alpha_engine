"""Regression tests for non-fabricated daily-ranker training data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    percentile_rank_to_gain,
)


def _index() -> pd.MultiIndex:
    return pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            ["A", "B", "C"],
        ],
        names=["datetime", "instrument"],
    )


def test_prepare_ranker_frame_drops_invalid_rows_and_singleton_dates() -> None:
    index = _index()
    features = pd.DataFrame(
        {
            "momentum": [
                np.nan,
                1.0,
                2.0,
                1.0,
                np.inf,
                3.0,
                np.nan,
                np.nan,
                1.0,
            ],
            "volatility": [
                0.1,
                0.2,
                0.3,
                0.4,
                0.5,
                0.6,
                0.7,
                0.8,
                0.9,
            ],
        },
        index=index,
    )
    raw_returns = pd.DataFrame(
        {
            "return": [
                0.1,
                0.2,
                np.nan,
                0.3,
                0.2,
                0.1,
                0.3,
                0.2,
                0.1,
            ]
        },
        index=index,
    )
    raw_returns.attrs.update(
        {"provenance": "raw_forward_return", "horizon": 10}
    )

    frame_x, frame_y, groups = prepare_ranker_frame(features, raw_returns)

    expected_index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-03"), "A"),
            (pd.Timestamp("2025-01-03"), "C"),
        ],
        names=["datetime", "instrument"],
    )
    assert frame_x.index.equals(expected_index)
    assert frame_y.index.equals(expected_index)
    assert groups == [2]
    assert np.isfinite(frame_x.to_numpy()).all()
    assert np.isfinite(frame_y.to_numpy()).all()
    assert frame_y.loc[(pd.Timestamp("2025-01-03"), "A")] == pytest.approx(1.0)
    assert frame_y.loc[(pd.Timestamp("2025-01-03"), "C")] == pytest.approx(0.5)
    assert frame_y.attrs["provenance"] == "processed_daily_rank_target"
    assert frame_y.attrs["source"] == "raw_forward_return"
    assert frame_y.attrs["horizon"] == 10


def test_prepare_ranker_frame_fails_when_no_valid_cross_section_remains() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-02"]), ["A", "B"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature": [np.nan, 1.0]}, index=index)
    raw_returns = pd.DataFrame({"return": [0.1, np.nan]}, index=index)

    with pytest.raises(ValueError, match="no valid ranker training rows"):
        prepare_ranker_frame(features, raw_returns)


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_percentile_rank_to_gain_rejects_invalid_targets(invalid: float) -> None:
    target = pd.Series([0.25, invalid, 1.0], name="rank_target")

    with pytest.raises(ValueError, match="missing or non-finite"):
        percentile_rank_to_gain(target)


def test_percentile_rank_to_gain_preserves_valid_label_semantics() -> None:
    target = pd.Series([0.25, 0.5, 1.0], name="rank_target")
    target.attrs["provenance"] = "processed_daily_rank_target"

    gains = percentile_rank_to_gain(target, n_bins=5)

    assert gains.tolist() == [1, 2, 4]
    assert gains.attrs["provenance"] == "processed_daily_rank_gain_target"
    assert gains.attrs["source"] == "processed_daily_rank_target"


def test_ranker_fit_rejects_invalid_inputs_before_lightgbm_import() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "A"),
            (pd.Timestamp("2025-01-02"), "B"),
        ],
        names=["datetime", "instrument"],
    )
    target = pd.Series([0.5, 1.0], index=index, name="rank_target")

    with pytest.raises(ValueError, match="missing or non-finite"):
        fit_lgbm_daily_ranker(
            pd.DataFrame({"feature": [1.0, np.nan]}, index=index),
            target,
            [2],
        )

    with pytest.raises(ValueError, match="at least two rows"):
        fit_lgbm_daily_ranker(
            pd.DataFrame({"feature": [1.0, 2.0]}, index=index),
            target,
            [1, 1],
        )


def test_ranker_core_contains_no_missing_value_fill_defaults() -> None:
    ranker_source = Path("src/research/daily_ranker.py").read_text(encoding="utf-8")
    model_source = Path("src/research/daily_ranker_model.py").read_text(
        encoding="utf-8"
    )

    assert ".fillna(0.0)" not in ranker_source
    assert ".fillna(0.5)" not in ranker_source
    assert ".fillna(0.5)" not in model_source
