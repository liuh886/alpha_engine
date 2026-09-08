from __future__ import annotations

import json
import re
from pathlib import Path

REGISTRY = Path("configs/strategies/registry.json")
MIGRATIONS = Path("supabase/migrations")
ALLOWED_TIERS = {"public", "authenticated", "pro", "owner"}
ROW_RE = re.compile(
    r"\('alpha_engine'\s*,\s*'strategy'\s*,\s*'([^']+)'\s*,\s*'([^']+)'"
)


def _declared_strategy_tiers() -> dict[str, str]:
    declared: dict[str, str] = {}
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        for strategy_id, tier in ROW_RE.findall(
            migration.read_text(encoding="utf-8")
        ):
            declared[strategy_id] = tier
    return declared


def test_every_registry_strategy_has_runtime_access_policy() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    strategy_ids = [s["strategy_id"] for s in registry["strategies"]]
    assert strategy_ids, "strategy registry must declare at least one strategy"

    declared = _declared_strategy_tiers()
    missing = [s for s in strategy_ids if s not in declared]
    assert not missing, (
        f"runtime access policy missing for: {missing} "
        "(alpha ops publish fails closed with HTTP 400)"
    )


def test_runtime_access_policy_tiers_are_known() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    strategy_ids = [s["strategy_id"] for s in registry["strategies"]]
    declared = _declared_strategy_tiers()
    bad_tiers = {
        s: declared[s]
        for s in strategy_ids
        if s in declared and declared[s] not in ALLOWED_TIERS
    }
    assert not bad_tiers, f"unknown required_tier: {bad_tiers}"
