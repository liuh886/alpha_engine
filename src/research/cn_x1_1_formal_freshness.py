"""Materialize the active formal freshness contract after CN x1.1 promotion."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes


def _replace_model(values: list[Any], old: str, new: str) -> list[Any]:
    replaced = [new if value == old else value for value in values]
    if old in replaced:
        raise ValueError(f"stale formal model remains in freshness contract: {old}")
    if new not in replaced:
        raise ValueError(f"promoted formal model missing from freshness contract: {new}")
    return replaced


def write_cn_x1_1_freshness(
    *,
    repository_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    source = repository_root / "data/research/formal_backtests/freshness.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("formal freshness contract must be an object")
    for key in (
        "required_models",
        "date_range_end_required_models",
        "freshness_receipt_required_models",
    ):
        rows = value.get(key)
        if not isinstance(rows, list):
            raise ValueError(f"formal freshness field must be a list: {key}")
        value[key] = _replace_model(rows, "cn_x1_0", "cn_x1_1")
    value["declared_at"] = "2026-08-05T17:20:00Z"
    value["promotion_issue"] = 577
    value["superseded_model"] = "cn_x1_0"
    value["promoted_model"] = "cn_x1_1"
    target = output_root / "data/research/formal_backtests/freshness.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(value))
    return value
