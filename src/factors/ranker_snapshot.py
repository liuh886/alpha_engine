"""Cutoff-bound canonical factor evidence for US/CN ranker decisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.factors.model_contract import resolve_canonical_factor_ids
from src.factors.strategy_snapshot import (
    SCHEMA_VERSION,
    StrategyFactorSnapshotError,
    validate_strategy_factor_snapshot,
)

LIBRARY_PATH = PROJECT_ROOT / "configs" / "factor_libraries" / "ohlcv.yaml"


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyFactorSnapshotError(f"{label} must be numeric")
    result = float(value)
    if result != result or abs(result) == float("inf"):
        raise StrategyFactorSnapshotError(f"{label} must be finite")
    return result


def _combined_source_identity(pairs: Sequence[tuple[str, str]]) -> str:
    """Return a deterministic digest for a multi-source factor contract."""

    encoded = "|".join(f"{left}:{right}" for left, right in pairs)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _resolve_source_path(source: str | Path) -> Path:
    path = Path(source)
    return path if path.is_absolute() else PROJECT_ROOT / path


def build_ranker_factor_snapshot(
    *,
    model_family_id: str,
    signal_date: str,
    latest_data_date: str,
    factor_values: Mapping[str, float],
    factor_references: Mapping[str, Mapping[str, Any]] | None = None,
    data_freshness_ok: bool,
    library_path: str | Path = LIBRARY_PATH,
    library_sources: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Bind the exact ordered ranker inputs to canonical factor identities.

    ``factor_values`` contains the target-portfolio weighted mean of each model
    input at the decision cutoff. Its key order is the model feature contract.
    Research factor-group labels are intentionally not inferred here because
    multiple groups may reference the same canonical factor set.

    ``library_sources`` supports a frozen multi-library contract, for example
    OHLCV plus Qlib Alpha158. Each factor ID must resolve to exactly one owner
    across the declared sources, and the returned order remains the requested
    factor order.
    """

    if not model_family_id:
        raise StrategyFactorSnapshotError("ranker model_family_id is required")
    if not signal_date or not latest_data_date:
        raise StrategyFactorSnapshotError("ranker signal/cutoff date is required")

    factor_ids = list(factor_values)
    if library_sources:
        sources = [str(value).strip() for value in library_sources]
        try:
            definitions = resolve_canonical_factor_ids(
                root=PROJECT_ROOT,
                library_sources=sources,
                factor_ids=factor_ids,
            )
        except ValueError as exc:
            raise StrategyFactorSnapshotError(str(exc)) from exc
        libraries = [load_factor_library(_resolve_source_path(source)) for source in sources]
    else:
        library = load_factor_library(library_path)
        try:
            definitions = library.resolve_factors(factor_ids)
        except ValueError as exc:
            raise StrategyFactorSnapshotError(str(exc)) from exc
        libraries = [library]

    references = factor_references or {}
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        factor_id = definition.factor_id
        rows.append(
            {
                "factor_id": factor_id,
                "factor_version": definition.factor_version,
                "implementation_hash": definition.implementation_hash,
                "display_name": definition.display_name,
                "information_family": definition.information_family,
                "value": _finite(factor_values[factor_id], factor_id),
                "reference": dict(references.get(factor_id, {})),
                "state": "observed",
                "effect": "neutral",
                "reason_code": "current_target_ranker_input",
                "observed_at": latest_data_date,
            }
        )

    if len(libraries) == 1:
        catalog_id = libraries[0].catalog.catalog_id
        catalog_version = libraries[0].catalog.catalog_version
        catalog_implementation_hash = libraries[0].catalog.implementation_hash()
        source_sha256 = libraries[0].source_sha256
    else:
        catalog_id = "+".join(library.catalog.catalog_id for library in libraries)
        catalog_version = "+".join(library.catalog.catalog_version for library in libraries)
        catalog_implementation_hash = _combined_source_identity(
            [(str(library.source_path), library.catalog.implementation_hash()) for library in libraries]
        )
        source_sha256 = _combined_source_identity(
            [(str(library.source_path), library.source_sha256) for library in libraries]
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "model_family_id": model_family_id,
        "signal_date": signal_date,
        "observation_cutoff": latest_data_date,
        "freshness": "current" if data_freshness_ok else "stale",
        "catalog_id": catalog_id,
        "catalog_version": catalog_version,
        "catalog_implementation_hash": catalog_implementation_hash,
        "source_sha256": source_sha256,
        "groups": [],
        "factor_count": len(rows),
        "factors": rows,
        "research_only": True,
        "trade_ready": False,
    }
    validate_strategy_factor_snapshot(snapshot)
    return snapshot
