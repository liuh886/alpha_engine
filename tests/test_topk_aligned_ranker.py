"""Contracts for the single predeclared Top-3-aligned ranker objective."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker import (
    make_daily_topk_relevance_target,
    prepare_topk_ranker_frame,
)
from src.research.daily_ranker_model import (
    fit_lgbm_daily_topk_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR


def _raw_returns(index: pd.MultiIndex, values: np.ndarray) -> pd.DataFrame:
    raw = pd.DataFrame({"return": values}, index=index)
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR
    return raw


def test_topk_target_has_exact_binary_positives_and_deterministic_ties() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "D"),
            (pd.Timestamp("2026-01-02"), "C"),
            (pd.Timestamp("2026-01-02"), "B"),
            (pd.Timestamp("2026-01-02"), "A"),
        ],
        names=["datetime", "instrument"],
    )
    raw = _raw_returns(index, np.array([0.1, 0.2, 0.3, 0.3]))

    target = make_daily_topk_relevance_target(raw, top_k=1)

    assert target.sum() == 1
    assert target.loc[(pd.Timestamp("2026-01-02"), "A")] == 1
    assert target.loc[(pd.Timestamp("2026-01-02"), "B")] == 0
    assert target.attrs == {
        "provenance": "processed_daily_topk_relevance_target",
        "source": "raw_forward_return",
        "horizon": 10,
        "top_k": 1,
    }


def test_prepare_topk_ranker_frame_selects_after_invalid_rows_are_removed() -> None:
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2026-01-02", "2026-01-05"]),
            [f"S{i}" for i in range(6)],
        ],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame(
        {
            "momentum": np.arange(len(index), dtype=float),
            "volatility": np.linspace(0.1, 1.2, len(index)),
        },
        index=index,
    )
    features.loc[(pd.Timestamp("2026-01-02"), "S5"), "momentum"] = np.nan
    raw = _raw_returns(index, np.tile(np.arange(6, dtype=float), 2))

    frame_x, target, groups = prepare_topk_ranker_frame(
        features,
        raw,
        top_k=3,
    )

    assert groups == [5, 6]
    assert target.groupby(level="datetime").sum().tolist() == [3, 3]
    assert frame_x.index.equals(target.index)
    assert (pd.Timestamp("2026-01-02"), "S5") not in target.index


def test_topk_target_requires_canonical_raw_10d_returns() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2026-01-02")], ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    raw = _raw_returns(index, np.arange(4, dtype=float))
    raw.attrs["provenance"] = "processed_daily_rank_target"

    with pytest.raises(ValueError, match="provenance"):
        make_daily_topk_relevance_target(raw, top_k=1)


def test_fit_topk_ranker_freezes_binary_gain_and_top3_cutoff() -> None:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2025-11-03", periods=6)
    instruments = [f"S{i:02d}" for i in range(12)]
    index = pd.MultiIndex.from_product(
        [dates, instruments],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame(
        rng.normal(size=(len(index), 3)),
        index=index,
        columns=["f0", "f1", "f2"],
    )
    raw = _raw_returns(index, rng.normal(size=len(index)))
    frame_x, target, groups = prepare_topk_ranker_frame(
        features,
        raw,
        top_k=3,
    )

    result = fit_lgbm_daily_topk_ranker(
        frame_x,
        target,
        groups,
        top_k=3,
        num_boost_round=5,
    )
    scores = predict_lgbm_daily_ranker(result, frame_x)

    assert result.target_type == "topk_binary_relevance"
    assert result.target_top_k == 3
    assert result.n_gain_bins == 2
    assert result.lambdarank_truncation_level == 6
    assert result.model.params["objective"] == "lambdarank"
    assert result.model.params["eval_at"] == [3]
    assert result.model.params["lambdarank_truncation_level"] == 6
    assert result.model.params["label_gain"] == [0, 1]
    assert scores.attrs["target_type"] == "topk_binary_relevance"
    assert scores.attrs["target_top_k"] == 3
    assert scores.attrs["lambdarank_truncation_level"] == 6


def test_fit_topk_ranker_rejects_structural_parameter_override() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2026-01-02")], ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature": [1.0, 2.0, 3.0, 4.0]}, index=index)
    raw = _raw_returns(index, np.array([0.1, 0.2, 0.3, 0.4]))
    frame_x, target, groups = prepare_topk_ranker_frame(
        features,
        raw,
        top_k=1,
    )

    with pytest.raises(ValueError, match="cannot be overridden"):
        fit_lgbm_daily_topk_ranker(
            frame_x,
            target,
            groups,
            top_k=1,
            params={"lambdarank_truncation_level": 30},
        )
