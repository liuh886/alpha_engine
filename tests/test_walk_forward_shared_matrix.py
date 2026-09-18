"""Parallel walk-forward splits must share the parent's loaded matrix.

Regression: each child used to reload and hash the full model-matrix cache,
which multiplied disk IO and memory by the number of splits.
"""

from __future__ import annotations

import pandas as pd
import pytest

import src.research.walk_forward as walk_forward
from src.research import model_matrix_cache


def _tiny_matrix() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-05", periods=2)
    index = pd.MultiIndex.from_product([dates, ["AAA"]], names=["datetime", "instrument"])
    features = pd.DataFrame({"close": [1.0, 2.0]}, index=index)
    labels = pd.DataFrame({"label": [0.1, 0.2]}, index=index)
    return features, labels


def _run_shared(monkeypatch, *, split_workers: int):
    def forbidden_load(*args, **kwargs):
        raise AssertionError("model matrix cache must not be loaded for shared matrices")

    monkeypatch.setattr(model_matrix_cache, "load_model_matrix_snapshot", forbidden_load)

    features, labels = _tiny_matrix()
    return walk_forward.walk_forward_vectorized(
        market="us",
        train_start="2026-01-01",
        train_end="2026-06-01",
        test_window_months=1,
        step_months=1,
        label_horizon=0,
        min_train_months=1,
        split_workers=split_workers,
        use_model_matrix_cache=True,
        _provider_sha256="a" * 64,
        _shared_matrices=(features, labels, None),
        _matrices_preprocessed=True,
    )


@pytest.mark.parametrize("split_workers", [1, 2])
def test_shared_matrices_skip_cache_load(monkeypatch, split_workers: int):
    result = _run_shared(monkeypatch, split_workers=split_workers)

    assert result.matrix_cache_status == "shared_in_process"
    assert result.splits
    assert all(split.status == "skipped" for split in result.splits)
