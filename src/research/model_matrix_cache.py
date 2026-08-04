"""Manifest-bound, non-pickle cache for reusable model matrices."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ModelMatrixSnapshot:
    features: pd.DataFrame
    labels: pd.DataFrame
    benchmark: pd.DataFrame | None
    cache_key: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_key(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(identity), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _save_array(root: Path, name: str, values: np.ndarray) -> dict[str, Any]:
    path = root / f"{name}.npy"
    np.save(path, values, allow_pickle=False)
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "shape": list(values.shape),
        "dtype": str(values.dtype),
    }


def _load_array(root: Path, record: Mapping[str, Any]) -> np.ndarray | None:
    path = root / str(record.get("path", ""))
    if not path.is_file() or _sha256(path) != str(record.get("sha256", "")):
        return None
    try:
        values = np.load(path, allow_pickle=False, mmap_mode="r")
    except (OSError, ValueError):
        return None
    if list(values.shape) != record.get("shape") or str(values.dtype) != record.get(
        "dtype"
    ):
        return None
    return values


def write_model_matrix_snapshot(
    root: str | Path,
    *,
    identity: Mapping[str, Any],
    features: pd.DataFrame,
    labels: pd.DataFrame,
    benchmark: pd.DataFrame | None,
) -> dict[str, Any]:
    """Write arrays first and publish metadata last for atomic cache discovery."""
    if not isinstance(features.index, pd.MultiIndex) or list(features.index.names) != [
        "datetime",
        "instrument",
    ]:
        raise ValueError("features require a (datetime, instrument) MultiIndex")
    if not features.index.equals(labels.index):
        raise ValueError("feature and label indexes must match exactly")
    if features.empty or labels.empty:
        raise ValueError("model matrices must not be empty")

    cache_root = Path(root)
    cache_root.mkdir(parents=True, exist_ok=True)
    dates = pd.DatetimeIndex(
        features.index.get_level_values("datetime")
    ).to_numpy()
    instruments = features.index.get_level_values("instrument").astype(str).to_numpy()
    files = {
        "features": _save_array(cache_root, "features", features.to_numpy()),
        "labels": _save_array(cache_root, "labels", labels.to_numpy()),
        "index_dates": _save_array(cache_root, "index_dates", dates),
        "index_instruments": _save_array(
            cache_root, "index_instruments", instruments.astype(str)
        ),
    }
    benchmark_columns: list[str] = []
    if benchmark is not None:
        benchmark_columns = [str(column) for column in benchmark.columns]
        files["benchmark"] = _save_array(
            cache_root, "benchmark", benchmark.to_numpy()
        )
        files["benchmark_dates"] = _save_array(
            cache_root,
            "benchmark_dates",
            pd.DatetimeIndex(benchmark.index).to_numpy(),
        )

    manifest = {
        "schema_version": "1.0",
        "cache_key": _cache_key(identity),
        "identity": dict(identity),
        "feature_columns": [str(column) for column in features.columns],
        "label_columns": [str(column) for column in labels.columns],
        "benchmark_columns": benchmark_columns,
        "files": files,
        "research_only": True,
        "trade_ready": False,
    }
    (cache_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_model_matrix_snapshot(
    root: str | Path,
    *,
    identity: Mapping[str, Any],
) -> ModelMatrixSnapshot | None:
    """Return a snapshot only when identity and every payload hash match."""
    cache_root = Path(root)
    manifest_path = cache_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("identity") != dict(identity)
        or manifest.get("cache_key") != _cache_key(identity)
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        return None
    records = manifest.get("files")
    if not isinstance(records, dict):
        return None
    required = {"features", "labels", "index_dates", "index_instruments"}
    if not required.issubset(records):
        return None
    loaded = {name: _load_array(cache_root, records[name]) for name in records}
    if any(value is None for value in loaded.values()):
        return None

    dates = pd.DatetimeIndex(np.asarray(loaded["index_dates"]))
    instruments = np.asarray(loaded["index_instruments"]).astype(str)
    index = pd.MultiIndex.from_arrays(
        [dates, instruments], names=["datetime", "instrument"]
    )
    features = pd.DataFrame(
        np.asarray(loaded["features"]),
        index=index,
        columns=[str(value) for value in manifest.get("feature_columns", [])],
    )
    labels = pd.DataFrame(
        np.asarray(loaded["labels"]),
        index=index,
        columns=[str(value) for value in manifest.get("label_columns", [])],
    )
    benchmark = None
    if "benchmark" in records or "benchmark_dates" in records:
        if "benchmark" not in records or "benchmark_dates" not in records:
            return None
        benchmark = pd.DataFrame(
            np.asarray(loaded["benchmark"]),
            index=pd.DatetimeIndex(np.asarray(loaded["benchmark_dates"])),
            columns=[str(value) for value in manifest.get("benchmark_columns", [])],
        )
    return ModelMatrixSnapshot(
        features=features,
        labels=labels,
        benchmark=benchmark,
        cache_key=str(manifest["cache_key"]),
    )
