"""Focused tests for the XGBoost daily ranker adapter.

Tests objective/config, group-size validation, and prediction alignment
against the supplied test feature index. No full-run integration or
workflow-contract tests — those belong with the runner/evidence layer.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker_model import (
    fit_xgb_daily_ranker,
    predict_xgb_daily_ranker,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_index(
    dates: list[str],
    instruments: list[str],
) -> pd.MultiIndex:
    return pd.MultiIndex.from_product(
        [pd.to_datetime(dates), instruments],
        names=["datetime", "instrument"],
    )


def _features(index: pd.MultiIndex, n_cols: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        rng.normal(size=(len(index), n_cols)),
        index=index,
        columns=[f"f{i}" for i in range(n_cols)],
    )


def _rank_target(index: pd.MultiIndex) -> pd.Series:
    rng = np.random.default_rng(99)
    vals = rng.uniform(size=len(index))
    target = pd.Series(vals, index=index, name="rank_target")
    target.attrs["provenance"] = "processed_daily_rank_target"
    target.attrs["source"] = "raw_forward_return"
    target.attrs["horizon"] = 10
    return target


# ---------------------------------------------------------------------------
# objective / config
# ---------------------------------------------------------------------------


def _flatten_config_nested(
    d: dict,
    prefix: str = "",
) -> dict[str, str]:
    """Flatten a nested dict into dot-separated keys for robust assertion."""
    out: dict[str, str] = {}
    for k, v in d.items():
        pk = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten_config_nested(v, pk))
        else:
            out[pk] = str(v)
    return out


def test_xgb_ranker_uses_rank_ndcg_objective() -> None:
    """Verify the XGBoost model is configured with rank:ndcg and expected
    defaults for a 100-estimator research comparison."""
    index = _make_index(["2026-01-02", "2026-01-05"], ["A", "B", "C"])
    feat = _features(index)
    target = _rank_target(index)

    result = fit_xgb_daily_ranker(feat, target, [3, 3], num_boost_round=5)
    cfg = json.loads(result.model.save_config())

    # XGBoost 3.x stores objective in save_config JSON, not Booster.attr()
    assert cfg["learner"]["objective"]["name"] == "rank:ndcg"

    # Flatten the full tree section to match params regardless of nesting
    flat = _flatten_config_nested(cfg["learner"]["gradient_booster"])
    assert flat["gbtree_train_param.tree_method"] == "hist"
    assert flat["tree_train_param.max_depth"] == "0"
    assert flat["tree_train_param.max_leaves"] == "31"
    assert flat["tree_train_param.grow_policy"] == "lossguide"
    assert float(flat["tree_train_param.learning_rate"]) == pytest.approx(0.05)

    assert result.n_gain_bins == 5
    assert result.feature_names == ["f0", "f1", "f2"]
    assert result.groups == [3, 3]
    assert result.target_type == "percentile_gain"


def test_xgb_ranker_respects_custom_n_gain_bins() -> None:
    index = _make_index(["2026-01-02", "2026-01-05"], ["A", "B", "C"])
    feat = _features(index)
    target = _rank_target(index)

    result = fit_xgb_daily_ranker(
        feat, target, [3, 3], n_gain_bins=10, num_boost_round=5
    )

    assert result.n_gain_bins == 10


# ---------------------------------------------------------------------------
# protected structural-param rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("objective", "reg:squarederror"),
        ("tree_method", "exact"),
        ("grow_policy", "depthwise"),
        ("max_leaves", 15),
        ("max_depth", 6),
        ("learning_rate", 0.1),
        ("seed", 123),
    ],
)
def test_xgb_ranker_rejects_override_of_protected_field(
    field: str, value: object,
) -> None:
    """Every structural fair-comparison field is rejected when overridden."""
    index = _make_index(["2026-01-02"], ["A", "B"])
    feat = _features(index)
    target = _rank_target(index)
    with pytest.raises(
        ValueError, match="structural parameters cannot be overridden"
    ):
        fit_xgb_daily_ranker(
            feat, target, [2], params={field: value}, num_boost_round=5,
        )


# ---------------------------------------------------------------------------
# group validation
# ---------------------------------------------------------------------------


def test_xgb_ranker_fails_when_group_sum_mismatches_nrows() -> None:
    index = _make_index(["2026-01-02"], ["A", "B", "C"])
    feat = _features(index)
    target = _rank_target(index)

    with pytest.raises(ValueError, match="sum\\(groups\\)"):
        fit_xgb_daily_ranker(feat, target, [2], num_boost_round=5)


def test_xgb_ranker_fails_on_singleton_group() -> None:
    index = _make_index(["2026-01-02"], ["A", "B"])
    feat = _features(index)
    target = _rank_target(index)

    with pytest.raises(ValueError, match="at least two rows"):
        fit_xgb_daily_ranker(feat, target, [1, 1], num_boost_round=5)


# ---------------------------------------------------------------------------
# prediction alignment
# ---------------------------------------------------------------------------


def test_xgb_ranker_predictions_align_to_supplied_index() -> None:
    """Predictions must exactly match the index of the features passed to
    the predict function, regardless of training index."""
    train_index = _make_index(["2026-01-02", "2026-01-05"], ["A", "B", "C"])
    train_feat = _features(train_index)
    train_target = _rank_target(train_index)
    result = fit_xgb_daily_ranker(
        train_feat, train_target, [3, 3], num_boost_round=5
    )

    test_index = _make_index(["2026-01-08"], ["X", "Y", "Z"])
    test_feat = _features(test_index)

    scores = predict_xgb_daily_ranker(result, test_feat)

    assert scores.index.equals(test_index)
    assert list(scores.index) == list(test_index)
    assert scores.columns.tolist() == ["score"]
    assert scores.shape == (3, 1)
    assert scores.attrs["provenance"] == "out_of_sample_daily_ranker_prediction"
    assert scores.attrs["model_type"] == "xgb_rank_ndcg"


def test_xgb_ranker_predict_with_subset_of_training_features() -> None:
    """Prediction with a subset of rows (different instruments, same date
    shape) still returns scores aligned to the supplied index."""
    all_instruments = ["A", "B", "C", "D"]
    index = _make_index(["2026-01-02"], all_instruments)
    feat = _features(index)
    target = _rank_target(index)
    result = fit_xgb_daily_ranker(feat, target, [4], num_boost_round=5)

    subset_index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-02"), inst) for inst in ["B", "D"]],
        names=["datetime", "instrument"],
    )
    subset_feat = _features(subset_index)

    scores = predict_xgb_daily_ranker(result, subset_feat)

    assert scores.index.equals(subset_index)
    assert len(scores) == 2
