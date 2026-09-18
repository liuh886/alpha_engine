"""Manifest-bound, non-pickle cache for reusable model matrices."""

from __future__ import annotations

import bisect
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


def model_matrix_cache_key(identity: Mapping[str, Any]) -> str:
    """Return the canonical content key for a model-matrix identity."""
    encoded = json.dumps(
        dict(identity), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_model_provider(
    provider_root: str | Path,
    *,
    instrument_file: str | Path,
    symbols: list[str],
    start_time: str | pd.Timestamp | None = None,
    end_time: str | pd.Timestamp | None = None,
    lookback_days: int = 0,
    lookahead_days: int = 0,
) -> str:
    """Hash the exact provider inputs that can affect a matrix build.

    With ``end_time`` the digest is *date-scoped*: it covers the calendar,
    instrument listing and binary values through ``end_time`` plus
    ``lookahead_days``, but ignores any bytes appended after that horizon.
    Appending a new trading session therefore leaves the fingerprint unchanged
    while a correction inside the retained window still invalidates it.

    Without ``end_time`` the legacy whole-provider digest is returned, which
    changes whenever any byte anywhere in the provider changes.
    """
    root = Path(provider_root)
    instrument_path = Path(instrument_file)
    if end_time is not None:
        if start_time is None:
            raise ValueError("start_time is required when end_time is provided")
        return _fingerprint_model_provider_scoped(
            root,
            instrument_path,
            symbols,
            start_time=start_time,
            end_time=end_time,
            lookback_days=lookback_days,
            lookahead_days=lookahead_days,
        )
    return _fingerprint_model_provider_full(root, instrument_path, symbols)


def _fingerprint_model_provider_full(
    root: Path,
    instrument_path: Path,
    symbols: list[str],
) -> str:
    """Whole-provider digest retained for callers without a declared window."""
    digest = hashlib.sha256()

    def _include(label: str, path: Path) -> None:
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        if not path.is_file():
            digest.update(b"MISSING\0")
            return
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

    _include("instrument_file", instrument_path)
    _include("calendar/day.txt", root / "calendars" / "day.txt")
    for symbol in sorted(set(symbols)):
        feature_dir = root / "features" / symbol.lower()
        files = sorted(feature_dir.glob("*.day.bin")) if feature_dir.is_dir() else []
        if not files:
            digest.update(f"symbol/{symbol}/MISSING\0".encode("utf-8"))
            continue
        for path in files:
            _include(f"symbol/{symbol}/{path.name}", path)
    return digest.hexdigest()


def _calendar_dates(calendar_path: Path) -> list[str]:
    if not calendar_path.is_file():
        return []
    return [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _digest_scoped_instruments(
    digest: "hashlib._Hash",
    instrument_path: Path,
    symbols: list[str],
    scope_end: str,
) -> None:
    records: dict[str, tuple[str, str]] = {}
    if instrument_path.is_file():
        for line in instrument_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0].strip():
                records[parts[0].strip().upper()] = (parts[1].strip(), parts[2].strip())

    digest.update(b"instrument-file/scoped\0")
    for symbol in sorted({str(item) for item in symbols}):
        record = records.get(symbol.upper())
        if record is None:
            digest.update(f"{symbol}/MISSING\0".encode("utf-8"))
            continue
        start_date, end_date = record
        if end_date > scope_end:
            # A session appended after the retained window does not change the
            # matrix; clamp the listing boundary to the scope instead.
            end_date = scope_end
        digest.update(f"{symbol}\0{start_date}\0{end_date}\0".encode("utf-8"))


def _digest_scoped_bin(
    digest: "hashlib._Hash",
    path: Path,
    scope_end_index: int,
) -> None:
    try:
        with path.open("rb") as handle:
            header = handle.read(4)
            if len(header) < 4:
                digest.update(b"bin/SHORT-HEADER\0")
                return
            start_index = int(np.frombuffer(header, dtype=np.int32)[0])
            payload = handle.read()
    except OSError:
        digest.update(b"bin/UNREADABLE\0")
        return

    if start_index < 0:
        digest.update(b"bin/NONSTANDARD-HEADER\0")
        digest.update(header)
        digest.update(payload)
        return

    total_values = len(payload) // 4
    if scope_end_index < 0 or total_values == 0:
        digest.update(b"bin/EMPTY-SCOPE\0")
        return

    covered_until = start_index + total_values - 1
    needed_until = min(scope_end_index, covered_until)
    if needed_until < start_index:
        digest.update(b"bin/NO-DATA-IN-SCOPE\0")
        return

    value_count = needed_until - start_index + 1
    digest.update(f"bin/start={start_index};count={value_count}\0".encode("ascii"))
    digest.update(payload[: value_count * 4])


def _fingerprint_model_provider_scoped(
    root: Path,
    instrument_path: Path,
    symbols: list[str],
    *,
    start_time: str | pd.Timestamp,
    end_time: str | pd.Timestamp,
    lookback_days: int,
    lookahead_days: int,
) -> str:
    if lookback_days < 0 or lookahead_days < 0:
        raise ValueError("lookback_days and lookahead_days must be non-negative")

    calendar = _calendar_dates(root / "calendars" / "day.txt")
    start_day = pd.Timestamp(start_time).normalize().strftime("%Y-%m-%d")
    end_day = pd.Timestamp(end_time).normalize().strftime("%Y-%m-%d")
    scope_end = (
        pd.Timestamp(end_time).normalize() + pd.Timedelta(days=int(lookahead_days))
    ).strftime("%Y-%m-%d")
    scope_end_index = bisect.bisect_right(calendar, scope_end) - 1

    digest = hashlib.sha256()
    digest.update(b"model-matrix-provider-scope-v1\0")
    digest.update(
        json.dumps(
            {
                "start": start_day,
                "end": end_day,
                "lookback_days": int(lookback_days),
                "lookahead_days": int(lookahead_days),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\0")

    if not calendar:
        digest.update(b"CALENDAR-MISSING\0")
    elif scope_end_index < 0:
        digest.update(b"CALENDAR-EMPTY-IN-SCOPE\0")
    else:
        digest.update(f"calendar/{scope_end_index + 1}\0".encode("ascii"))
        for date in calendar[: scope_end_index + 1]:
            digest.update(date.encode("utf-8"))
            digest.update(b"\n")

    _digest_scoped_instruments(digest, instrument_path, symbols, scope_end)
    for symbol in sorted({str(item) for item in symbols}):
        feature_dir = root / "features" / symbol.lower()
        files = sorted(feature_dir.glob("*.day.bin")) if feature_dir.is_dir() else []
        if not files:
            digest.update(f"symbol/{symbol}/MISSING\0".encode("utf-8"))
            continue
        for path in files:
            digest.update(f"symbol/{symbol}/{path.name}\0".encode("utf-8"))
            _digest_scoped_bin(digest, path, scope_end_index)
    return digest.hexdigest()


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
    if list(values.shape) != record.get("shape") or str(values.dtype) != record.get("dtype"):
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
    dates = pd.DatetimeIndex(features.index.get_level_values("datetime")).to_numpy()
    instruments = features.index.get_level_values("instrument").astype(str).to_numpy()
    files = {
        "features": _save_array(cache_root, "features", features.to_numpy()),
        "labels": _save_array(cache_root, "labels", labels.to_numpy()),
        "index_dates": _save_array(cache_root, "index_dates", dates),
        "index_instruments": _save_array(cache_root, "index_instruments", instruments.astype(str)),
    }
    benchmark_columns: list[str] = []
    if benchmark is not None:
        benchmark_columns = [str(column) for column in benchmark.columns]
        files["benchmark"] = _save_array(cache_root, "benchmark", benchmark.to_numpy())
        files["benchmark_dates"] = _save_array(
            cache_root,
            "benchmark_dates",
            pd.DatetimeIndex(benchmark.index).to_numpy(),
        )

    manifest = {
        "schema_version": "1.0",
        "cache_key": model_matrix_cache_key(identity),
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
        or manifest.get("cache_key") != model_matrix_cache_key(identity)
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
    index = pd.MultiIndex.from_arrays([dates, instruments], names=["datetime", "instrument"])
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
