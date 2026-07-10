"""Regression tests for non-fabricated stable signal blending."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.run_stable_signal_blend_evidence import _complete_prediction_rows
from src.research.stable_signal_blend import daily_cross_sectional_zscore


def test_zscore_drops_invalid_rows_and_singleton_dates() -> None:
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2025-01-02", "2025-01-03"]),
            ["A", "B", "C"],
        ],
        names=["datetime", "instrument"],
    )
    score = pd.DataFrame(
        {"score": [1.0, np.nan, 3.0, np.inf, 2.0, np.nan]},
        index=index,
    )
    score.attrs["provenance"] = "fixture"

    normalized = daily_cross_sectional_zscore(score)

    expected = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "A"),
            (pd.Timestamp("2025-01-02"), "C"),
        ],
        names=["datetime", "instrument"],
    )
    assert normalized.index.equals(expected)
    assert normalized["score"].tolist() == [-1.0, 1.0]
    assert normalized.attrs["provenance"] == "fixture"
    assert normalized.attrs["transform"] == "daily_cross_sectional_zscore"


def test_zscore_keeps_valid_constant_cross_section_as_zero_signal() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    normalized = daily_cross_sectional_zscore(
        pd.DataFrame({"score": [2.0, 2.0, 2.0]}, index=index)
    )

    assert normalized["score"].tolist() == [0.0, 0.0, 0.0]


def test_prediction_rows_require_complete_finite_features() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame(
        {
            "momentum": [1.0, np.nan, 3.0],
            "volatility": [0.1, 0.2, np.inf],
            "unused": [np.nan, np.nan, np.nan],
        },
        index=index,
    )

    complete = _complete_prediction_rows(
        features,
        ["momentum", "volatility"],
    )

    assert complete.index.tolist() == [(pd.Timestamp("2025-01-02"), "A")]
    assert list(complete.columns) == ["momentum", "volatility"]


def test_stable_blend_runner_is_diagnostic_only_and_contains_no_zero_fill() -> None:
    runner_source = Path(
        "scripts/run_stable_signal_blend_evidence.py"
    ).read_text(encoding="utf-8")
    blend_source = Path("src/research/stable_signal_blend.py").read_text(
        encoding="utf-8"
    )

    assert ".fillna(0.0)" not in runner_source
    assert ".fillna(0.0)" not in blend_source
    assert '"diagnostic_only": True' in runner_source
    assert '"promotion_eligible": False' in runner_source
    assert '"trade_ready": False' in runner_source
    assert '"lifecycle_promotion": "not_evaluated"' in runner_source
