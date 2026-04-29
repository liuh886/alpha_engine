from __future__ import annotations

import json
import time
from pathlib import Path


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


def write_latest_snapshot_file(
    *,
    output_path: str | Path,
    dataset_key: str,
    provider_uri: str,
    freq: str,
    latest_calendar_day: str,
) -> dict:
    """
    Write a small JSON marker describing the latest data snapshot.
    This is a lightweight stepping stone toward a full snapshot manager.
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
