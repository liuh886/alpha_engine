from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.research.model_matrix_cache import (
    load_model_matrix_snapshot,
    write_model_matrix_snapshot,
)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-02", periods=3)
    index = pd.MultiIndex.from_product(
        [dates, ["000425", "601728"]], names=["datetime", "instrument"]
    )
    features = pd.DataFrame(
        {"factor_a": [1.0, np.nan, 3.0, 4.0, 5.0, 6.0]}, index=index
    )
    labels = pd.DataFrame({"label": np.arange(6, dtype=float)}, index=index)
    benchmark = pd.DataFrame({"label": [0.1, 0.2, 0.3]}, index=dates)
    return features, labels, benchmark


def test_model_matrix_cache_requires_exact_identity_and_intact_files(
    tmp_path: Path,
) -> None:
    features, labels, benchmark = _frames()
    identity = {
        "market": "cn",
        "pool_sha256": "a" * 64,
        "provider_sha256": "b" * 64,
        "factor_sha256": "c" * 64,
        "cutoff": "2026-07-31",
    }
    manifest = write_model_matrix_snapshot(
        tmp_path,
        identity=identity,
        features=features,
        labels=labels,
        benchmark=benchmark,
    )
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False

    snapshot = load_model_matrix_snapshot(tmp_path, identity=identity)
    assert snapshot is not None
    pd.testing.assert_frame_equal(snapshot.features, features)
    pd.testing.assert_frame_equal(snapshot.labels, labels)
    pd.testing.assert_frame_equal(snapshot.benchmark, benchmark, check_freq=False)
    assert np.isnan(snapshot.features.iloc[1, 0])

    changed = {**identity, "cutoff": "2026-08-01"}
    assert load_model_matrix_snapshot(tmp_path, identity=changed) is None

    with (tmp_path / "features.npy").open("ab") as handle:
        handle.write(b"tampered")
    assert load_model_matrix_snapshot(tmp_path, identity=identity) is None
