"""Immutable factor-definition contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

_ALLOWED_ADJUSTMENTS = {"raw", "adjusted", "event_derived", "not_applicable"}
_ALLOWED_MARKETS = {"us", "cn"}
_ALLOWED_STATUSES = {
    "unvalidated_formula",
    "legacy_unverified",
    "data_blocked",
    "rejected",
    "market_specific_clue",
    "candidate",
    "redundant",
    "independent_validation_required",
    "retired",
}


@dataclass(frozen=True)
class FactorDefinition:
    """One immutable factor formula and its data/availability semantics."""

    factor_id: str
    factor_version: str
    display_name: str
    namespace: str
    information_family: str
    expression: str
    source_name: str
    source_version: str
    source_reference: str
    required_fields: tuple[str, ...]
    markets: tuple[str, ...]
    minimum_lookback: int
    availability_lag_sessions: int
    adjustment_requirement: str
    output_frequency: str
    output_dtype: str
    missing_value_policy: str
    status: str
    implementation_hash: str

    def __post_init__(self) -> None:
        if not self.factor_id.startswith(f"{self.namespace}."):
            raise ValueError("factor_id must be prefixed by namespace")
        if not self.expression:
            raise ValueError("factor expression must be non-empty")
        if not self.required_fields:
            raise ValueError("factor required_fields must be non-empty")
        if set(self.markets) - _ALLOWED_MARKETS:
            raise ValueError("factor markets must be a subset of US and CN")
        if self.minimum_lookback < 0 or self.availability_lag_sessions < 0:
            raise ValueError("factor lookback and availability lag must be non-negative")
        if self.adjustment_requirement not in _ALLOWED_ADJUSTMENTS:
            raise ValueError("unsupported adjustment requirement")
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError("unsupported factor status")
        if self.implementation_hash != self.compute_implementation_hash():
            raise ValueError("factor implementation_hash does not match definition")

    def identity_payload(self) -> dict[str, Any]:
        """Return fields that define executable factor identity."""

        return {
            "factor_id": self.factor_id,
            "factor_version": self.factor_version,
            "namespace": self.namespace,
            "expression": self.expression,
            "source_name": self.source_name,
            "source_version": self.source_version,
            "required_fields": list(self.required_fields),
            "markets": list(self.markets),
            "minimum_lookback": self.minimum_lookback,
            "availability_lag_sessions": self.availability_lag_sessions,
            "adjustment_requirement": self.adjustment_requirement,
            "output_frequency": self.output_frequency,
            "output_dtype": self.output_dtype,
            "missing_value_policy": self.missing_value_policy,
        }

    def compute_implementation_hash(self) -> str:
        encoded = json.dumps(
            self.identity_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        factor_id: str,
        factor_version: str,
        display_name: str,
        namespace: str,
        information_family: str,
        expression: str,
        source_name: str,
        source_version: str,
        source_reference: str,
        required_fields: tuple[str, ...],
        markets: tuple[str, ...],
        minimum_lookback: int,
        availability_lag_sessions: int,
        adjustment_requirement: str,
        output_frequency: str = "day",
        output_dtype: str = "float64",
        missing_value_policy: str = "preserve_nan_after_warmup",
        status: str = "unvalidated_formula",
    ) -> FactorDefinition:
        draft = cls.__new__(cls)
        payload = {
            "factor_id": factor_id,
            "factor_version": factor_version,
            "display_name": display_name,
            "namespace": namespace,
            "information_family": information_family,
            "expression": expression,
            "source_name": source_name,
            "source_version": source_version,
            "source_reference": source_reference,
            "required_fields": required_fields,
            "markets": markets,
            "minimum_lookback": minimum_lookback,
            "availability_lag_sessions": availability_lag_sessions,
            "adjustment_requirement": adjustment_requirement,
            "output_frequency": output_frequency,
            "output_dtype": output_dtype,
            "missing_value_policy": missing_value_policy,
            "status": status,
        }
        identity = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "factor_id",
                "factor_version",
                "namespace",
                "expression",
                "source_name",
                "source_version",
                "required_fields",
                "markets",
                "minimum_lookback",
                "availability_lag_sessions",
                "adjustment_requirement",
                "output_frequency",
                "output_dtype",
                "missing_value_policy",
            }
        }
        encoded = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload["implementation_hash"] = hashlib.sha256(encoded).hexdigest()
        del draft
        return cls(**payload)
