"""Research projections over the governed factor foundation.

Canonical definitions and schema validation belong to :mod:`src.factors.library`.
This module projects those definitions into the group mapping expected by the
existing ranker research path. Exploratory scanning remains a separate committed
pool and has no generated fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.exploratory_pool import (
    EXPLORATORY_FACTOR_POOL,
    factor_pool_json,
    factor_pool_summary,
    factors_by_category,
    load_exploratory_factor_pool,
)
from src.factors.library import (
    FACTOR_LIBRARY_SCHEMA_VERSION,
    FactorGroup,
    factor_groups_to_ranker_feature_groups,
    load_factor_library as load_canonical_factor_library,
)

STRUCTURED_FACTOR_LIBRARY_SCHEMA = FACTOR_LIBRARY_SCHEMA_VERSION


def load_factor_library(path: str | Path) -> dict[str, FactorGroup]:
    """Project the canonical factor library into the research group mapping."""

    return dict(load_canonical_factor_library(path).groups)


def select_factor_groups(
    library: dict[str, FactorGroup], group_names: list[str]
) -> list[FactorGroup]:
    selected: list[FactorGroup] = []
    for name in group_names:
        if name not in library:
            raise ValueError(
                f"FactorGroup {name!r} not found. Available: {sorted(library)}"
            )
        selected.append(library[name])
    return selected


def resolve_factor_expressions(
    factor_ids: list[str], library: dict[str, FactorGroup]
) -> list[str]:
    definitions = {
        definition.factor_id: definition
        for group in library.values()
        for definition in group.factors
    }
    result: list[str] = []
    for factor_id in factor_ids:
        if factor_id not in definitions:
            raise ValueError(f"Unknown factor id {factor_id!r}")
        result.append(definitions[factor_id].expression)
    return result


def factor_library_manifest(groups: list[FactorGroup]) -> dict[str, object]:
    definitions = {
        definition.factor_id: definition
        for group in groups
        for definition in group.factors
    }
    return {
        "schema_version": FACTOR_LIBRARY_SCHEMA_VERSION,
        "n_groups": len(groups),
        "n_factors": len(definitions),
        "group_names": sorted(group.name for group in groups),
        "groups": [group.to_dict() for group in groups],
        "definitions": [definitions[key].to_dict() for key in sorted(definitions)],
    }


# Exploratory pool API. This is intentionally not the canonical model library.
FACTOR_LIBRARY: list[dict[str, Any]] = EXPLORATORY_FACTOR_POOL
MOMENTUM_LIBRARY = factors_by_category("momentum")
VOLATILITY_LIBRARY = factors_by_category("volatility")
VOLUME_LIBRARY = factors_by_category("volume")
MEAN_REVERSION_LIBRARY = factors_by_category("mean_reversion")
TECHNICAL_LIBRARY = factors_by_category("technical")
CROSS_FIELD_LIBRARY = factors_by_category("cross_field")
COMPOSITE_LIBRARY = factors_by_category("composite")


def load_factor_pool_from_yaml(path: str | Path | None = None) -> list[dict[str, Any]]:
    return load_exploratory_factor_pool(path)


def get_library_summary() -> dict[str, int]:
    return factor_pool_summary()


def get_factors_by_category(category: str) -> list[dict[str, Any]]:
    return factors_by_category(category)


def get_factor_library_json(category: str = "") -> str:
    return factor_pool_json(category)
