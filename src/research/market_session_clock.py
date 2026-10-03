"""Resolve the latest calendar date that can contain a completed regular session."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MARKET_CLOCKS = {
    "us": (ZoneInfo("America/New_York"), time(16, 0)),
    "cn": (ZoneInfo("Asia/Shanghai"), time(15, 0)),
}
EXCHANGE_CALENDAR_IDS = {"us": "XNYS", "cn": "XSHG"}


class MarketSessionClockError(ValueError):
    """Raised when a market/session cutoff cannot be resolved."""


def exchange_sessions(market: str, start: str, end: str) -> list[str]:
    """Return exchange sessions, without treating a weekday as an observed bar.

    The locked exchange calendar supplies scheduling only. Provider coverage
    and completed-session guards must still pass before data can be admitted.
    Unsupported calendar ranges fail closed rather than inventing weekdays.
    """
    import exchange_calendars as xcals

    calendar_id = EXCHANGE_CALENDAR_IDS.get(market)
    if calendar_id is None:
        raise MarketSessionClockError(f"unsupported market clock: {market}")
    try:
        sessions = xcals.get_calendar(calendar_id).sessions_in_range(start, end)
    except Exception as exc:
        raise MarketSessionClockError(
            f"cannot resolve {calendar_id} sessions from {start} through {end}: {exc}"
        ) from exc
    return [session.date().isoformat() for session in sessions]


def completed_market_date(
    market: str,
    requested_as_of: str,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Cap an as-of date so an in-progress regular session is never admitted.

    Weekends are excluded here because provider promotion requires every active
    symbol to reach the requested cutoff. Provider sessions remain the
    authority for exchange-specific holidays.
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

    completed = min(requested, latest_calendar_date)
    while completed.weekday() >= 5:
        completed -= timedelta(days=1)
    return completed.isoformat()
