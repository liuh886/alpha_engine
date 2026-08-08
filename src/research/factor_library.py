"""Research projections over the governed factor foundation.

Canonical structured definitions are owned by :mod:`src.factors.library`.
Exploratory scanning is owned by :mod:`src.factors.exploratory_pool`. This module
contains only research projections needed by existing ranker/diagnostic code; it
contains no factor definitions, compatibility parser, or generated fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.definition import FactorDefinition
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
    FactorLibrary,
    factor_groups_to_ranker_feature_groups,
    load_factor_library,
)

FactorSpec = FactorDefinition
STRUCTURED_FACTOR_LIBRARY_SCHEMA = FACTOR_LIBRARY_SCHEMA_VERSION


def select_factor_groups(
    library: FactorLibrary, group_names: list[str]
) -> list[FactorGroup]:
    return library.select_groups(group_names)


def resolve_factor_expressions(
    factor_ids: list[str], library: FactorLibrary
) -> list[str]:
    return library.resolve_expressions(factor_ids)


def factor_library_manifest(groups: list[FactorGroup]) -> dict[str, object]:
    definitions: dict[str, FactorDefinition] = {}
    for group in groups:
        for definition in group.factors:
            definitions[definition.factor_id] = definition
    return {
        "schema_version": FACTOR_LIBRARY_SCHEMA_VERSION,
        "n_groups": len(groups),
        "n_factors": len(definitions),
        "group_names": sorted(group.name for group in groups),
        "groups": [group.to_dict() for group in groups],
        "definitions": [definitions[key].to_dict() for key in sorted(definitions)],
    }


# Exploratory pool is intentionally separate from the canonical model library.
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
