"""Cutoff-bound canonical factor evidence for US/CN ranker decisions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.factors.strategy_snapshot import (
    SCHEMA_VERSION,
    StrategyFactorSnapshotError,
    validate_strategy_factor_snapshot,
)

LIBRARY_PATH = PROJECT_ROOT / "configs" / "factor_libraries" / "ohlcv.yaml"
RANKER_GROUPS = {
    "us_ranker": "momentum_volatility_volume",
    "cn_ranker": "cn_balanced_ohlcv",
}


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyFactorSnapshotError(f"{label} must be numeric")
    result = float(value)
    if result != result or abs(result) == float("inf"):
        raise StrategyFactorSnapshotError(f"{label} must be finite")
    return result


def build_ranker_factor_snapshot(
    *,
    model_family_id: str,
    signal_date: str,
    latest_data_date: str,
    factor_values: Mapping[str, float],
    factor_references: Mapping[str, Mapping[str, Any]] | None = None,
    data_freshness_ok: bool,
    library_path: str | Path = LIBRARY_PATH,
) -> dict[str, Any]:
    """Bind the exact current ranker inputs to canonical factor identities.

    ``factor_values`` contains the target-portfolio weighted mean of each model
    input at the decision cutoff. ``factor_references`` may additionally carry
    universe means or model contribution diagnostics without redefining the
    canonical factor value itself.
    """

    group = RANKER_GROUPS.get(model_family_id)
    if group is None:
        raise StrategyFactorSnapshotError(
            f"no ranker factor materializer for family {model_family_id!r}"
        )
    if not signal_date or not latest_data_date:
        raise StrategyFactorSnapshotError("ranker signal/cutoff date is required")

    library = load_factor_library(library_path)
    definitions = library.factors_for_groups([group])
    expected_ids = [definition.factor_id for definition in definitions]
    actual_ids = list(factor_values)
    if actual_ids != expected_ids:
        raise StrategyFactorSnapshotError(
            f"ranker factor identity mismatch: expected={expected_ids}, actual={actual_ids}"
        )

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

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "model_family_id": model_family_id,
        "signal_date": signal_date,
        "observation_cutoff": latest_data_date,
        "freshness": "current" if data_freshness_ok else "stale",
        "catalog_id": library.catalog.catalog_id,
        "catalog_version": library.catalog.catalog_version,
        "catalog_implementation_hash": library.catalog.implementation_hash(),
        "source_sha256": library.source_sha256,
        "groups": [group],
        "factor_count": len(rows),
        "factors": rows,
        "research_only": True,
        "trade_ready": False,
    }
    validate_strategy_factor_snapshot(snapshot)
    return snapshot
