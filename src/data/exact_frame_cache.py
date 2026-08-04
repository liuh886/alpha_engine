"""Integrity-checked DataFrame snapshots bound to one exact source identity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

_FRAME_NAME = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class ExactFrameSnapshot:
    """A source snapshot whose identity and payload hashes have been verified."""

    retrieved_at: str
    frames: Mapping[str, pd.DataFrame]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_names(names: Sequence[str]) -> list[str]:
    normalized = [str(name).strip() for name in names]
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("frame names must be non-empty and unique")
    if any(not _FRAME_NAME.fullmatch(name) for name in normalized):
        raise ValueError("frame names may contain only lowercase letters, digits and _")
    return normalized


def load_exact_frame_snapshot(
    root: str | Path,
    *,
    identity: Mapping[str, Any],
    frame_names: Sequence[str],
) -> ExactFrameSnapshot | None:
    """Load a snapshot only when identity, file set and content hashes all match."""

    names = _validated_names(frame_names)
    cache_root = Path(root)
    metadata_path = cache_root / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if metadata.get("schema_version") != "1.0":
        return None
    if metadata.get("identity") != dict(identity):
        return None
    retrieved_at = str(metadata.get("retrieved_at", "")).strip()
    files = metadata.get("files")
    if not retrieved_at or not isinstance(files, dict) or set(files) != set(names):
        return None

    frames: dict[str, pd.DataFrame] = {}
    try:
        for name in names:
            entry = files[name]
            if not isinstance(entry, dict):
                return None
            relative_path = str(entry.get("path", ""))
            expected_hash = str(entry.get("sha256", ""))
            if relative_path != f"{name}.json" or len(expected_hash) != 64:
                return None
            path = cache_root / relative_path
            if not path.is_file() or _sha256(path) != expected_hash:
                return None
            frames[name] = pd.read_json(StringIO(path.read_text(encoding="utf-8")), orient="table")
    except (OSError, TypeError, ValueError):
        return None
    return ExactFrameSnapshot(retrieved_at=retrieved_at, frames=frames)


def write_exact_frame_snapshot(
    root: str | Path,
    *,
    identity: Mapping[str, Any],
    retrieved_at: str,
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Write payloads first and metadata last so partial writes cannot be reused."""

    names = _validated_names(list(frames))
    if not str(retrieved_at).strip():
        raise ValueError("retrieved_at is required")
    cache_root = Path(root)
    cache_root.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, str]] = {}
    for name in names:
        frame = frames[name]
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"cached value is not a DataFrame: {name}")
        path = cache_root / f"{name}.json"
        path.write_text(
            frame.to_json(orient="table", date_format="iso", force_ascii=False),
            encoding="utf-8",
        )
        files[name] = {"path": path.name, "sha256": _sha256(path)}

    metadata = {
        "schema_version": "1.0",
        "identity": dict(identity),
        "retrieved_at": str(retrieved_at),
        "files": files,
        "research_only": True,
        "trade_ready": False,
    }
    (cache_root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata
