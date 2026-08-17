from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.strategy_operations import (
    _transition_predecessor_strategies,
    build_operations_payload,
)
from src.artifacts.system_health import (
    SystemHealthError,
    build_system_health,
    validate_system_health,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
FORMAL_FRESHNESS = Path("data/research/formal_model_runs/freshness.json")
MODEL_DATA = Path("data/research/model_data_bundle_v1/model-data-readiness.json")


def _operations() -> dict[str, object]:
    return build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=Path("data/research/strategy_signal_ledgers"),
        generated_at="2026-08-13T09:30:00Z",
    )


def _health(*, freshness: Path = FORMAL_FRESHNESS) -> dict[str, object]:
    return build_system_health(
        repository_root=Path.cwd(),
        formal_catalog=FORMAL_CATALOG,
        formal_freshness=freshness,
        operations=_operations(),
        model_data_readiness=MODEL_DATA,
        generated_at="2026-08-13T09:30:00Z",
    )


def test_system_health_matches_active_or_declared_transition_strategy_set() -> None:
    payload = _health()
    validate_system_health(payload)
    active = load_active_strategy_catalog()
    observed = {row["model_version_id"] for row in payload["strategies"]}
    expected = set(active.active_model_version_ids)
    if observed != expected:
        formal = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
        transition = _transition_predecessor_strategies(
            formal,
            active=active,
            strategy_catalog=Path("configs/strategies/registry.json"),
        )
        assert observed == set(transition)
    assert {row["market"] for row in payload["markets"]} == {"us", "cn"}
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    for row in payload["strategies"]:
        assert set(row["stages"]) == {
            "provider",
            "formal",
            "model_data",
            "factor",
            "signal",
            "delivery",
        }
        assert row["formal_bundle_id"]
        assert row["formal_run_id"]


def test_provider_lag_is_delayed_not_formal_corruption(tmp_path: Path) -> None:
    freshness = json.loads(FORMAL_FRESHNESS.read_text(encoding="utf-8"))
    freshness["markets"]["us"] = "2026-01-02"
    path = tmp_path / "freshness.json"
    path.write_text(json.dumps(freshness), encoding="utf-8")

    payload = _health(freshness=path)
    us = next(row for row in payload["markets"] if row["market"] == "us")
    assert us["state"] == "delayed"
    assert us["provider_formal_consistency"] == "current"
    assert us["provider_lag_sessions"] is None
    assert us["provider_lag_exact"] is False


def test_delivery_failure_degrades_strategy_health() -> None:
    operations = _operations()
    row = next(
        item
        for item in operations["records"]
        if item["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    )
    row["delivery_status"] = "failed"
    row["status"] = "current_no_change"
    payload = build_system_health(
        repository_root=Path.cwd(),
        formal_catalog=FORMAL_CATALOG,
        formal_freshness=FORMAL_FRESHNESS,
        operations=operations,
        model_data_readiness=MODEL_DATA,
        generated_at="2026-08-13T09:30:00Z",
    )
    qqq = next(
        item
        for item in payload["strategies"]
        if item["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    )
    assert qqq["stages"]["delivery"] == "blocked"
    assert qqq["state"] == "blocked"


def test_system_health_fails_closed_on_partial_operations_set() -> None:
    operations = _operations()
    operations["records"] = operations["records"][:-1]
    with pytest.raises(SystemHealthError, match="exactly match"):
        build_system_health(
            repository_root=Path.cwd(),
            formal_catalog=FORMAL_CATALOG,
            formal_freshness=FORMAL_FRESHNESS,
            operations=operations,
            model_data_readiness=MODEL_DATA,
            generated_at="2026-08-13T09:30:00Z",
        )
