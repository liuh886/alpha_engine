"""Reference instruments consumed by publication paths must carry roles.

CGDV historically drifted into the price-refresh comparison list, the
formal provider cache and the console preset without any registry
identity (market-evidence recorded ``roles: []``). These gates pin every
hardcoded consumption list to the governed reference registry and fail
on roleless drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.common.runtime_settings import PROJECT_ROOT

REGISTRY = PROJECT_ROOT / "configs/pools/reference_instrument_registry_v1.yaml"


def _registry() -> dict:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _us_instruments() -> dict:
    instruments = _registry()["markets"]["us"]["instruments"]
    assert isinstance(instruments, dict) and instruments
    return instruments


def test_cgdv_has_declared_comparison_reference_role() -> None:
    entry = _us_instruments().get("CGDV")
    assert isinstance(entry, dict), "CGDV must be a governed reference instrument"
    assert "comparison_reference" in entry["roles"]
    assert entry["candidate_eligible"] is False
    assert entry["portfolio_eligible_by_default"] is False


def _roles_for(symbol: str, instruments: dict) -> list[str]:
    entry = instruments.get(symbol)
    assert isinstance(entry, dict), f"{symbol} missing from reference registry"
    roles = entry.get("roles")
    assert isinstance(roles, list) and roles, f"{symbol} is roleless in registry"
    return roles


def test_refresh_comparison_references_are_governed() -> None:
    script = (
        PROJECT_ROOT / "scripts/data/refresh_selected_pool_prices_v2.py"
    ).read_text(encoding="utf-8")
    match = pytest.importorskip("re").search(
        r'"us":\s*\(([^)]*)\)', script
    )
    assert match, "refresh script comparison-reference tuple not found"
    symbols = {
        piece.strip().strip('"\'')
        for piece in match.group(1).split(",")
        if piece.strip().strip('"\'')
    }
    instruments = _us_instruments()
    for symbol in symbols:
        # Governance gate: any hardcoded consumption must resolve to a
        # registered instrument with at least one declared role.
        _roles_for(symbol, instruments)


def test_provider_cache_auxiliaries_are_governed() -> None:
    source = (
        PROJECT_ROOT / "src/artifacts/formal_provider_cache.py"
    ).read_text(encoding="utf-8")
    import re

    match = re.search(r'"us":\s*\(([^)]*)\)', source)
    assert match, "provider cache us auxiliary tuple not found"
    symbols = {
        piece.strip().strip('"\'')
        for piece in match.group(1).split(",")
        if piece.strip().strip('"\'')
    }
    instruments = _us_instruments()
    for symbol in symbols:
        _roles_for(symbol, instruments)
