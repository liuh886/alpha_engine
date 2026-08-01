"""Deterministic factor catalog with duplicate protection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.factors.definition import FactorDefinition


@dataclass
class FactorCatalog:
    """Ordered factor collection with immutable formula identities."""

    catalog_id: str
    catalog_version: str
    definitions: list[FactorDefinition] = field(default_factory=list)

    def add(self, definition: FactorDefinition) -> None:
        if any(row.factor_id == definition.factor_id for row in self.definitions):
            raise ValueError(f"duplicate factor_id: {definition.factor_id}")
        if any(
            row.implementation_hash == definition.implementation_hash
            for row in self.definitions
        ):
            raise ValueError(
                "duplicate factor implementation: "
                f"{definition.factor_id}"
            )
        self.definitions.append(definition)

    def extend(self, definitions: Iterable[FactorDefinition]) -> None:
        for definition in definitions:
            self.add(definition)

    def implementation_hash(self) -> str:
        payload = {
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "definitions": [
                {
                    "factor_id": row.factor_id,
                    "implementation_hash": row.implementation_hash,
                }
                for row in self.definitions
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "factor_count": len(self.definitions),
            "implementation_hash": self.implementation_hash(),
            "definitions": [row.to_dict() for row in self.definitions],
            "research_only": True,
            "trade_ready": False,
        }
