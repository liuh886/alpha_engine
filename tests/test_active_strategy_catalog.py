from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.governance.active_strategy_catalog import (
    ActiveStrategyCatalogError,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
    validate_active_strategy_catalog,
)

CATALOG = Path("configs/strategies/registry.json")
FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")


def test_committed_active_strategy_catalog_matches_formal_catalog() -> None:
    active = load_active_strategy_catalog(CATALOG)
    catalog = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))

    assert active.active_model_version_ids == (
        "qqqi_qqq_tqqq_v4_3",
        "us_x1_2",
        "cn_x1_1",
        "byd_v1_3_recovery_event_low_vol_confirmation_v1",
    )
    assert all(
        "current_operations_access" not in strategy
        for strategy in registry["strategies"]
    )
    assert_formal_catalog_matches_active_strategies(catalog, active)


def test_catalog_rejects_duplicate_active_model_identity() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["strategies"][1]["model_version_id"] = payload["strategies"][0][
        "model_version_id"
    ]
    payload["strategies"][1]["signal_ledger"] = payload["strategies"][0]["signal_ledger"]

    with pytest.raises(ActiveStrategyCatalogError, match="duplicate model_version_id"):
        validate_active_strategy_catalog(payload)


def test_catalog_rejects_signal_ledger_not_bound_to_active_model() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["strategies"][0]["signal_ledger"] = "data/research/strategy_signal_ledgers/old_model"

    with pytest.raises(ActiveStrategyCatalogError, match="terminate at active model id"):
        validate_active_strategy_catalog(payload)


def test_formal_catalog_fails_closed_when_active_model_is_missing() -> None:
    active = load_active_strategy_catalog(CATALOG)
    catalog = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    catalog["records"] = catalog["records"][:-1]

    with pytest.raises(ActiveStrategyCatalogError, match="formal catalog/active strategy mismatch"):
        assert_formal_catalog_matches_active_strategies(catalog, active)
