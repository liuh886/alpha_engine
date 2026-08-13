"""Resolve the latest calendar date that can contain a completed regular session."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MARKET_CLOCKS = {
    "us": (ZoneInfo("America/New_York"), time(16, 0)),
    "cn": (ZoneInfo("Asia/Shanghai"), time(15, 0)),
}


class MarketSessionClockError(ValueError):
    """Raised when a market/session cutoff cannot be resolved."""


def completed_market_date(
    market: str,
    requested_as_of: str,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Cap an as-of date so an in-progress regular session is never admitted.

    This function only resolves the calendar boundary. Provider sessions remain
    the authority for weekends and exchange holidays.
    """

    market_key = str(market).strip().lower()
    if market_key not in MARKET_CLOCKS:
        raise MarketSessionClockError(f"unsupported market clock: {market}")
    try:
        requested = date.fromisoformat(requested_as_of)
    except ValueError as exc:
        raise MarketSessionClockError(
            f"invalid requested_as_of date: {requested_as_of}"
        ) from exc

    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    zone, regular_close = MARKET_CLOCKS[market_key]
    local_now = current.astimezone(zone)
    local_today = local_now.date()
    latest_calendar_date = local_today
    if local_now.time().replace(tzinfo=None) < regular_close:
        latest_calendar_date -= timedelta(days=1)

    return min(requested, latest_calendar_date).isoformat()
