"""Read and verify immutable shadow-decision ledger tickets."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Mapping

ALLOWED_MARKETS = {"us", "cn"}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read decision ledger file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"decision ledger file must contain an object: {path}")
    return payload


def default_ledger_root() -> Path:
    configured = os.environ.get("ALPHA_DECISION_LEDGER_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "artifacts" / "decision_ledger"


class DecisionLedgerReader:
    """Fail-closed reader for the research-only decision ledger."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = default_ledger_root() if root is None else Path(root).resolve()

    @staticmethod
    def _validate_market(market: str) -> str:
        normalized = market.lower().strip()
        if normalized not in ALLOWED_MARKETS:
            raise ValueError(f"unsupported market: {market}")
        return normalized

    def _market_dir(self, market: str) -> Path:
        return self.root / self._validate_market(market)

    def _manifest(self, market: str) -> dict[str, Any]:
        path = self._market_dir(market) / "ledger_manifest.json"
        if not path.exists():
            return {
                "schema_version": "1.0",
                "market": market,
                "research_only": True,
                "trade_ready": False,
                "ticket_count": 0,
                "tickets": [],
            }
        payload = _load_json(path)
        if payload.get("market") != market:
            raise ValueError("ledger manifest market mismatch")
        if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
            raise ValueError("ledger manifest violates research-only truth boundary")
        tickets = payload.get("tickets")
        if not isinstance(tickets, list):
            raise ValueError("ledger manifest tickets must be a list")
        return payload

    @staticmethod
    def _validate_ticket(ticket: Mapping[str, Any], *, market: str, as_of_date: str) -> None:
        if ticket.get("market") != market:
            raise ValueError("ticket market mismatch")
        if ticket.get("as_of_date") != as_of_date:
            raise ValueError("ticket date mismatch")
        date.fromisoformat(as_of_date)
        if ticket.get("research_only") is not True:
            raise ValueError("ticket must be research_only")
        if ticket.get("trade_ready") is not False:
            raise ValueError("ticket claiming trade readiness is not readable")
        if ticket.get("automatic_order_routing") is not False:
            raise ValueError("ticket must disable automatic order routing")
        if ticket.get("mode") != "diagnostic_only":
            raise ValueError("ticket mode must remain diagnostic_only")
        identity = ticket.get("ticket_identity_sha256")
        if not isinstance(identity, str) or len(identity) != 64:
            raise ValueError("ticket identity is missing or malformed")

    def get_ticket(self, market: str, as_of_date: str) -> dict[str, Any]:
        normalized = self._validate_market(market)
        parsed = date.fromisoformat(as_of_date)
        canonical_date = parsed.isoformat()
        path = self._market_dir(normalized) / f"{canonical_date}.json"
        if not path.exists():
            raise FileNotFoundError(path)

        ticket = _load_json(path)
        self._validate_ticket(ticket, market=normalized, as_of_date=canonical_date)

        manifest = self._manifest(normalized)
        entries = {
            str(row.get("as_of_date")): row
            for row in manifest.get("tickets", [])
            if isinstance(row, dict)
        }
        manifest_entry = entries.get(canonical_date)
        if manifest_entry is None:
            raise ValueError("ticket is absent from the ledger manifest")
        if manifest_entry.get("ticket_identity_sha256") != ticket["ticket_identity_sha256"]:
            raise ValueError("ticket identity differs from the ledger manifest")
        expected_hash = manifest_entry.get("file_sha256")
        if expected_hash != _sha256_file(path):
            raise ValueError("ticket file hash differs from the ledger manifest")
        return ticket

    @staticmethod
    def summarize_ticket(ticket: Mapping[str, Any]) -> dict[str, Any]:
        actions: dict[str, int] = {}
        for row in ticket.get("securities", []):
            if not isinstance(row, dict):
                continue
            action = str(row.get("action", "UNKNOWN"))
            actions[action] = actions.get(action, 0) + 1
        market_context = ticket.get("market_context", {})
        turnover = ticket.get("turnover_budget", {})
        return {
            "market": ticket.get("market"),
            "as_of_date": ticket.get("as_of_date"),
            "actionable_from": ticket.get("actionable_from"),
            "ticket_identity_sha256": ticket.get("ticket_identity_sha256"),
            "mode": ticket.get("mode"),
            "trade_ready": False,
            "market_regime": market_context.get("market_regime"),
            "risk_on": market_context.get("risk_on"),
            "gross_exposure": market_context.get("gross_exposure"),
            "cash_weight": market_context.get("cash_weight"),
            "selected_baskets": market_context.get("selected_baskets", []),
            "ticket_turnover": turnover.get("ticket_turnover"),
            "turnover_remaining": turnover.get("remaining"),
            "within_turnover_budget": turnover.get("within_budget"),
            "security_count": len(ticket.get("securities", [])),
            "action_counts": actions,
            "warning_count": len(ticket.get("warnings", [])),
        }

    def history(self, market: str, *, limit: int = 60) -> list[dict[str, Any]]:
        normalized = self._validate_market(market)
        bounded_limit = max(1, min(int(limit), 365))
        manifest = self._manifest(normalized)
        dates = sorted(
            {
                str(row.get("as_of_date"))
                for row in manifest.get("tickets", [])
                if isinstance(row, dict) and row.get("as_of_date")
            },
            reverse=True,
        )
        return [
            self.summarize_ticket(self.get_ticket(normalized, as_of_date))
            for as_of_date in dates[:bounded_limit]
        ]

    def latest(self, market: str) -> dict[str, Any]:
        history = self.history(market, limit=1)
        if not history:
            raise FileNotFoundError(self._market_dir(market))
        return self.get_ticket(market, str(history[0]["as_of_date"]))

    def markets(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for market in sorted(ALLOWED_MARKETS):
            history = self.history(market, limit=1)
            latest = history[0] if history else None
            manifest = self._manifest(market)
            rows.append(
                {
                    "market": market,
                    "available": latest is not None,
                    "ticket_count": int(manifest.get("ticket_count", len(manifest.get("tickets", [])))),
                    "latest": latest,
                }
            )
        return rows
