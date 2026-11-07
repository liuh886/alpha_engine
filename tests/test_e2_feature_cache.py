"""R1 shared-feature cache stays opt-in, bounded and numerically exact."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.e2_feature_cache import feature_cache_scope, get_or_build
from src.research.studies.xgb_study import _materialize_training_features


def test_disabled_cache_never_reuses_data():
    calls = []
    def produce():
        calls.append(1)
        return {"score": len(calls)}
    assert get_or_build("slice", {"date": "A"}, produce)["score"] == 1
    assert get_or_build("slice", {"date": "A"}, produce)["score"] == 2
    assert calls == [1, 1]


def test_cache_returns_independent_copies_and_is_scoped():
    calls = []
    def produce():
        calls.append(1)
        return pd.DataFrame({"close": [1.0, 2.0]})

    with feature_cache_scope(batch_spec_sha256="a" * 64) as session:
        first = get_or_build("slice", {"symbol": "KLAC"}, produce)
        first.loc[0, "close"] = 999.0
        second = get_or_build("slice", {"symbol": "KLAC"}, produce)
        assert second["close"].tolist() == [1.0, 2.0]
        assert session.summary()["hits"] == 1
        assert session.summary()["misses"] == 1
        assert len(calls) == 1
        # A different fold or source request does not reuse the previous value.
        get_or_build("slice", {"symbol": "CRWD"}, produce)
        assert len(calls) == 2
    assert session.entries == {}
    # Even an identical batch identity cannot leak values beyond its scope.
    with feature_cache_scope(batch_spec_sha256="a" * 64) as next_session:
        get_or_build("slice", {"symbol": "KLAC"}, produce)
        assert next_session.misses == 1
    assert len(calls) == 3


def test_bounded_memory_and_batch_identity_partitioning():
    with feature_cache_scope(batch_spec_sha256="b" * 64, max_entries=1) as session:
        get_or_build("slice", {"id": 1}, lambda: 1)
        get_or_build("slice", {"id": 2}, lambda: 2)
        assert session.evictions == 1
        get_or_build("slice", {"id": 1}, lambda: 3)
        assert session.misses == 3
        assert session.summary()["resident_entries"] == 1
    with pytest.raises(ValueError, match="invalid scoped"):
        with feature_cache_scope(batch_spec_sha256="not-a-hash"):
            pass


def _market_frame():
    days = pd.date_range("2026-01-01", periods=33, freq="B")
    rows = []
    for idx, day in enumerate(days):
        for symbol, weight in (("AAA", 1.0), ("BBB", 2.0)):
            rows.append({
                "time": day.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "close": 100.0 + weight * (idx + 1) + idx * idx * 0.01,
                "volume": 1000.0 + weight * idx,
            })
    return pd.DataFrame(rows)


def test_cached_full_feature_materialization_is_equal_to_cold_path():
    frame = _market_frame()
    cold = _materialize_training_features(frame, ("AAA", "BBB"))
    assert len(cold[0]) == 8  # 33 - 20 lookback - 5 forward label
    assert cold[1].shape == (16, 4)
    assert len(cold[2]) == 16
    assert cold[3] == [2] * 8
    calls = []
    def calculate():
        calls.append(True)
        return _materialize_training_features(frame, ("AAA", "BBB"))
    with feature_cache_scope(batch_spec_sha256="a" * 64) as session:
        first = get_or_build("train_features", {"fold": "A", "all_features": True}, calculate)
        second = get_or_build("train_features", {"fold": "A", "all_features": True}, calculate)
        # Selecting feature subsets after materialization does not corrupt the cached full set.
        first[1].loc[0, "return_5d"] = 10_000
        third = get_or_build("train_features", {"fold": "A", "all_features": True}, calculate)
        assert len(calls) == 1
        assert session.summary()["by_kind"]["train_features"] == {"hits": 2, "misses": 1}
        assert third[1].loc[0, "return_5d"] != 10_000
        assert second[1].equals(cold[1])
        assert np.array_equal(third[2].to_numpy(), cold[2].to_numpy())
        assert third[0] == cold[0] and third[3] == cold[3]
