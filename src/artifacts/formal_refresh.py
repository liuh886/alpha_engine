"""Shared support for formal Bundle v2 refresh transactions.

The transaction planner owns plan and receipt schemas, while versioned strategy
Adapters own model-specific refresh implementations. This Module keeps the
small shared Interface for canonical JSON I/O, digests, governed market clocks,
and bounded refresh deadlines.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class FormalRefreshError(ValueError):
    """Raised when refresh evidence violates the publication contract."""


def load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalRefreshError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalRefreshError(f"JSON root must be an object: {path}")
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise FormalRefreshError(f"unsupported JSON value: {type(value)!r}")


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_object(path: Path, payload: Mapping[str, Any]) -> str:
    encoded = _canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _date(value: object, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise FormalRefreshError(f"invalid {label}: {value!r}") from exc


_MARKET_CLOCK_SYMBOLS = {"us": "QQQ", "cn": "000300"}


def market_provider_cutoff(manifest: Mapping[str, Any], *, market: str) -> str:
    """Return the governed market-session watermark from its benchmark clock.

    Per-symbol coverage remains quality evidence for the model that consumes the
    symbol. A lagging stock must never rewind the market clock for every active
    strategy in that market.
    """

    if manifest.get("market") != market:
        raise FormalRefreshError(f"provider manifest market mismatch: expected {market}")
    if manifest.get("status") != "selected_pool_price_refresh_ready":
        raise FormalRefreshError(f"{market} provider refresh is not ready")
    if manifest.get("promotion_eligible") is not True:
        raise FormalRefreshError(f"{market} provider refresh is not promotion eligible")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise FormalRefreshError(f"{market} provider refresh boundary is invalid")
    rows = manifest.get("records")
    if not isinstance(rows, list) or not rows:
        raise FormalRefreshError(f"{market} provider records are missing")

    clock_symbol = _MARKET_CLOCK_SYMBOLS.get(market)
    if clock_symbol is None:
        raise FormalRefreshError(f"unsupported market clock: {market}")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("symbol") or "").strip().upper() == clock_symbol
    ]
    if len(matches) != 1:
        raise FormalRefreshError(
            f"{market} provider must contain exactly one market clock {clock_symbol}"
        )
    last_date = matches[0].get("last_date")
    if last_date is None:
        raise FormalRefreshError(f"{market} market clock {clock_symbol} lacks last_date")
    return _date(last_date, label=f"{market} market clock last_date").isoformat()


def next_weekday_refresh_deadline(cutoff: str, *, market: str) -> str:
    """Return the next bounded refresh check after a published market session.

    This is an operational deadline, not a claim that the following weekday is
    necessarily an exchange session. The live refresh resolver remains the
    source of truth and naturally no-ops on holidays.
    """

    day = _date(cutoff, label=f"{market} cutoff") + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    hour = 8 if market == "cn" else 23
    return datetime(
        day.year,
        day.month,
        day.day,
        hour,
        30,
        tzinfo=timezone.utc,
    ).isoformat()
