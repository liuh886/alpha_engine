"""Canonical factor-expression identity and alias accounting.

The identity scheme is intentionally conservative. Version 1 removes Unicode
whitespace outside quoted literals and hashes the normalized Qlib expression
text. It does not claim algebraic equivalence between differently written
expressions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.research.factor_library import FactorSpec

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
_ALIAS_SPECIFIC_FIELDS = {"id", "expression", "family", "description", "group"}


@dataclass(frozen=True)
class FactorAlias:
    """One configured factor id attached to a canonical expression."""

    group_name: str
    factor: FactorSpec

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.factor.id,
            "group": self.group_name,
            "family": self.factor.family,
            "description": self.factor.description,
            "expression": self.factor.expression,
        }


@dataclass(frozen=True)
class CanonicalFactorSpec:
    """One independently evaluated expression with its configured aliases."""

    canonical_expression_id: str
    canonical_expression_sha256: str
    normalized_expression: str
    evaluation_expression: str
    aliases: tuple[FactorAlias, ...]


def normalize_factor_expression(expression: str) -> str:
    """Normalize Qlib expression text for identity scheme version 1.

    Unicode whitespace outside quoted literals is removed. Whitespace inside
    single- or double-quoted literals is preserved. Parentheses, operator
    ordering, constants, function names, and literal contents remain
    significant, so this scheme never claims algebraic equivalence.
    """

    normalized: list[str] = []
    active_quote: str | None = None
    escaped = False
    for character in str(expression):
        if active_quote is not None:
            normalized.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == active_quote:
                active_quote = None
            continue

        if character in {"'", '"'}:
            active_quote = character
            normalized.append(character)
        elif not character.isspace():
            normalized.append(character)

    if active_quote is not None:
        raise ValueError("factor expression contains an unterminated quoted literal")
    result = "".join(normalized)
    if not result:
        raise ValueError("factor expression must remain non-empty after normalization")
    return result


def canonical_expression_identity(expression: str) -> dict[str, str]:
    """Return the deterministic, versioned identity for one expression."""

    normalized = normalize_factor_expression(expression)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "canonical_expression_id": f"qlib-expression:{digest}",
        "canonical_expression_sha256": digest,
        "normalized_expression": normalized,
    }


def factor_identity_metadata() -> dict[str, str]:
    """Describe the identity contract without requiring consumers to infer it."""

    return {
        "scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "digest": "sha256",
        "normalization": "remove_unicode_whitespace_outside_quoted_literals",
        "equivalence_scope": "textual_not_algebraic",
    }


def group_factor_specs_by_expression(
    factor_specs: list[tuple[str, FactorSpec]],
) -> list[CanonicalFactorSpec]:
    """Group configured factor ids by deterministic expression identity."""

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
        record["aliases"].append(FactorAlias(group_name=group_name, factor=factor))

    return [
        CanonicalFactorSpec(
            canonical_expression_id=str(record["canonical_expression_id"]),
            canonical_expression_sha256=str(
                record["canonical_expression_sha256"]
            ),
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
    """Attach identity and alias provenance to one independently computed row."""

    aliases = [alias.to_dict() for alias in canonical_spec.aliases]
    metric_payload = {
        key: value
        for key, value in diagnostic_row.items()
        if key not in _ALIAS_SPECIFIC_FIELDS
    }
    return {
        "canonical_expression_id": canonical_spec.canonical_expression_id,
        "identity_scheme": FACTOR_EXPRESSION_IDENTITY_SCHEME,
        "canonical_expression_sha256": (
            canonical_spec.canonical_expression_sha256
        ),
        "expression": canonical_spec.evaluation_expression,
        "normalized_expression": canonical_spec.normalized_expression,
        "alias_count": len(aliases),
        "alias_ids": [alias["id"] for alias in aliases],
        "groups": sorted({alias["group"] for alias in aliases}),
        "families": sorted({alias["family"] for alias in aliases}),
        "aliases": aliases,
        **metric_payload,
    }


def expand_alias_rows(canonical_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a canonical metric row into auditable per-id alias rows."""

    metrics = _metric_payload(canonical_row)
    canonical_rank = canonical_row.get("canonical_rank")
    rows: list[dict[str, Any]] = []
    for alias in canonical_row.get("aliases", []):
        if not isinstance(alias, dict):
            raise ValueError("canonical factor aliases must be objects")
        rows.append(
            {
                "id": str(alias["id"]),
                "expression": str(alias["expression"]),
                "family": str(alias["family"]),
                "description": str(alias.get("description", "")),
                "group": str(alias["group"]),
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
    """Fail closed when aliases of one identity carry divergent evidence."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in alias_rows:
        canonical_id = str(row.get("canonical_expression_id", ""))
        if not canonical_id:
            raise ValueError("factor alias is missing canonical_expression_id")
        grouped.setdefault(canonical_id, []).append(row)

    for canonical_id, rows in grouped.items():
        expected = json.dumps(
            _metric_payload(rows[0]), sort_keys=True, separators=(",", ":")
        )
        for row in rows[1:]:
            observed = json.dumps(
                _metric_payload(row), sort_keys=True, separators=(",", ":")
            )
            if observed != expected:
                raise ValueError(
                    "factor alias metrics diverged for canonical expression "
                    f"{canonical_id}: {rows[0].get('id')} vs {row.get('id')}"
                )
