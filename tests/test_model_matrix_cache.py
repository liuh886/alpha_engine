from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.model_matrix_cache import (
    fingerprint_model_provider,
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


def _write_provider(
    root: Path,
    dates: list[str],
    values: list[float],
    *,
    symbol: str = "AAA",
    start_date: str | None = None,
    end_date: str | None = None,
) -> Path:
    calendar_dir = root / "calendars"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    (calendar_dir / "day.txt").write_text(
        "".join(f"{date}\n" for date in dates), encoding="utf-8"
    )

    feature_dir = root / "features" / symbol.lower()
    feature_dir.mkdir(parents=True, exist_ok=True)
    array = np.asarray(values, dtype=np.float32)
    (feature_dir / "close.day.bin").write_bytes(
        np.array([0], dtype=np.int32).tobytes() + array.tobytes()
    )

    instruments_dir = root / "instruments"
    instruments_dir.mkdir(parents=True, exist_ok=True)
    instrument_file = instruments_dir / "us.txt"
    instrument_file.write_text(
        f"{symbol}\t{start_date or dates[0]}\t{end_date or dates[-1]}\n",
        encoding="utf-8",
    )
    return instrument_file


def _scoped_kwargs(instrument_file: Path) -> dict:
    return {
        "instrument_file": instrument_file,
        "symbols": ["AAA"],
        "start_time": "2026-01-05",
        "end_time": "2026-01-07",
        "lookback_days": 0,
        "lookahead_days": 0,
    }


def test_scoped_fingerprint_ignores_appends_beyond_horizon(tmp_path: Path) -> None:
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    instrument_file = _write_provider(tmp_path, dates, [1.0, 2.0, 3.0, 4.0])
    kwargs = _scoped_kwargs(instrument_file)

    first = fingerprint_model_provider(tmp_path, **kwargs)

    extended_dates = [*dates, "2026-01-09"]
    _write_provider(tmp_path, extended_dates, [1.0, 2.0, 3.0, 4.0, 5.0])

    assert fingerprint_model_provider(tmp_path, **kwargs) == first


def test_scoped_fingerprint_detects_correction_inside_window(tmp_path: Path) -> None:
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    instrument_file = _write_provider(tmp_path, dates, [1.0, 2.0, 3.0, 4.0])
    kwargs = _scoped_kwargs(instrument_file)

    first = fingerprint_model_provider(tmp_path, **kwargs)

    _write_provider(tmp_path, dates, [1.0, 99.0, 3.0, 4.0])

    assert fingerprint_model_provider(tmp_path, **kwargs) != first


def test_scoped_fingerprint_detects_listing_boundary_change(tmp_path: Path) -> None:
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    instrument_file = _write_provider(tmp_path, dates, [1.0, 2.0, 3.0, 4.0])
    kwargs = _scoped_kwargs(instrument_file)

    first = fingerprint_model_provider(tmp_path, **kwargs)

    _write_provider(tmp_path, dates, [1.0, 2.0, 3.0, 4.0], end_date="2026-01-06")

    assert fingerprint_model_provider(tmp_path, **kwargs) != first


def test_scoped_fingerprint_tracks_coverage_growth_inside_window(tmp_path: Path) -> None:
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    instrument_file = _write_provider(
        tmp_path, dates, [1.0, 2.0], end_date="2026-01-06"
    )
    kwargs = _scoped_kwargs(instrument_file)

    first = fingerprint_model_provider(tmp_path, **kwargs)

    _write_provider(tmp_path, dates, [1.0, 2.0, 3.0])

    assert fingerprint_model_provider(tmp_path, **kwargs) != first


def test_scoped_fingerprint_requires_start_time(tmp_path: Path) -> None:
    dates = ["2026-01-05", "2026-01-06"]
    instrument_file = _write_provider(tmp_path, dates, [1.0, 2.0])

    with pytest.raises(ValueError, match="start_time"):
        fingerprint_model_provider(
            tmp_path,
            instrument_file=instrument_file,
            symbols=["AAA"],
            end_time="2026-01-06",
        )
