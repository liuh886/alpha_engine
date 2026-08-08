"""Expression-level diagnostic identity for canonical factor definitions.

Factor identity itself is ``FactorDefinition.factor_id`` plus implementation hash.
This module only groups formulas for diagnostic computation when several declared
groups reference the same canonical factor. Expression normalization is delegated
to the governed factor foundation and is not a second identity system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.factors.definition import FactorDefinition
from src.factors.library import normalize_expression

FACTOR_EXPRESSION_IDENTITY_SCHEME = "qlib_expression_text_v1"
_ALIAS_METRIC_KEYS = (
    "coverage_ratio",
    "valid_dates",
    "mean_cross_section_size",
    "mean_pearson_ic",
    "mean_rank_ic",
    "rank_ic_std",
    "rank_icir",
    "positive_rank_ic_ratio",
    "mean_top_bottom_spread",
    "positive_spread_ratio",
    "recommended_orientation",
    "oriented_mean_rank_ic",
    "oriented_rank_icir",
    "oriented_mean_top_bottom_spread",
    "direction_agreement",
    "positive_oriented_window_ratio",
    "window_metrics",
)
_ALIAS_SPECIFIC_FIELDS = {
    "factor_id",
    "factor_version",
    "display_name",
    "namespace",
    "information_family",
    "expression",
    "group",
    "implementation_hash",
}


@dataclass(frozen=True)
class FactorAlias:
    """One group membership attached to one canonical factor definition."""

    group_name: str
    factor: FactorDefinition

    def to_dict(self) -> dict[str, str]:
        return {
            "factor_id": self.factor.factor_id,
            "group": self.group_name,
            "information_family": self.factor.information_family,
            "display_name": self.factor.display_name,
            "expression": self.factor.expression,
            "implementation_hash": self.factor.implementation_hash,
        }


@dataclass(frozen=True)
class CanonicalFactorSpec:
    """One independently evaluated expression and its group memberships."""

    canonical_expression_id: str
    canonical_expression_sha256: str
    normalized_expression: str
    evaluation_expression: str
    aliases: tuple[FactorAlias, ...]


def normalize_factor_expression(expression: str) -> str:
    """Use the canonical factor-foundation normalization contract."""

    return normalize_expression(expression)


def canonical_expression_identity(expression: str) -> dict[str, str]:
    """Return deterministic expression identity for diagnostic deduplication."""

    normalized = normalize_expression(expression)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "canonical_expression_id": f"qlib-expression:{digest}",
        "canonical_expression_sha256": digest,
        "normalized_expression": normalized,
    }


def factor_identity_metadata() -> dict[str, str]:
    return {
        "scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "digest": "sha256",
        "normalization": "src.factors.library.normalize_expression",
        "equivalence_scope": "textual_not_algebraic",
        "factor_identity_authority": "FactorDefinition.factor_id+implementation_hash",
    }


def group_factor_specs_by_expression(
    factor_specs: list[tuple[str, FactorDefinition]],
) -> list[CanonicalFactorSpec]:
    """Group group-memberships by expression for one diagnostic evaluation."""

    grouped: dict[str, dict[str, Any]] = {}
    for group_name, factor in factor_specs:
        identity = canonical_expression_identity(factor.expression)
        canonical_id = identity["canonical_expression_id"]
        record = grouped.get(canonical_id)
        if record is None:
            grouped[canonical_id] = {
                **identity,
                "evaluation_expression": factor.expression,
                "aliases": [FactorAlias(group_name=group_name, factor=factor)],
            }
            continue
        if record["normalized_expression"] != identity["normalized_expression"]:
            raise ValueError("factor expression hash collision detected")
        existing_ids = {alias.factor.factor_id for alias in record["aliases"]}
        if factor.factor_id not in existing_ids:
            raise ValueError(
                "canonical factor library exposed duplicate expression IDs: "
                f"{sorted(existing_ids)} and {factor.factor_id}"
            )
        record["aliases"].append(FactorAlias(group_name=group_name, factor=factor))

    return [
        CanonicalFactorSpec(
            canonical_expression_id=str(record["canonical_expression_id"]),
            canonical_expression_sha256=str(record["canonical_expression_sha256"]),
            normalized_expression=str(record["normalized_expression"]),
            evaluation_expression=str(record["evaluation_expression"]),
            aliases=tuple(record["aliases"]),
        )
        for record in grouped.values()
    ]


def _metric_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in _ALIAS_METRIC_KEYS}


def build_canonical_factor_row(
    canonical_spec: CanonicalFactorSpec,
    diagnostic_row: dict[str, Any],
) -> dict[str, Any]:
    """Attach canonical factor/group provenance to one diagnostic row."""

    memberships = [alias.to_dict() for alias in canonical_spec.aliases]
    factor_ids = sorted({row["factor_id"] for row in memberships})
    if len(factor_ids) != 1:
        raise ValueError("one diagnostic expression must map to exactly one factor_id")
    metric_payload = {
        key: value
        for key, value in diagnostic_row.items()
        if key not in _ALIAS_SPECIFIC_FIELDS
    }
    return {
        "factor_id": factor_ids[0],
        "canonical_expression_id": canonical_spec.canonical_expression_id,
        "identity_scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "canonical_expression_sha256": canonical_spec.canonical_expression_sha256,
        "expression": canonical_spec.evaluation_expression,
        "normalized_expression": canonical_spec.normalized_expression,
        "group_count": len({row["group"] for row in memberships}),
        "groups": sorted({row["group"] for row in memberships}),
        "information_families": sorted(
            {row["information_family"] for row in memberships}
        ),
        "group_memberships": memberships,
        **metric_payload,
    }


def expand_alias_rows(canonical_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand one diagnostic row into auditable group-membership rows."""

    metrics = _metric_payload(canonical_row)
    canonical_rank = canonical_row.get("canonical_rank")
    rows: list[dict[str, Any]] = []
    for membership in canonical_row.get("group_memberships", []):
        if not isinstance(membership, dict):
            raise ValueError("factor group memberships must be objects")
        rows.append(
            {
                **membership,
                "canonical_expression_id": str(
                    canonical_row["canonical_expression_id"]
                ),
                "identity_scheme": str(canonical_row["identity_scheme"]),
                "canonical_expression_sha256": str(
                    canonical_row["canonical_expression_sha256"]
                ),
                "canonical_rank": canonical_rank,
                **metrics,
            }
        )
    return rows


def validate_alias_metric_consistency(alias_rows: list[dict[str, Any]]) -> None:
    """Fail closed when group memberships carry divergent diagnostic evidence."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in alias_rows:
        factor_id = str(row.get("factor_id", ""))
        if not factor_id:
            raise ValueError("factor diagnostic membership is missing factor_id")
        grouped.setdefault(factor_id, []).append(row)

    for factor_id, rows in grouped.items():
        expected = json.dumps(
            _metric_payload(rows[0]), sort_keys=True, separators=(",", ":")
        )
        for row in rows[1:]:
            observed = json.dumps(
                _metric_payload(row), sort_keys=True, separators=(",", ":")
            )
            if observed != expected:
                raise ValueError(
                    "factor group-membership metrics diverged for canonical factor "
                    f"{factor_id}"
                )
