"""Resolve formal model factor inputs through the canonical factor library."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.factors.library import load_factor_library


def resolve_model_factor_inputs(
    *,
    root: Path,
    features: Mapping[str, Any],
    expected_library: Path,
    expected_count: int,
) -> tuple[list[str], list[str]]:
    """Return ordered canonical factor IDs and their executable expressions."""

    library_label = str(features.get("library") or "").strip()
    if Path(library_label) != expected_library:
        raise ValueError(
            f"factor library identity changed: expected={expected_library.as_posix()}, "
            f"actual={library_label or 'missing'}"
        )
    factor_ids = [str(value).strip() for value in features.get("factor_ids", [])]
    library = load_factor_library(root / expected_library)
    definitions = library.resolve_factors(factor_ids)
    if len(definitions) != expected_count:
        raise ValueError(
            f"factor input count changed: expected={expected_count}, actual={len(definitions)}"
        )
    return factor_ids, [definition.expression for definition in definitions]
