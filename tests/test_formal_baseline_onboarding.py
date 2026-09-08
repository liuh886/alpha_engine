from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import yaml

from src.governance.active_strategy_catalog import (
    ActiveStrategy,
    ActiveStrategyCatalogError,
    load_active_strategy_catalog,
)
from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import RUNNER_ID


EXPERIMENT_ROOT = Path("configs/research_experiments")
FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")


def _active_strategies():
    """Load the registry at test time, never at module import.

    A bad registry row must fail these tests with a clear message, not crash
    collection for the whole suite (2026-09-06 health-gate outage).
    """

    return load_active_strategy_catalog()


def _formal_model_ids() -> set[str]:
    payload = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    return {row["model_version_id"] for row in payload["records"]}


def pytest_generate_tests(metafunc) -> None:
    if "strategy" in metafunc.fixturenames:
        try:
            strategies: list = list(_active_strategies().strategies)
            ids = [strategy.strategy_id for strategy in strategies]
        except ActiveStrategyCatalogError:
            # A bad registry row must fail as clear per-test failures below,
            # never as a collection crash or an unapproved skip.
            strategies, ids = [None], ["registry-invalid"]
        metafunc.parametrize("strategy", strategies, ids=ids)


def test_registry_loads_for_onboarding() -> None:
    _active_strategies()


def test_completed_onboarding_specs_do_not_remain_in_live_config() -> None:
    stale: list[str] = []
    for path in sorted(EXPERIMENT_ROOT.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("runner") != RUNNER_ID:
            continue
        if payload.get("active") is not True:
            stale.append(path.as_posix())
    assert stale == []


def test_formal_catalog_matches_active_strategy_catalog() -> None:
    assert _formal_model_ids() == set(_active_strategies().active_model_version_ids)


def test_current_formal_catalog_bundle_is_hash_verified(
    strategy: ActiveStrategy | None,
) -> None:
    assert strategy is not None, (
        "strategy registry failed to load; see test_registry_loads_for_onboarding"
    )
    baseline = load_formal_baseline(
        strategy.model_version_id,
        expected_model_kind=strategy.model_kind,
        expected_model_family_id=strategy.model_family_id,
    )

    assert baseline.model_version_id == strategy.model_version_id
    assert baseline.model_family_id == strategy.model_family_id
    assert baseline.model_kind == strategy.model_kind
    assert baseline.market == strategy.market
    assert baseline.benchmark
    assert date.fromisoformat(baseline.evidence_cutoff).isoformat() == baseline.evidence_cutoff
    assert baseline.bundle_id
    assert baseline.manifest_sha256
    assert baseline.metrics
