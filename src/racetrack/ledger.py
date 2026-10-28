"""Racetrack sparse holdings event ledger Q(t, s) with cryptographic hash-chaining.

Enforces ADR-0004 personal privacy boundary, genesis block initialization with
64 zeros, recursive canonical hash-chain continuity, and dense panel expansion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pandas as pd

from src.racetrack.contracts import (
    ChronologyOrderError,
    DuplicateSessionError,
    LedgerOverwriteError,
    LedgerTamperedError,
    PrivacyViolationError,
    RebalanceEvent,
    WeightConstraintError,
    assert_privacy_clean,
)

GENESIS_PARENT_HASH = "0" * 64


class EventLedger:
    """Manages the sparse event-stream ledger Q(t, s) stored as hash-chained JSONL."""

    def __init__(
        self,
        path: Path,
        runner_id: str,
        runner_version: str,
        events: list[RebalanceEvent] | None = None,
    ) -> None:
        self.path = Path(path)
        self.runner_id = runner_id
        self.runner_version = runner_version
        self._events: list[RebalanceEvent] = events or []

    @property
    def events(self) -> list[RebalanceEvent]:
        """Return a copy of all rebalance events in chronological order."""
        return list(self._events)

    @staticmethod
    def validate_events(
        events: Sequence[RebalanceEvent], runner_id: str, runner_version: str
    ) -> None:
        """Validate an in-memory stream before simulation or any filesystem write."""
        parent = GENESIS_PARENT_HASH
        previous_session = None
        for event in events:
            # Reconstruct to detect mutations of dictionaries inside frozen events.
            RebalanceEvent.from_dict(event.to_dict())
            if (event.runner_id, event.runner_version) != (runner_id, runner_version):
                raise LedgerTamperedError("Event runner/version does not match the ledger contract")
            if event.parent_hash != parent:
                raise LedgerTamperedError("Broken event parent hash chain")
            if previous_session == event.effective_session:
                raise DuplicateSessionError("Duplicate event session")
            if previous_session and event.effective_session < previous_session:
                raise ChronologyOrderError("Out-of-order event session")
            parent = event.event_hash
            previous_session = event.effective_session

    @property
    def tip_hash(self) -> str:
        """Hash of the latest event in the chain, or genesis parent hash if empty."""
        if not self._events:
            return GENESIS_PARENT_HASH
        return self._events[-1].event_hash

    @classmethod
    def create(
        cls,
        path: Path,
        runner_id: str,
        runner_version: str,
        overwrite: bool = False,
    ) -> "EventLedger":
        """Create a new EventLedger tied to a JSONL file path.

        Args:
            path: Target JSONL file path.
            runner_id: Unique runner / strategy identifier.
            runner_version: Strategy version string.
            overwrite: If True, overwrite existing file; if False, raise LedgerOverwriteError if file exists.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with p.open("w" if overwrite else "x", encoding="utf-8"):
                pass
        except FileExistsError as exc:
            raise LedgerOverwriteError(
                f"Ledger file already exists at '{p}'. Set overwrite=True to overwrite, or use EventLedger.load()."
            ) from exc
        return cls(p, runner_id, runner_version, events=[])

    @classmethod
    def load(cls, path: Path) -> "EventLedger":
        """Load and verify an existing JSONL ledger from disk."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Ledger file not found at {p}")

        events: list[RebalanceEvent] = []
        with open(p, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerTamperedError(
                        f"Corrupt JSON at line {line_no} in {p}: {exc}"
                    ) from exc

                assert_privacy_clean(data)
                try:
                    ev = RebalanceEvent.from_dict(data)
                except (WeightConstraintError, PrivacyViolationError) as exc:
                    raise LedgerTamperedError(
                        f"Tampered event payload at line {line_no} in {p}: {exc}"
                    ) from exc
                events.append(ev)

        if not events:
            # Empty file
            return cls(p, runner_id="", runner_version="", events=[])

        # Verify strict monotonic session order
        prev_sess: str | None = None
        for ev in events:
            if prev_sess is not None:
                if ev.effective_session == prev_sess:
                    raise LedgerTamperedError(
                        f"Duplicate effective_session '{ev.effective_session}' in ledger {p}"
                    )
                if ev.effective_session < prev_sess:
                    raise LedgerTamperedError(
                        f"Out-of-order session '{ev.effective_session}' < '{prev_sess}' in ledger {p}"
                    )
            prev_sess = ev.effective_session

        runner_id = events[0].runner_id
        runner_version = events[0].runner_version

        ledger = cls(p, runner_id, runner_version, events)
        ledger.verify()
        return ledger

    def append(
        self,
        effective_session: str,
        target_weights: dict[str, float],
        reason: str,
        timestamp_utc: str | None = None,
        event_id: str | None = None,
    ) -> RebalanceEvent:
        """Append a new rebalance event to the hash chain and disk JSONL.

        Args:
            effective_session: Date string (YYYY-MM-DD) when weights become effective.
            target_weights: Mapping of symbol -> target portfolio fraction.
            reason: Human-readable rationale for the rebalance.
            timestamp_utc: Optional ISO timestamp (defaults to current UTC time).
            event_id: Optional UUIDv4 string (defaults to random UUID).

        Returns:
            The created, validated RebalanceEvent.

        Raises:
            DuplicateSessionError: If effective_session matches the latest event.
            ChronologyOrderError: If effective_session is earlier than the latest event.
        """
        if self._events:
            last_sess = self._events[-1].effective_session
            if effective_session == last_sess:
                raise DuplicateSessionError(
                    f"Cannot append event with duplicate effective_session '{effective_session}'"
                )
            if effective_session < last_sess:
                raise ChronologyOrderError(
                    f"Cannot append event with out-of-order session '{effective_session}' (previous was '{last_sess}')"
                )

        parent_hash = self.tip_hash
        event = RebalanceEvent.create(
            parent_hash=parent_hash,
            effective_session=effective_session,
            runner_id=self.runner_id,
            runner_version=self.runner_version,
            target_weights=target_weights,
            reason=reason,
            event_id=event_id,
            timestamp_utc=timestamp_utc,
        )

        # Write to JSONL
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")

        self._events.append(event)
        return event

    def verify(self) -> bool:
        """Verify that the ledger's hash chain is unbroken and free of tampering.

        Checks:
            1. First event parent_hash == '0' * 64.
            2. For each event k > 0, event[k].parent_hash == event[k-1].event_hash.
            3. Each event's event_hash matches its re-computed canonical hash.
            4. Zero personal account sensitive fields present.

        Raises:
            LedgerTamperedError: If hash mismatch or broken chain is detected.
        """
        if not self.path.exists():
            return True

        file_events: list[RebalanceEvent] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerTamperedError(
                        f"Corrupt JSON at line {line_no} in {self.path}: {exc}"
                    ) from exc

                assert_privacy_clean(data)
                try:
                    ev = RebalanceEvent.from_dict(data)
                except (WeightConstraintError, PrivacyViolationError) as exc:
                    raise LedgerTamperedError(
                        f"Tampered event payload at line {line_no} in {self.path}: {exc}"
                    ) from exc
                file_events.append(ev)

        if not file_events:
            return True

        self.validate_events(file_events, self.runner_id, self.runner_version)

        # 1. Genesis parent hash check
        if file_events[0].parent_hash != GENESIS_PARENT_HASH:
            raise LedgerTamperedError(
                f"Genesis event parent_hash mismatch at line 1: expected {GENESIS_PARENT_HASH}, "
                f"got {file_events[0].parent_hash}"
            )

        # 2. Sequential hash chain continuity check
        for i in range(1, len(file_events)):
            curr = file_events[i]
            prev = file_events[i - 1]
            if curr.parent_hash != prev.event_hash:
                raise LedgerTamperedError(
                    f"Hash chain broken at event index {i} (session {curr.effective_session}): "
                    f"parent_hash '{curr.parent_hash}' does not match prior event_hash '{prev.event_hash}'"
                )

        return True

    def to_dense_panel(self, sessions: Sequence[str]) -> pd.DataFrame:
        """Expand sparse rebalance events into a daily target weights dense panel.

        Args:
            sessions: Ordered list of trading calendar session date strings.

        Returns:
            pd.DataFrame indexed by sessions with columns for each symbol held,
            forward-filled from the effective date until next rebalance.
        """
        if not sessions:
            return pd.DataFrame()

        # Collect all symbols mentioned in any event
        all_symbols = sorted({s for ev in self._events for s in ev.target_weights.keys()})

        # Sort events chronologically by effective_session
        sorted_events = sorted(self._events, key=lambda ev: ev.effective_session)

        # Map each session to its active target weights
        event_idx = 0
        current_weights: dict[str, float] = {s: 0.0 for s in all_symbols}
        records: list[dict[str, float]] = []

        for sess in sessions:
            # Advance events that became effective on or before this session
            while (
                event_idx < len(sorted_events)
                and sorted_events[event_idx].effective_session <= sess
            ):
                ev = sorted_events[event_idx]
                current_weights = {s: 0.0 for s in all_symbols}
                for s, w in ev.target_weights.items():
                    current_weights[s] = float(w)
                event_idx += 1

            records.append(dict(current_weights))

        panel_df = pd.DataFrame(records, index=list(sessions))
        panel_df.index.name = "session"
        return panel_df
