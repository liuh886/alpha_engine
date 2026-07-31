from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.decision_support.decision_ledger_reader import DecisionLedgerReader


def _write_ticket(root: Path, market: str, as_of_date: str, *, action: str = "WATCH") -> Path:
    market_dir = root / market
    market_dir.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(f"{market}:{as_of_date}".encode()).hexdigest()
    ticket = {
        "schema_version": "1.0",
        "ticket_identity_sha256": identity,
        "generated_at": f"{as_of_date}T22:00:00+00:00",
        "market": market,
        "as_of_date": as_of_date,
        "actionable_from": as_of_date,
        "mode": "diagnostic_only",
        "research_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "performance_evaluated": False,
        "market_context": {
            "benchmark": "QQQ" if market == "us" else "000300.SH",
            "risk_on": True,
            "market_regime": "risk_on",
            "selected_baskets": ["semiconductors"],
            "gross_exposure": 0.5,
            "cash_weight": 0.5,
        },
        "baskets": [],
        "securities": [
            {
                "symbol": "TEST",
                "basket": "semiconductors",
                "state": "WATCH",
                "action": action,
                "target_weight": 0.0,
                "previous_weight": 0.0,
            }
        ],
        "turnover_budget": {
            "ticket_turnover": 0.1,
            "remaining": 3.9,
            "within_budget": True,
        },
        "warnings": [],
    }
    path = market_dir / f"{as_of_date}.json"
    path.write_text(json.dumps(ticket, sort_keys=True), encoding="utf-8")
    return path


def _write_manifest(root: Path, market: str, ticket_paths: list[Path]) -> None:
    entries = []
    for path in ticket_paths:
        ticket = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            {
                "as_of_date": ticket["as_of_date"],
                "ticket_identity_sha256": ticket["ticket_identity_sha256"],
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "filename": path.name,
            }
        )
    payload = {
        "schema_version": "1.0",
        "market": market,
        "research_only": True,
        "trade_ready": False,
        "ticket_count": len(entries),
        "tickets": entries,
    }
    (root / market / "ledger_manifest.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )


def test_latest_history_and_market_overview(tmp_path: Path) -> None:
    first = _write_ticket(tmp_path, "us", "2026-07-30")
    second = _write_ticket(tmp_path, "us", "2026-07-31", action="ENTER_CANDIDATE")
    _write_manifest(tmp_path, "us", [first, second])

    reader = DecisionLedgerReader(tmp_path)
    latest = reader.latest("us")
    history = reader.history("us", limit=10)
    markets = {row["market"]: row for row in reader.markets()}

    assert latest["as_of_date"] == "2026-07-31"
    assert history[0]["action_counts"] == {"ENTER_CANDIDATE": 1}
    assert history[1]["as_of_date"] == "2026-07-30"
    assert markets["us"]["available"] is True
    assert markets["us"]["ticket_count"] == 2
    assert markets["cn"]["available"] is False


def test_tampered_ticket_fails_closed(tmp_path: Path) -> None:
    path = _write_ticket(tmp_path, "us", "2026-07-31")
    _write_manifest(tmp_path, "us", [path])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["warnings"] = ["TAMPERED"]
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="file hash"):
        DecisionLedgerReader(tmp_path).get_ticket("us", "2026-07-31")


def test_trade_ready_ticket_is_rejected(tmp_path: Path) -> None:
    path = _write_ticket(tmp_path, "us", "2026-07-31")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trade_ready"] = True
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _write_manifest(tmp_path, "us", [path])

    with pytest.raises(ValueError, match="trade readiness"):
        DecisionLedgerReader(tmp_path).get_ticket("us", "2026-07-31")


def test_invalid_market_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported market"):
        DecisionLedgerReader(tmp_path).history("../secrets")
