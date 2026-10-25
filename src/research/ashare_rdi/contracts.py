"""Point-in-time event exposure skeleton; deliberately does not invent RDI weights."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

DIRECTIONS = frozenset({"risk", "clearing", "policy"})
SCOPES = frozenset({"market", "sector"})
STAGES = frozenset({"announced", "approved", "executed", "verified"})


@dataclass(frozen=True)
class RiskEvent:
    """One documented, versioned claim, not one article or one trading signal.

    Multiple reports about the same development must share story_id. Revisions
    have distinct event_id and availability time. available_at records the
    *later* of public disclosure and verified provider availability.
    """

    event_id: str
    story_id: str
    family: str
    direction: str
    scope: str
    sector_id: str | None
    stage: str
    announced_at: datetime
    available_at: datetime
    active_from: date
    active_until: date
    source_id: str
    source_hash: str

    def __post_init__(self) -> None:
        if not all(
            (self.event_id, self.story_id, self.family, self.source_id, self.source_hash)
        ):
            raise ValueError("event needs identifiers and source provenance")
        if self.direction not in DIRECTIONS or self.scope not in SCOPES:
            raise ValueError("unsupported direction or scope")
        if self.stage not in STAGES:
            raise ValueError("unsupported evidence stage")
        if (self.scope == "sector") != bool(self.sector_id):
            raise ValueError("sector-scoped event requires sector_id; market event forbids it")
        if self.announced_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("PIT timestamps must have timezone offsets")
        if self.available_at < self.announced_at:
            raise ValueError("available_at cannot precede disclosure")
        if self.active_from > self.active_until:
            raise ValueError("invalid effective window")


def event_exposure_timeline(
    events: Sequence[RiskEvent],
    *,
    as_of: datetime,
    future_sessions: Sequence[date],
    sector_id: str | None = None,
) -> list[dict[str, object]]:
    """Known-at-cutoff forward event calendar, with *no* fitted weights.

    Sessions must be genuine, strictly increasing CN exchange trading dates
    following the completed as_of session. This helper does not derive a
    calendar from weekdays. Unknown/missing evidence is not treated as zero
    by downstream inference; callers must separately assert coverage.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone aware")
    if not future_sessions or list(future_sessions) != sorted(set(future_sessions)):
        raise ValueError("future_sessions must be nonempty, ordered and unique")
    if future_sessions[0] <= as_of.date():
        raise ValueError("future_sessions must start after the as_of calendar date")

    # Latest *known* revision for each independent real-world story and family.
    # A later research ingestion cannot rewrite a prior observation.
    selected: dict[tuple[str, str, str, str | None], RiskEvent] = {}
    for event in events:
        if event.available_at > as_of:
            continue
        if event.scope == "sector" and event.sector_id != sector_id:
            continue
        key = (event.story_id, event.family, event.scope, event.sector_id)
        prior = selected.get(key)
        if prior is None or (event.available_at, event.event_id) > (
            prior.available_at,
            prior.event_id,
        ):
            selected[key] = event

    rows: list[dict[str, object]] = []
    for day in future_sessions:
        active = [e for e in selected.values() if e.active_from <= day <= e.active_until]
        counts = {direction: sum(e.direction == direction for e in active) for direction in DIRECTIONS}
        rows.append(
            {
                "session": day.isoformat(),
                "known_stories": len(active),
                "risk_stories": counts["risk"],
                "clearing_stories": counts["clearing"],
                "policy_stories": counts["policy"],
                "risk_families": sorted({e.family for e in active if e.direction == "risk"}),
                "clearing_families": sorted({e.family for e in active if e.direction == "clearing"}),
            }
        )
    return rows
