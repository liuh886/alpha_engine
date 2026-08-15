"""Resolve maintained runtime adapters for exact active strategy identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import yaml  # type: ignore[import-untyped]

from src.governance.active_strategy_catalog import (
    ActiveStrategy,
    ActiveStrategyCatalog,
    load_active_strategy_catalog,
)

CapabilityStatus = Literal["available", "blocked", "not_applicable"]

FORMAL_REFRESH_ADAPTERS: Mapping[str, str] = {
    "qqqi_qqq_tqqq_v4_3": "qqq_v4_3_formal_refresh_v1",
    "us_x1_3": "us_x1_3_formal_refresh_v1",
    "byd_v1_3_recovery_event_low_vol_confirmation_v1": "byd_v1_3_formal_refresh_v1",
}
CURRENT_TARGET_ADAPTERS: Mapping[str, str] = {
    "us_x1_3": "us_x1_3_current_target_v1",
}
RANKER_FORMAL_REFRESH_ADAPTERS = frozenset({"us_x1_3_formal_refresh_v1"})


class StrategyRuntimeCapabilityError(ValueError):
    """Raised when runtime capability identity is missing or inconsistent."""


@dataclass(frozen=True)
class RuntimeCapability:
    status: CapabilityStatus
    adapter_id: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "adapter_id": self.adapter_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StrategyRuntimeCapabilities:
    strategy_id: str
    model_version_id: str
    formal_refresh: RuntimeCapability
    current_target: RuntimeCapability


def _load_ranker_contract(strategy: ActiveStrategy, repository_root: Path) -> dict:
    path = repository_root / strategy.model_contract
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StrategyRuntimeCapabilityError(
            f"invalid model contract for runtime capability: {strategy.strategy_id}"
        ) from exc
    if not isinstance(value, dict):
        raise StrategyRuntimeCapabilityError(
            f"model contract must be an object: {strategy.strategy_id}"
        )
    expected = {
        "model_id": strategy.model_version_id,
        "market": strategy.market,
        "research_only": True,
        "trade_ready": False,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise StrategyRuntimeCapabilityError(
                f"model contract/runtime identity mismatch for {strategy.strategy_id}: {field}"
            )
    return value


def _available(adapter_id: str) -> RuntimeCapability:
    return RuntimeCapability(status="available", adapter_id=adapter_id)


def _blocked(reason: str) -> RuntimeCapability:
    return RuntimeCapability(status="blocked", reason=reason)


def _not_applicable(reason: str) -> RuntimeCapability:
    return RuntimeCapability(status="not_applicable", reason=reason)


def resolve_strategy_runtime_capabilities(
    strategy: ActiveStrategy,
    *,
    repository_root: Path = Path("."),
) -> StrategyRuntimeCapabilities:
    """Resolve runtime support without falling back across model versions."""

    contract: dict = {}
    if strategy.model_kind == "cross_sectional_ranker":
        contract = _load_ranker_contract(strategy, repository_root)

    formal_adapter = FORMAL_REFRESH_ADAPTERS.get(strategy.model_version_id)
    formal_refresh = (
        _available(formal_adapter)
        if formal_adapter is not None
        else _blocked(
            f"blocked_pending_maintained_{strategy.model_version_id}_formal_refresh_adapter"
        )
    )

    if strategy.model_kind != "cross_sectional_ranker":
        current_target = _not_applicable(
            "not_managed_by_cross_sectional_ranker_current_target_runtime"
        )
    else:
        publication = contract.get("formal_publication")
        activation = (
            publication.get("current_target_activation")
            if isinstance(publication, Mapping)
            else None
        )
        if isinstance(activation, str) and activation.startswith("blocked_"):
            current_target = _blocked(activation)
        else:
            current_adapter = CURRENT_TARGET_ADAPTERS.get(strategy.model_version_id)
            current_target = (
                _available(current_adapter)
                if current_adapter is not None
                else _blocked(
                    f"blocked_pending_maintained_{strategy.model_version_id}_inference_adapter"
                )
            )

    return StrategyRuntimeCapabilities(
        strategy_id=strategy.strategy_id,
        model_version_id=strategy.model_version_id,
        formal_refresh=formal_refresh,
        current_target=current_target,
    )


def load_active_strategy_runtime_capabilities(
    *,
    repository_root: Path = Path("."),
    active: ActiveStrategyCatalog | None = None,
) -> dict[str, StrategyRuntimeCapabilities]:
    """Return one exact runtime capability record per active strategy."""

    root = repository_root.resolve()
    catalog = active or load_active_strategy_catalog(root / "configs/strategies/registry.json")
    return {
        strategy.strategy_id: resolve_strategy_runtime_capabilities(
            strategy,
            repository_root=root,
        )
        for strategy in catalog.strategies
    }
