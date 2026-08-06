"""Shared deterministic helpers for the active BYD formal publisher."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

BYD_SNAPSHOT_SHA256 = "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179"
ETF_ARTIFACT_SHA256 = "7e077664516b74546ec118f2bf0484ee650577a0898623f3f0cb8623397e061f"
ETF_ADJUSTED_SHA256 = "fc3321142b36bfb513a897c84ed59c27be6995111a3ab6fda4fe1196311b704b"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def write_json(path: Path, value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
        default=_json_default,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def allocation_action(previous: float, current: float) -> str:
    if current > previous:
        return "buy"
    if current < previous:
        return "sell"
    return "hold"
