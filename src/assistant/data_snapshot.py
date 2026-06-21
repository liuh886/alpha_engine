from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from src.data.snapshot import DataSnapshot
from src.data.snapshot_manifest import SnapshotManifest


def read_latest_calendar_day(provider_dir: str | Path, *, freq: str = "day") -> str | None:
    """
    Read the latest trading day from a Qlib provider directory.

    Expected layout: <provider_dir>/calendars/<freq>.txt (e.g., day.txt)
    """
    provider_dir = Path(provider_dir)
    cal_path = provider_dir / "calendars" / f"{freq}.txt"
    if not cal_path.exists():
        return None

    try:
        lines = cal_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    for line in reversed(lines):
        line = str(line).strip()
        if line:
            return line
    return None


def build_data_snapshot_id(*, dataset_key: str, freq: str, latest_calendar_day: str) -> str:
    """Legacy date-marker adapter. This ID is never authoritative."""
    dataset_key = str(dataset_key or "").strip()
    freq = str(freq or "").strip()
    latest_calendar_day = str(latest_calendar_day or "").strip()
    if not dataset_key:
        raise ValueError("dataset_key is required")
    if not freq:
        raise ValueError("freq is required")
    if not latest_calendar_day:
        raise ValueError("latest_calendar_day is required")
    return f"{dataset_key}-{freq}-{latest_calendar_day}"


def write_latest_manifest_file(
    *, output_path: str | Path, dataset_key: str, manifest: SnapshotManifest
) -> dict:
    """Atomically persist an exact manifest marker for compatibility readers."""
    if manifest.identity_version < 2 or manifest.computed_snapshot_id() != manifest.snapshot_id:
        raise ValueError("manifest identity mismatch")
    payload = {
        "dataset_key": str(dataset_key),
        "snapshot_id": manifest.snapshot_id,
        "authoritative": True,
        "manifest": manifest.to_dict(),
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.parent / f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary, output_path)
    return payload


def resolve_snapshot_provider(snapshot_id: str, *, snapshot_store: str | Path) -> Path:
    """Resolve and verify a snapshot for training/backtest/inference use."""
    return DataSnapshot.resolve_snapshot(snapshot_id, store=snapshot_store).provider_path


def write_latest_snapshot_file(
    *,
    output_path: str | Path,
    dataset_key: str,
    provider_uri: str,
    freq: str,
    latest_calendar_day: str,
) -> dict:
    """
    Write a legacy date-only marker for compatibility callers.

    New runtime consumers must use ``write_latest_manifest_file`` and
    ``resolve_snapshot_provider``.
    """
    snapshot_id = build_data_snapshot_id(
        dataset_key=dataset_key,
        freq=freq,
        latest_calendar_day=latest_calendar_day,
    )

    payload = {
        "snapshot_id": snapshot_id,
        "dataset_key": str(dataset_key),
        "provider_uri": str(provider_uri),
        "freq": str(freq),
        "latest_calendar_day": str(latest_calendar_day),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
