"""Forward outcomes for descriptive risk-factor validation, not trade execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class PriceBar:
    session: date
    open: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if not all(isfinite(v) and v > 0 for v in (self.open, self.low, self.close)):
            raise ValueError("prices must be finite positive values")
        if self.low > min(self.open, self.close):
            raise ValueError("low exceeds open or close")


def forward_outcomes(
    bars: Sequence[PriceBar],
    *,
    decision_session: date,
    horizons: tuple[int, ...] = (7, 14, 28),
    instrument_kind: str = "index",
) -> list[dict[str, object]]:
    """Evaluate a close-of-t observation on distinct future trading sessions.

    index: hypothetical close(t)->close(t+h) *direction* label; not executable.
    etf: next-session open(t+1)->close(t+h), inclusive h-session horizon;
    prices must be a consistent distribution/split-adjusted total-return basis.
    Both labels use only realized bars, never forward-filled missing sessions.
    """
    if instrument_kind not in {"index", "etf"}:
        raise ValueError("instrument_kind must be index or etf")
    if not horizons or any(h <= 0 for h in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError("horizons must be distinct positive trading-session counts")
    sessions = [b.session for b in bars]
    if sessions != sorted(set(sessions)):
        raise ValueError("bars must be strictly increasing unique sessions")
    try:
        idx = sessions.index(decision_session)
    except ValueError as exc:
        raise ValueError("decision_session has no observed price bar") from exc
    result: list[dict[str, object]] = []
    for horizon in horizons:
        end_idx = idx + horizon
        if end_idx >= len(bars):
            # Keep insufficient tail observations explicit; never shorten a label.
            result.append({"horizon_sessions": horizon, "status": "insufficient_future_bars"})
            continue
        entry = bars[idx].close if instrument_kind == "index" else bars[idx + 1].open
        path = bars[idx + 1 : end_idx + 1]
        result.append(
            {
                "horizon_sessions": horizon,
                "status": "observed",
                "entry_session": (
                    bars[idx].session.isoformat()
                    if instrument_kind == "index"
                    else bars[idx + 1].session.isoformat()
                ),
                "exit_session": bars[end_idx].session.isoformat(),
                "forward_return": bars[end_idx].close / entry - 1.0,
                "worst_intrahorizon_return": min(b.low for b in path) / entry - 1.0,
                "instrument_kind": instrument_kind,
            }
        )
    return result
