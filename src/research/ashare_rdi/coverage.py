"""Audit completeness separately from the *number* of observed market events.

A historic empty query is not a verified zero. Only independent, archived source
coverage can make an event-family/day observation eligible for research.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

ALLOWED_STATES = frozenset({"verified", "partial", "unknown", "provider_failed"})


@dataclass(frozen=True)
class FamilyCoverage:
    session: date
    family: str
    state: str
    source_id: str
    source_sha256: str
    point_in_time_archive_verified: bool

    def __post_init__(self) -> None:
        if not self.family or not self.source_id:
            raise ValueError("coverage family and source_id are required")
        if self.state not in ALLOWED_STATES:
            raise ValueError("unsupported coverage state")
        if self.point_in_time_archive_verified and (
            self.state != "verified"
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("verified PIT archive requires verified state and SHA-256")


def audit_coverage(
    rows: Iterable[FamilyCoverage],
    sessions: Sequence[date],
    families: Sequence[str],
) -> dict[str, object]:
    """Return missing/partial/unverified cells; never interpolate unobserved days."""
    expected = {(day, family) for day in sessions for family in families}
    if not families or not sessions:
        raise ValueError("coverage audit requires nonempty sessions and families")
    if len(set(sessions)) != len(sessions) or len(set(families)) != len(families):
        raise ValueError("duplicate session or family in coverage audit")
    index: dict[tuple[date, str], FamilyCoverage] = {}
    for row in rows:
        key = (row.session, row.family)
        if key in index:
            raise ValueError(f"duplicate coverage cell: {key}")
        if key in expected:
            index[key] = row
    missing = sorted(expected - set(index))
    not_verified = sorted(
        key for key, record in index.items()
        if record.state != "verified" or not record.point_in_time_archive_verified
    )
    usable = expected - set(missing) - set(not_verified)
    return {
        "status": "ready" if len(usable) == len(expected) else "blocked_incomplete_event_history",
        "expected_cells": len(expected),
        "usable_cells": len(usable),
        "unverified_cells": len(not_verified),
        "missing_cells": len(missing),
        "coverage_ratio": len(usable) / len(expected),
        "missing": [{"session": d.isoformat(), "family": f} for d, f in missing],
        "unverified": [
            {"session": d.isoformat(), "family": f, "state": index[d, f].state}
            for d, f in not_verified
        ],
    }


def coverage_cells_ready(
    index: Mapping[tuple[date, str], FamilyCoverage],
    session: date,
    required_families: Sequence[str],
) -> bool:
    """Only fully verified historical source coverage permits true zero counts."""
    return all(
        (row := index.get((session, family))) is not None
        and row.state == "verified"
        and row.point_in_time_archive_verified
        for family in required_families
    )
