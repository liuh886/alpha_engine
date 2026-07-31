"""Read-only API for immutable shadow decision tickets."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.decision_support.decision_ledger_reader import DecisionLedgerReader

router = APIRouter(tags=["decision-desk"])


def _reader() -> DecisionLedgerReader:
    return DecisionLedgerReader()


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="decision ticket not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="decision ledger read failed")


@router.get("/decision-desk")
def get_decision_desk_overview():
    try:
        return {
            "ok": True,
            "research_only": True,
            "trade_ready": False,
            "markets": _reader().markets(),
        }
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/decision-desk/{market}/latest")
def get_latest_decision_ticket(market: str):
    try:
        ticket = _reader().latest(market)
        return {"ok": True, "ticket": ticket}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/decision-desk/{market}/history")
def get_decision_ticket_history(
    market: str,
    limit: int = Query(60, ge=1, le=365),
):
    try:
        rows = _reader().history(market, limit=limit)
        return {"ok": True, "market": market.lower(), "history": rows}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/decision-desk/{market}/{as_of_date}")
def get_decision_ticket(market: str, as_of_date: str):
    try:
        ticket = _reader().get_ticket(market, as_of_date)
        return {"ok": True, "ticket": ticket}
    except Exception as exc:
        raise _translate_error(exc) from exc
