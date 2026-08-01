"""Fail-closed resolver for authoritative selected-pool research."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")


@dataclass(frozen=True)
class SelectedPoolBinding:
    market: str
    pool_id: str
    pool_spec: Path
    registry_spec: Path
    authoritative_data_blockers: tuple[str, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML contract must be a mapping: {path}")
    return payload


def resolve_selected_pool(
    market: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    authoritative: bool = True,
    require_data_ready: bool = True,
) -> SelectedPoolBinding:
    """Resolve the selected pool or block an authoritative run."""

    normalized_market = str(market).strip().lower()
    registry_spec = Path(registry_path).resolve()
    registry = _load_yaml(registry_spec)
    policy = registry.get("policy", {})
    if authoritative and policy.get("new_experiments_must_use_selected_pool") is not True:
        raise ValueError("selected-pool registry does not enforce authoritative experiments")

    markets = registry.get("markets", {})
    market_config = markets.get(normalized_market)
    if not isinstance(market_config, dict):
        raise ValueError(f"market is not declared in selected-pool registry: {normalized_market}")
    if authoritative and market_config.get("new_authoritative_runs_allowed") is not True:
        status = market_config.get("status", "unknown")
        raise ValueError(
            f"authoritative {normalized_market} run blocked by selected-pool status: {status}"
        )

    blockers = tuple(
        str(value).strip()
        for value in market_config.get("authoritative_data_blockers", [])
        if str(value).strip()
    )
    if authoritative and require_data_ready and blockers:
        raise ValueError(
            f"authoritative {normalized_market} run blocked by data readiness: "
            + "; ".join(blockers)
        )

    pool_id = str(market_config.get("active_pool_id", "")).strip()
    pool_spec_value = str(market_config.get("pool_spec", "")).strip()
    if not pool_id or not pool_spec_value:
        raise ValueError(f"active selected pool is incomplete for market: {normalized_market}")
    pool_spec = Path(pool_spec_value).resolve()
    pool = _load_yaml(pool_spec)
    if pool.get("pool_id") != pool_id:
        raise ValueError(
            f"selected-pool identity mismatch: registry={pool_id}, file={pool.get('pool_id')}"
        )
    if pool.get("market") != normalized_market:
        raise ValueError("selected-pool market mismatch")
    if authoritative and pool.get("status") != "active_selected_pool":
        raise ValueError("authoritative run requires status=active_selected_pool")

    return SelectedPoolBinding(
        market=normalized_market,
        pool_id=pool_id,
        pool_spec=pool_spec,
        registry_spec=registry_spec,
        authoritative_data_blockers=blockers,
    )


def assert_pool_is_active_selected(
    pool_path: str | Path,
    *,
    market: str,
    registry_path: str | Path = DEFAULT_REGISTRY,
    require_data_ready: bool = True,
) -> SelectedPoolBinding:
    binding = resolve_selected_pool(
        market,
        registry_path=registry_path,
        authoritative=True,
        require_data_ready=require_data_ready,
    )
    supplied = Path(pool_path).resolve()
    if supplied != binding.pool_spec:
        raise ValueError(
            f"authoritative run attempted non-selected pool: {supplied}; expected {binding.pool_spec}"
        )
    return binding
