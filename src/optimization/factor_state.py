"""Factor state definitions — validated vs proposed, no false claims.

Every factor has exactly one of these states:
- validated: passed all gates, ready for production use
- proposed: discovered but not yet validated
- retired: was active, now deprecated
- rejected: failed validation

Factors are never silently promoted. State transitions are explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FactorState(str, Enum):
    VALIDATED = "validated"     # Passed all validation gates
    PROPOSED = "proposed"       # Discovered, not yet validated
    RETIRED = "retired"         # Was active, now deprecated
    REJECTED = "rejected"       # Failed validation


@dataclass(frozen=True)
class FactorRecord:
    """Single factor with explicit state."""
    factor_id: str
    expression: str
    information_family: str
    state: FactorState
    markets: tuple[str, ...] = ("us", "cn")
    implementation_hash: str = ""

    @property
    def is_active(self) -> bool:
        return self.state == FactorState.VALIDATED

    @property
    def is_proposed(self) -> bool:
        return self.state == FactorState.PROPOSED

    def validate(self, implementation_hash: str) -> "FactorRecord":
        """Promote from proposed → validated (returns new instance)."""
        if self.state != FactorState.PROPOSED:
            raise ValueError(f"can only validate from PROPOSED state, got {self.state}")
        return FactorRecord(
            factor_id=self.factor_id, expression=self.expression,
            information_family=self.information_family, state=FactorState.VALIDATED,
            markets=self.markets, implementation_hash=implementation_hash,
        )

    def retire(self) -> "FactorRecord":
        if self.state not in (FactorState.VALIDATED, FactorState.PROPOSED):
            raise ValueError(f"can only retire from VALIDATED or PROPOSED, got {self.state}")
        return FactorRecord(
            factor_id=self.factor_id, expression=self.expression,
            information_family=self.information_family, state=FactorState.RETIRED,
            markets=self.markets, implementation_hash=self.implementation_hash,
        )


@dataclass
class FactorCatalog:
    """Ordered collection with state-aware queries."""

    records: list[FactorRecord] = field(default_factory=list)

    def add(self, record: FactorRecord) -> None:
        if any(r.factor_id == record.factor_id for r in self.records):
            raise ValueError(f"duplicate factor_id: {record.factor_id}")
        self.records.append(record)

    def validated(self, market: str | None = None) -> list[FactorRecord]:
        result = [r for r in self.records if r.state == FactorState.VALIDATED]
        if market:
            result = [r for r in result if market in r.markets]
        return result

    def proposed(self, market: str | None = None) -> list[FactorRecord]:
        result = [r for r in self.records if r.state == FactorState.PROPOSED]
        if market:
            result = [r for r in result if market in r.markets]
        return result

    def by_family(self, market: str | None = None) -> dict[str, list[FactorRecord]]:
        result: dict[str, list[FactorRecord]] = {}
        for r in self.records:
            if market and market not in r.markets:
                continue
            result.setdefault(r.information_family, []).append(r)
        return result

    @property
    def total_count(self) -> int:
        return len(self.records)

    @property
    def validated_count(self) -> int:
        return sum(1 for r in self.records if r.state == FactorState.VALIDATED)

    @property
    def proposed_count(self) -> int:
        return sum(1 for r in self.records if r.state == FactorState.PROPOSED)

    def state_summary(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(r.state.value for r in self.records))
