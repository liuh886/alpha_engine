"""Deterministic raw-plus-adjustment contract for US research snapshots.

The contract preserves Yahoo raw OHLCV and adjusted close separately, derives
model-input adjusted bars through one versioned formula, and fails closed when
a refresh rewrites a frozen historical prefix. It does not mutate historical
US x1.1 evidence or imply trade readiness.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA_VERSION = "1.0"
FORMULA_VERSION = "us_raw_adjustment_v1"
FORMULA_TEXT = (
    "ratio=adj_close/raw_close; adjusted_close=adj_close; "
    "adjusted_open_high_low=raw_open_high_low*ratio; "
    "volume=raw_volume; amount=adjusted_close*volume; factor=1.0"
)
RAW_COLUMNS = (
    "date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "adj_close",
    "volume",
    "adjustment_ratio",
)
MODEL_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
)
NUMERIC_RAW_COLUMNS = RAW_COLUMNS[1:]


class HistoricalRevisionError(RuntimeError):
    """Raised when a refresh changes an already frozen historical prefix."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def formula_identity_sha256() -> str:
    return sha256_bytes(f"{FORMULA_VERSION}\n{FORMULA_TEXT}\n".encode("utf-8"))


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    return result


def normalize_yahoo_raw(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize one unadjusted Yahoo frame into immutable raw evidence."""

    if frame is None or frame.empty:
        raise ValueError("Yahoo raw frame is empty")
    result = _flatten_columns(frame).reset_index()
    result.columns = [
        str(column).strip().lower().replace(" ", "_") for column in result.columns
    ]
    if "datetime" in result.columns and "date" not in result.columns:
        result = result.rename(columns={"datetime": "date"})
    required = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise ValueError(f"Yahoo raw frame is missing columns: {missing}")

    result["date"] = pd.to_datetime(result["date"], errors="raise")
    if result["date"].dt.tz is not None:
        result["date"] = result["date"].dt.tz_localize(None)
    result["date"] = result["date"].dt.normalize()
    for column in required[1:]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    result = result.loc[:, required].dropna().sort_values("date").reset_index(drop=True)
    if result.empty:
        raise ValueError("Yahoo raw frame has no complete rows")
    if result["date"].duplicated().any():
        raise ValueError("Yahoo raw frame contains duplicate dates")
    if (result[["open", "high", "low", "close", "adj_close"]] <= 0).any().any():
        raise ValueError("Yahoo raw prices must be positive")
    if (result["volume"] < 0).any():
        raise ValueError("Yahoo volume must be non-negative")

    required_high = result[["open", "close", "low"]].max(axis=1)
    required_low = result[["open", "close", "high"]].min(axis=1)
    if (result["high"] < required_high).any() or (result["low"] > required_low).any():
        raise ValueError("Yahoo raw OHLC envelope is invalid")

    normalized = result.rename(
        columns={
            "open": "raw_open",
            "high": "raw_high",
            "low": "raw_low",
            "close": "raw_close",
        }
    )
    normalized["adjustment_ratio"] = (
        normalized["adj_close"] / normalized["raw_close"]
    )
    ratios = normalized["adjustment_ratio"].to_numpy(dtype=float)
    if not np.isfinite(ratios).all() or (ratios <= 0).any():
        raise ValueError("adjustment ratio must be finite and positive")
    return normalized.loc[:, list(RAW_COLUMNS)]


def validate_raw_contract(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize a persisted raw-contract CSV."""

    if tuple(frame.columns) != RAW_COLUMNS:
        raise ValueError(f"raw-contract columns must be {list(RAW_COLUMNS)}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    for column in NUMERIC_RAW_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        raise ValueError("raw-contract frame contains duplicate dates")
    expected_ratio = result["adj_close"] / result["raw_close"]
    if not np.allclose(
        result["adjustment_ratio"].to_numpy(dtype=float),
        expected_ratio.to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
    ):
        raise ValueError("persisted adjustment_ratio does not tie to adj_close/raw_close")
    return result


def derive_adjusted_bars(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """Derive canonical model-input bars from one validated raw snapshot."""

    raw = validate_raw_contract(raw_frame)
    ratio = raw["adjustment_ratio"].astype(float)
    output = pd.DataFrame({"date": raw["date"]})
    output["open"] = raw["raw_open"].astype(float) * ratio
    output["high"] = raw["raw_high"].astype(float) * ratio
    output["low"] = raw["raw_low"].astype(float) * ratio
    output["close"] = raw["adj_close"].astype(float)
    output["volume"] = raw["volume"].astype(float)
    output["amount"] = output["close"] * output["volume"]
    output["factor"] = 1.0

    required_high = output[["open", "close", "low"]].max(axis=1)
    required_low = output[["open", "close", "high"]].min(axis=1)
    high_gap = (required_high - output["high"]).clip(lower=0.0)
    low_gap = (output["low"] - required_low).clip(lower=0.0)
    high_scale = pd.concat([required_high.abs(), output["high"].abs()], axis=1).max(axis=1).clip(lower=1.0)
    low_scale = pd.concat([required_low.abs(), output["low"].abs()], axis=1).max(axis=1).clip(lower=1.0)
    max_relative = float(max((high_gap / high_scale).max(), (low_gap / low_scale).max()))
    if max_relative > 1e-12:
        raise ValueError(
            "derived adjusted OHLC envelope is materially invalid: "
            f"max_relative={max_relative:.12g}"
        )
    output.loc[high_gap > 0, "high"] = required_high.loc[high_gap > 0]
    output.loc[low_gap > 0, "low"] = required_low.loc[low_gap > 0]

    if not np.array_equal(
        output["close"].to_numpy(dtype=float),
        raw["adj_close"].to_numpy(dtype=float),
    ):
        raise ValueError("derived adjusted close must exactly equal Adj Close")
    return output.loc[:, list(MODEL_COLUMNS)]


def _canonical_csv_bytes(frame: pd.DataFrame, *, columns: tuple[str, ...]) -> bytes:
    output = frame.loc[:, list(columns)].copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    return output.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode(
        "utf-8"
    )


def write_raw_contract(path: str | Path, frame: pd.DataFrame) -> str:
    normalized = validate_raw_contract(frame)
    payload = _canonical_csv_bytes(normalized, columns=RAW_COLUMNS)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return sha256_bytes(payload)


def write_model_bars(path: str | Path, frame: pd.DataFrame) -> str:
    if tuple(frame.columns) != MODEL_COLUMNS:
        raise ValueError(f"model-input columns must be {list(MODEL_COLUMNS)}")
    payload = _canonical_csv_bytes(frame, columns=MODEL_COLUMNS)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return sha256_bytes(payload)


def compare_frozen_prefix(previous: pd.DataFrame, current: pd.DataFrame) -> dict[str, Any]:
    """Compare current raw evidence with an immutable historical prefix."""

    left = validate_raw_contract(previous)
    right = validate_raw_contract(current)
    cutoff = left["date"].max()
    right_prefix = right.loc[right["date"] <= cutoff].reset_index(drop=True)
    same_dates = left["date"].equals(right_prefix["date"])
    column_differences: dict[str, int] = {}
    for column in NUMERIC_RAW_COLUMNS:
        if len(left) != len(right_prefix):
            column_differences[column] = max(len(left), len(right_prefix))
            continue
        left_values = left[column].to_numpy(dtype=float)
        right_values = right_prefix[column].to_numpy(dtype=float)
        column_differences[column] = int(np.count_nonzero(left_values != right_values))
    revision_count = sum(column_differences.values())
    return {
        "previous_rows": int(len(left)),
        "current_prefix_rows": int(len(right_prefix)),
        "previous_cutoff": cutoff.date().isoformat(),
        "dates_exact": bool(same_dates),
        "column_exact_difference_counts": column_differences,
        "historical_prefix_exact": bool(same_dates and revision_count == 0),
        "appended_rows": int((right["date"] > cutoff).sum()),
    }


def enforce_append_only(previous: pd.DataFrame, current: pd.DataFrame) -> dict[str, Any]:
    report = compare_frozen_prefix(previous, current)
    if not report["historical_prefix_exact"]:
        raise HistoricalRevisionError(
            "upstream source rewrote the frozen historical prefix: "
            + json.dumps(report, sort_keys=True)
        )
    return report


def directory_identity(root: str | Path, pattern: str = "*.csv") -> dict[str, Any]:
    directory = Path(root)
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no files matched {pattern!r} under {directory}")
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    for path in files:
        file_hash = sha256_file(path)
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": file_hash,
            }
        )
    return {
        "file_count": len(rows),
        "identity_sha256": digest.hexdigest(),
        "files": rows,
    }
