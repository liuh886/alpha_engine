"""Exploratory factor-pool loader.

The exploratory scanner consumes the committed 261-factor YAML pool only. There
is deliberately no programmatic generation fallback: a missing or malformed pool
fails closed instead of silently changing the research surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FACTOR_POOL_PATH = PROJECT_ROOT / "configs" / "factor_pool.yaml"


def load_exploratory_factor_pool(path: str | Path | None = None) -> list[dict[str, Any]]:
    yaml_path = Path(path).resolve() if path is not None else DEFAULT_FACTOR_POOL_PATH
    if not yaml_path.is_file():
        raise FileNotFoundError(f"exploratory factor pool not found: {yaml_path}")
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("exploratory factor pool YAML must be a mapping")
    pools = payload.get("factor_pools")
    if not isinstance(pools, dict) or not pools:
        raise ValueError("exploratory factor pool requires non-empty factor_pools")

    factors: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_expressions: set[str] = set()
    for raw_category, rows in pools.items():
        category = str(raw_category).strip()
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"exploratory factor category {category!r} must be a list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"exploratory factor in {category!r} must be a mapping")
            name = str(row.get("name", "")).strip()
            expression = str(row.get("expression", "")).strip()
            if not name or not expression:
                raise ValueError("exploratory factors require name and expression")
            if name in seen_names:
                raise ValueError(f"duplicate exploratory factor name: {name}")
            seen_names.add(name)
            if expression in seen_expressions:
                continue
            seen_expressions.add(expression)
            factors.append({"name": name, "expression": expression, "category": category})
    return factors


EXPLORATORY_FACTOR_POOL = load_exploratory_factor_pool()


def factors_by_category(category: str) -> list[dict[str, Any]]:
    return [row for row in EXPLORATORY_FACTOR_POOL if row["category"] == category]


def factor_pool_summary() -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in EXPLORATORY_FACTOR_POOL:
        category = str(row["category"])
        summary[category] = summary.get(category, 0) + 1
    summary["total"] = len(EXPLORATORY_FACTOR_POOL)
    return summary


def factor_pool_json(category: str = "") -> str:
    rows = factors_by_category(category) if category else EXPLORATORY_FACTOR_POOL
    return json.dumps(
        {"total": len(rows), "summary": factor_pool_summary(), "factors": rows},
        indent=2,
    )
