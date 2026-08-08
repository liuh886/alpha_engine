"""Canonical schema-v2 factor library.

Factor definitions live once. Named groups reference factor IDs and never copy
formula metadata. This is the static definition seam shared by research,
formal-model configuration, runtime factor snapshots, and frontend evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from yaml import MappingNode, SafeLoader

from src.factors.catalog import FactorCatalog
from src.factors.definition import FactorDefinition

FACTOR_LIBRARY_SCHEMA_VERSION = "2.0"


def normalize_expression(expression: str) -> str:
    """Normalize Qlib expression text without claiming algebraic equivalence."""

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
        raise ValueError("factor expression must be non-empty")
    return result


def expression_identity(expression: str) -> str:
    return hashlib.sha256(normalize_expression(expression).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FactorGroup:
    """Named ordered set of canonical factor IDs."""

    name: str
    description: str
    factor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("factor group name must be non-empty")
        if not self.factor_ids:
            raise ValueError(f"factor group {self.name!r} must reference factors")
        if len(self.factor_ids) != len(set(self.factor_ids)):
            raise ValueError(f"factor group {self.name!r} contains duplicate factor IDs")


@dataclass(frozen=True)
class FactorLibrary:
    """One immutable factor catalog plus reusable group references."""

    schema_version: str
    source_path: Path
    source_sha256: str
    catalog: FactorCatalog
    groups: Mapping[str, FactorGroup]

    def factor(self, factor_id: str) -> FactorDefinition:
        for definition in self.catalog.definitions:
            if definition.factor_id == factor_id:
                return definition
        raise ValueError(f"unknown factor id: {factor_id}")

    def select_groups(self, group_names: Iterable[str]) -> list[FactorGroup]:
        selected: list[FactorGroup] = []
        for raw_name in group_names:
            name = str(raw_name)
            if name not in self.groups:
                raise ValueError(
                    f"factor group {name!r} not found; available={sorted(self.groups)}"
                )
            selected.append(self.groups[name])
        return selected

    def group_definitions(self, group: FactorGroup) -> tuple[FactorDefinition, ...]:
        return tuple(self.factor(factor_id) for factor_id in group.factor_ids)

    def factors_for_groups(self, group_names: Iterable[str]) -> list[FactorDefinition]:
        definitions: list[FactorDefinition] = []
        seen: set[str] = set()
        for group in self.select_groups(group_names):
            for factor_id in group.factor_ids:
                if factor_id in seen:
                    continue
                seen.add(factor_id)
                definitions.append(self.factor(factor_id))
        return definitions

    def resolve_expressions(self, factor_ids: Iterable[str]) -> list[str]:
        return [self.factor(str(factor_id)).expression for factor_id in factor_ids]

    def manifest(self, group_names: Iterable[str] | None = None) -> dict[str, Any]:
        if group_names is None:
            groups = list(self.groups.values())
            definitions = list(self.catalog.definitions)
        else:
            names = [str(name) for name in group_names]
            groups = self.select_groups(names)
            definitions = self.factors_for_groups(names)
        return {
            "schema_version": self.schema_version,
            "source": str(self.source_path),
            "source_sha256": self.source_sha256,
            "catalog_id": self.catalog.catalog_id,
            "catalog_version": self.catalog.catalog_version,
            "catalog_implementation_hash": self.catalog.implementation_hash(),
            "factor_count": len(definitions),
            "group_count": len(groups),
            "groups": [
                {
                    "name": group.name,
                    "description": group.description,
                    "factor_ids": list(group.factor_ids),
                }
                for group in groups
            ],
            "definitions": [definition.to_dict() for definition in definitions],
            "research_only": True,
            "trade_ready": False,
        }


def _assert_unique_mapping_keys(raw_text: str, key: str) -> None:
    composed = yaml.compose(raw_text, Loader=SafeLoader)
    if not isinstance(composed, MappingNode):
        return
    for key_node, value_node in composed.value:
        if key_node.value != key or not isinstance(value_node, MappingNode):
            continue
        seen: set[str] = set()
        for child_key, _ in value_node.value:
            value = str(child_key.value)
            if value in seen:
                raise ValueError(f"duplicate key in factor library {key}: {value}")
            seen.add(value)


def _required_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    values = tuple(str(item).strip() for item in value)
    if not all(values):
        raise ValueError(f"{field} contains an empty value")
    return values


def load_factor_library(path: str | Path) -> FactorLibrary:
    """Load the only supported factor-library schema (2.0), failing closed."""

    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"factor library not found: {source_path}")
    raw_bytes = source_path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    _assert_unique_mapping_keys(raw_text, "factors")
    _assert_unique_mapping_keys(raw_text, "groups")
    payload = yaml.safe_load(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("factor library YAML must be a mapping")
    if str(payload.get("schema_version", "")) != FACTOR_LIBRARY_SCHEMA_VERSION:
        raise ValueError(
            f"factor library requires schema_version={FACTOR_LIBRARY_SCHEMA_VERSION}"
        )

    catalog_cfg = payload.get("catalog")
    defaults = payload.get("defaults")
    raw_factors = payload.get("factors")
    raw_groups = payload.get("groups")
    if not isinstance(catalog_cfg, dict):
        raise ValueError("factor library catalog must be a mapping")
    if not isinstance(defaults, dict):
        raise ValueError("factor library defaults must be a mapping")
    if not isinstance(raw_factors, dict) or not raw_factors:
        raise ValueError("factor library factors must be a non-empty mapping")
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise ValueError("factor library groups must be a non-empty mapping")

    catalog = FactorCatalog(
        catalog_id=str(catalog_cfg.get("id", "")).strip(),
        catalog_version=str(catalog_cfg.get("version", "")).strip(),
    )
    if not catalog.catalog_id or not catalog.catalog_version:
        raise ValueError("factor library catalog id/version must be non-empty")

    expression_ids: dict[str, str] = {}
    definitions_by_id: dict[str, FactorDefinition] = {}
    namespace = str(defaults.get("namespace", "")).strip()
    for raw_factor_id, raw in raw_factors.items():
        factor_id = str(raw_factor_id).strip()
        if not isinstance(raw, dict):
            raise ValueError(f"factor {factor_id!r} must be a mapping")
        expression = str(raw.get("expression", "")).strip()
        canonical_expression = expression_identity(expression)
        previous = expression_ids.get(canonical_expression)
        if previous is not None:
            raise ValueError(
                "canonical factor library defines the same expression more than once: "
                f"{previous!r} and {factor_id!r}"
            )
        expression_ids[canonical_expression] = factor_id
        definition = FactorDefinition.create(
            factor_id=factor_id,
            factor_version=str(
                raw.get("factor_version", defaults.get("factor_version", "1.0"))
            ),
            display_name=str(raw.get("display_name", factor_id)),
            namespace=str(raw.get("namespace", namespace)),
            information_family=str(raw.get("information_family", "")).strip(),
            expression=expression,
            source_name=str(
                raw.get("source_name", defaults.get("source_name", ""))
            ).strip(),
            source_version=str(
                raw.get("source_version", defaults.get("source_version", ""))
            ).strip(),
            source_reference=str(
                raw.get("source_reference", defaults.get("source_reference", ""))
            ).strip(),
            required_fields=_required_tuple(raw.get("required_fields"), "required_fields"),
            markets=_required_tuple(raw.get("markets"), "markets"),
            minimum_lookback=int(raw.get("minimum_lookback", 0)),
            availability_lag_sessions=int(
                raw.get(
                    "availability_lag_sessions",
                    defaults.get("availability_lag_sessions", 0),
                )
            ),
            adjustment_requirement=str(
                raw.get(
                    "adjustment_requirement",
                    defaults.get("adjustment_requirement", "adjusted"),
                )
            ),
            output_frequency=str(
                raw.get("output_frequency", defaults.get("output_frequency", "day"))
            ),
            output_dtype=str(
                raw.get("output_dtype", defaults.get("output_dtype", "float64"))
            ),
            missing_value_policy=str(
                raw.get(
                    "missing_value_policy",
                    defaults.get(
                        "missing_value_policy", "preserve_nan_after_warmup"
                    ),
                )
            ),
            status=str(raw.get("status", defaults.get("status", "unvalidated_formula"))),
        )
        catalog.add(definition)
        definitions_by_id[factor_id] = definition

    groups: dict[str, FactorGroup] = {}
    for raw_group_name, raw in raw_groups.items():
        group_name = str(raw_group_name).strip()
        if not isinstance(raw, dict):
            raise ValueError(f"factor group {group_name!r} must be a mapping")
        factor_ids = _required_tuple(raw.get("factor_ids"), "factor_ids")
        unknown = [factor_id for factor_id in factor_ids if factor_id not in definitions_by_id]
        if unknown:
            raise ValueError(
                f"factor group {group_name!r} references unknown factors: {unknown}"
            )
        groups[group_name] = FactorGroup(
            name=group_name,
            description=str(raw.get("description", "")),
            factor_ids=factor_ids,
        )

    return FactorLibrary(
        schema_version=FACTOR_LIBRARY_SCHEMA_VERSION,
        source_path=source_path,
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        catalog=catalog,
        groups=groups,
    )


def factor_groups_to_ranker_feature_groups(
    library: FactorLibrary,
    groups: Iterable[FactorGroup],
):
    """Project canonical groups into the existing ranker feature-group type."""

    from src.research.ranker_calibration_grid import RankerFeatureGroup

    return [
        RankerFeatureGroup(
            name=group.name,
            expressions=tuple(
                definition.expression
                for definition in sorted(
                    library.group_definitions(group), key=lambda item: item.factor_id
                )
            ),
        )
        for group in groups
    ]
