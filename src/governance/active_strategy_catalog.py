"""Canonical catalog of active product strategies and their formal model identities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from src.artifacts.model_run_bundle_v2 import MODEL_KINDS, validate_catalog

SCHEMA_VERSION = "1.0.0"
FORMAL_STATUS = "accepted_formal_baseline"
ACCESS_LEVELS = {"public", "authenticated", "pro", "owner"}
MARKETS = {"us", "cn", "hk"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
DEFAULT_CATALOG_PATH = Path("configs/strategies/registry.json")


class ActiveStrategyCatalogError(ValueError):
    """Raised when active strategy identity or product policy is ambiguous."""


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActiveStrategyCatalogError(f"{label} must be a non-empty string")
    return value.strip()


def _slug(value: object, *, label: str) -> str:
    text = _required_string(value, label=label)
    if not SLUG.fullmatch(text):
        raise ActiveStrategyCatalogError(f"invalid {label}: {text!r}")
    return text


def _relative_path(value: object, *, label: str) -> str:
    text = _required_string(value, label=label).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ActiveStrategyCatalogError(f"unsafe {label}: {text!r}")
    return path.as_posix()


@dataclass(frozen=True)
class ActiveStrategy:
    strategy_id: str
    display_name: str
    model_family_id: str
    model_version_id: str
    model_kind: str
    market: str
    benchmark_id: str
    formal_status: str
    decision_cadence: str
    next_decision_policy: str
    signal_ledger: str
    historical_evidence_access: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActiveStrategy":
        model_kind = _required_string(value.get("model_kind"), label="model_kind")
        if model_kind not in MODEL_KINDS:
            raise ActiveStrategyCatalogError(f"unsupported model_kind: {model_kind}")
        market = _required_string(value.get("market"), label="market")
        if market not in MARKETS:
            raise ActiveStrategyCatalogError(f"unsupported market: {market}")
        formal_status = _required_string(value.get("formal_status"), label="formal_status")
        if formal_status != FORMAL_STATUS:
            raise ActiveStrategyCatalogError(
                f"active strategy must be {FORMAL_STATUS}: {formal_status}"
            )
        historical_access = _required_string(
            value.get("historical_evidence_access"), label="historical_evidence_access"
        )
        if historical_access not in ACCESS_LEVELS:
            raise ActiveStrategyCatalogError("unsupported historical evidence access level")
        return cls(
            strategy_id=_slug(value.get("strategy_id"), label="strategy_id"),
            display_name=_required_string(value.get("display_name"), label="display_name"),
            model_family_id=_slug(value.get("model_family_id"), label="model_family_id"),
            model_version_id=_slug(value.get("model_version_id"), label="model_version_id"),
            model_kind=model_kind,
            market=market,
            benchmark_id=_required_string(value.get("benchmark_id"), label="benchmark_id"),
            formal_status=formal_status,
            decision_cadence=_required_string(
                value.get("decision_cadence"), label="decision_cadence"
            ),
            next_decision_policy=_required_string(
                value.get("next_decision_policy"), label="next_decision_policy"
            ),
            signal_ledger=_relative_path(value.get("signal_ledger"), label="signal_ledger"),
            historical_evidence_access=historical_access,
        )


@dataclass(frozen=True)
class ActiveStrategyCatalog:
    strategies: tuple[ActiveStrategy, ...]

    @property
    def by_strategy_id(self) -> dict[str, ActiveStrategy]:
        return {row.strategy_id: row for row in self.strategies}

    @property
    def by_model_version_id(self) -> dict[str, ActiveStrategy]:
        return {row.model_version_id: row for row in self.strategies}

    @property
    def by_model_family_id(self) -> dict[str, ActiveStrategy]:
        return {row.model_family_id: row for row in self.strategies}

    @property
    def active_model_version_ids(self) -> tuple[str, ...]:
        return tuple(row.model_version_id for row in self.strategies)


def validate_active_strategy_catalog(payload: object) -> ActiveStrategyCatalog:
    if not isinstance(payload, Mapping):
        raise ActiveStrategyCatalogError("active strategy catalog root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ActiveStrategyCatalogError("unsupported active strategy catalog schema")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise ActiveStrategyCatalogError("active strategy catalog research boundary is invalid")
    _slug(payload.get("registry_id"), label="registry_id")
    rows = payload.get("strategies")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise ActiveStrategyCatalogError("active strategy catalog must contain strategies")
    strategies: list[ActiveStrategy] = []
    for index, value in enumerate(rows):
        if not isinstance(value, Mapping):
            raise ActiveStrategyCatalogError(f"strategy {index} must be an object")
        strategies.append(ActiveStrategy.from_mapping(value))

    for label, values in (
        ("strategy_id", [row.strategy_id for row in strategies]),
        ("model_version_id", [row.model_version_id for row in strategies]),
        ("model_family_id", [row.model_family_id for row in strategies]),
        ("signal_ledger", [row.signal_ledger for row in strategies]),
    ):
        if len(values) != len(set(values)):
            raise ActiveStrategyCatalogError(f"duplicate {label} in active strategy catalog")

    for row in strategies:
        if PurePosixPath(row.signal_ledger).name != row.model_version_id:
            raise ActiveStrategyCatalogError(
                f"signal ledger must terminate at active model id: {row.strategy_id}"
            )
    return ActiveStrategyCatalog(tuple(strategies))


def load_active_strategy_catalog(
    path: Path = DEFAULT_CATALOG_PATH,
) -> ActiveStrategyCatalog:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveStrategyCatalogError(f"invalid active strategy catalog: {path}") from exc
    return validate_active_strategy_catalog(payload)


def assert_formal_catalog_matches_active_strategies(
    catalog: Mapping[str, Any], active: ActiveStrategyCatalog
) -> None:
    validate_catalog(catalog)
    if catalog.get("channel") != "formal":
        raise ActiveStrategyCatalogError("active strategy catalog requires a formal catalog")
    records = catalog.get("records")
    if not isinstance(records, list):
        raise ActiveStrategyCatalogError("formal catalog records are missing")
    by_model = active.by_model_version_id
    observed: set[str] = set()
    for value in records:
        if not isinstance(value, Mapping):
            raise ActiveStrategyCatalogError("formal catalog record must be an object")
        model_version_id = str(value.get("model_version_id") or "")
        strategy = by_model.get(model_version_id)
        if strategy is None:
            raise ActiveStrategyCatalogError(
                f"formal catalog contains model outside active strategy catalog: {model_version_id}"
            )
        if value.get("model_family_id") != strategy.model_family_id:
            raise ActiveStrategyCatalogError(
                f"formal family mismatch for {strategy.strategy_id}"
            )
        if value.get("model_kind") != strategy.model_kind:
            raise ActiveStrategyCatalogError(
                f"formal model kind mismatch for {strategy.strategy_id}"
            )
        if value.get("publication_status") != strategy.formal_status:
            raise ActiveStrategyCatalogError(
                f"formal status mismatch for {strategy.strategy_id}"
            )
        observed.add(model_version_id)
    expected = set(active.active_model_version_ids)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ActiveStrategyCatalogError(
            f"formal catalog/active strategy mismatch: missing={missing}, extra={extra}"
        )
