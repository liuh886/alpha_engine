"""Resolve model factor inputs through maintained canonical factor libraries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.factors.definition import FactorDefinition
from src.factors.library import load_factor_library, normalize_expression


def _resolve_library_path(root: Path, raw: str | Path) -> Path:
    root_resolved = root.resolve()
    path = Path(raw)
    resolved = (path if path.is_absolute() else root_resolved / path).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"factor library path escapes repository root: {raw}") from exc
    return resolved


def resolve_canonical_factor_ids(
    *,
    root: Path,
    library_sources: Sequence[str | Path],
    factor_ids: Sequence[str],
) -> list[FactorDefinition]:
    """Resolve one ordered factor contract across canonical libraries.

    Factor IDs and normalized expressions must each be unique in the selected
    contract.  A factor ID must have exactly one canonical owner among the
    declared sources.  The returned order is exactly the requested factor order.
    """

    sources = [str(value).strip() for value in library_sources]
    if not sources or not all(sources):
        raise ValueError("library_sources must contain at least one canonical source")
    if len(sources) != len(set(sources)):
        raise ValueError("library_sources must not contain duplicates")

    ids = [str(value).strip() for value in factor_ids]
    if not ids or not all(ids):
        raise ValueError("factor_ids must contain at least one non-empty factor id")
    if len(ids) != len(set(ids)):
        raise ValueError("factor_ids must not contain duplicates")

    requested = set(ids)
    definitions_by_id: dict[str, FactorDefinition] = {}
    source_by_id: dict[str, str] = {}
    for raw_source in sources:
        path = _resolve_library_path(root, raw_source)
        library = load_factor_library(path)
        for definition in library.catalog.definitions:
            if definition.factor_id not in requested:
                continue
            previous = source_by_id.get(definition.factor_id)
            if previous is not None:
                raise ValueError(
                    "canonical factor id has multiple declared owners: "
                    f"{definition.factor_id} in {previous} and {raw_source}"
                )
            definitions_by_id[definition.factor_id] = definition
            source_by_id[definition.factor_id] = raw_source

    missing = [factor_id for factor_id in ids if factor_id not in definitions_by_id]
    if missing:
        raise ValueError(f"unknown canonical factor ids: {missing}")

    definitions = [definitions_by_id[factor_id] for factor_id in ids]
    expression_owner: dict[str, str] = {}
    for definition in definitions:
        normalized = normalize_expression(definition.expression)
        previous = expression_owner.get(normalized)
        if previous is not None:
            raise ValueError(
                "selected canonical factors duplicate one executable expression: "
                f"{previous} and {definition.factor_id}"
            )
        expression_owner[normalized] = definition.factor_id
    return definitions


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
