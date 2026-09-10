"""Display-truth contracts: no highlights without an as-of context.

P0-1 (staleness): every operations record and every health market entry
carries a machine-readable staleness block so the console can never render
historical highlights as current state.
P0-2 (sealed drawdown): every active strategy's formal bundle exposes an
available sealed max_drawdown, so the console never needs to self-compute
drawdown (the #1112 divergence class).
"""

from __future__ import annotations

from pathlib import Path

from src.artifacts.strategy_operations import (
    _staleness,
    build_operations_payload,
    validate_operations_payload,
)
from src.artifacts.system_health import _trading_sessions_between

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")


def test_sessions_between_counts_weekdays_only() -> None:
    assert _trading_sessions_between("2026-09-04", "2026-09-04") == 0
    assert _trading_sessions_between("2026-09-04", "2026-09-07") == 1  # Fri->Mon
    assert _trading_sessions_between("2026-09-07", "2026-09-11") == 4
    assert _trading_sessions_between("2026-09-11", "2026-09-07") == 0


def test_fresh_record_is_not_stale() -> None:
    block = _staleness("2026-09-08", market="cn", generated_at="2026-09-08T20:00:00Z")
    assert block["as_of"] == "2026-09-08"
    assert block["stale"] is False
    assert block["sessions_behind"] == 0


def test_lagging_record_names_its_gap() -> None:
    block = _staleness("2026-08-24", market="us", generated_at="2026-09-09T01:00:00Z")
    assert block["stale"] is True
    assert block["expected_cutoff"] == "2026-09-08"
    assert block["sessions_behind"] == 11


def test_unknown_data_date_is_stale_by_default() -> None:
    for missing in (None, "", "not-a-date"):
        block = _staleness(missing, market="cn", generated_at="2026-09-08T00:00:00Z")
        assert block["stale"] is True
        assert block["sessions_behind"] is None


def test_unknown_market_is_stale_by_default() -> None:
    block = _staleness("2026-09-08", market="xx", generated_at="2026-09-08T00:00:00Z")
    assert block["stale"] is True


def test_every_operations_record_carries_staleness(tmp_path: Path) -> None:
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-09-09T00:00:00Z",
    )
    validate_operations_payload(payload)
    records = payload["records"]
    assert isinstance(records, list) and records
    for row in records:
        assert isinstance(row, dict)
        block = row.get("staleness")
        assert isinstance(block, dict), row.get("model_version_id")
        assert set(block) == {"as_of", "expected_cutoff", "sessions_behind", "stale"}
        assert isinstance(block["stale"], bool)
        if block["as_of"] is None:
            assert block["stale"] is True


def test_health_markets_carry_staleness(tmp_path: Path) -> None:
    import json

    from src.artifacts.system_health import build_system_health, validate_system_health

    operations = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-09-09T00:00:00Z",
    )
    freshness = Path("data/research/formal_model_runs/freshness.json")
    model_data = Path("data/research/model_data_bundle_v1/model-data-readiness.json")
    if not freshness.is_file() or not model_data.is_file():
        import pytest

        pytest.skip("formal freshness/model-data inputs absent from checkout")
    health = build_system_health(
        repository_root=Path("."),
        formal_catalog=FORMAL_CATALOG,
        formal_freshness=freshness,
        operations=operations,
        model_data_readiness=model_data,
        generated_at="2026-09-09T00:00:00Z",
    )
    validate_system_health(health)
    assert health["markets"]
    for market in health["markets"]:
        block = market.get("staleness")
        assert isinstance(block, dict), market.get("market")
        assert set(block) == {"as_of", "expected_cutoff", "sessions_behind", "stale"}


def test_every_active_strategy_has_sealed_max_drawdown() -> None:
    import json

    catalog = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    records = catalog.get("records")
    assert isinstance(records, list) and records
    for row in records:
        assert isinstance(row, dict)
        model_id = str(row.get("model_version_id"))
        manifest_path = Path("data/research/formal_model_runs") / str(
            row.get("manifest_path")
        )
        risk_path = manifest_path.parent / "risk.json"
        assert risk_path.is_file(), f"{model_id}: risk section missing"
        risk = json.loads(risk_path.read_text(encoding="utf-8"))
        metrics = risk.get("metrics")
        assert isinstance(metrics, list), f"{model_id}: risk metrics missing"
        drawdowns = [
            metric
            for metric in metrics
            if isinstance(metric, dict)
            and metric.get("metric_id") == "max_drawdown"
        ]
        assert len(drawdowns) == 1, f"{model_id}: max_drawdown not unique"
        metric = drawdowns[0]
        assert metric.get("availability_status") == "available", model_id
        value = metric.get("value")
        assert isinstance(value, (int, float)) and not isinstance(value, bool), model_id
        assert float(value) <= 0.0, model_id


def test_state_detail_truth_table() -> None:
    from src.artifacts.strategy_operations import _state_detail

    assert _state_detail("current_no_change", has_history=True, stale=False) == "current"
    assert _state_detail("target_pending_execution", has_history=True, stale=False) == "current"
    assert _state_detail("execution_observed", has_history=True, stale=False) == "current"
    assert _state_detail("current_no_change", has_history=True, stale=True) == "degraded_delayed"
    assert _state_detail("stale", has_history=True, stale=True) == "degraded_delayed"
    assert _state_detail("pipeline_unavailable", has_history=True, stale=True) == "degraded_blocked"
    assert _state_detail("awaiting_observation", has_history=True, stale=True) == "degraded_blocked"
    assert _state_detail("pipeline_unavailable", has_history=False, stale=True) == "blocked"
    assert _state_detail("blocked", has_history=True, stale=False) == "blocked"
    assert _state_detail("delivery_failed", has_history=True, stale=False) == "blocked"
    assert _state_detail("mystery", has_history=True, stale=False) == "blocked"


def test_every_operations_record_carries_closed_state_detail(tmp_path: Path) -> None:
    from src.artifacts.strategy_operations import STATE_DETAIL_VALUES

    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-09-09T00:00:00Z",
    )
    validate_operations_payload(payload)
    for row in payload["records"]:
        assert isinstance(row, dict)
        assert row.get("state_detail") in STATE_DETAIL_VALUES, row.get("model_version_id")
