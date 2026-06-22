"""Truthful accounting for data update outcomes.

Tracks per-market symbol counts across a data update pipeline run and
produces typed reports that cannot silently claim success when symbols
are missing, stale, or failed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DataUpdateFailure(RuntimeError):
    """Typed failure that must propagate to the update job exit code.

    Raised by :meth:`UpdateAccountingReport.validate_for_publish` when
    the accounting does not permit an unconditional success claim.
    """


class FailureReason(str, Enum):
    """Typed reasons a symbol can fail during a data update."""

    FETCH_FAILED = "FETCH_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    STALE_DATA = "STALE_DATA"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    EXCLUDED_BY_POLICY = "EXCLUDED_BY_POLICY"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    CONSISTENCY_CHECK_FAILED = "CONSISTENCY_CHECK_FAILED"
    UNKNOWN = "UNKNOWN"


# Canonical state names used in per-market accounting ledgers.
ACCOUNTING_STATES = (
    "configured",
    "attempted",
    "updated",
    "reused",
    "excluded",
    "failed",
    "stale",
)


@dataclass
class UpdateAccountingReport:
    """Typed report of a single data-update run.

    Every symbol that was *configured* must appear in exactly one terminal
    state (updated / reused / excluded / failed / stale) for
    ``is_complete`` to be ``True``.
    """

    configured: dict[str, list[str]]
    attempted: dict[str, set[str]] = field(default_factory=dict)
    updated: dict[str, set[str]] = field(default_factory=dict)
    reused: dict[str, set[str]] = field(default_factory=dict)
    excluded: dict[str, set[str]] = field(default_factory=dict)
    failed: dict[str, set[str]] = field(default_factory=dict)
    stale: dict[str, set[str]] = field(default_factory=dict)
    reasons: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.configured = {
            str(market).lower(): sorted({str(symbol).upper() for symbol in symbols})
            for market, symbols in self.configured.items()
        }
        for state in ACCOUNTING_STATES[1:]:
            values = getattr(self, state)
            for market in self.configured:
                values.setdefault(market, set())

    # -- mutators ---------------------------------------------------------------

    def add(
        self,
        state: str,
        market: str,
        symbol: str,
        *,
        reason: str | FailureReason = "",
    ) -> None:
        """Record *symbol* under *state* for *market*.

        Parameters
        ----------
        state:
            One of the non-``configured`` accounting states (e.g. ``"updated"``).
        market:
            Market identifier (normalised to lowercase).
        symbol:
            Ticker symbol (normalised to uppercase).
        reason:
            Optional failure reason.  Accepts a ``FailureReason`` enum value
            or an arbitrary string.
        """
        if state not in ACCOUNTING_STATES[1:]:
            raise ValueError(f"unsupported accounting state: {state}")
        market = str(market).lower()
        symbol = str(symbol).upper()
        getattr(self, state).setdefault(market, set()).add(symbol)
        reason_str = reason.value if isinstance(reason, FailureReason) else str(reason)
        if reason_str:
            self.reasons.setdefault(state, {})[f"{market}:{symbol}"] = reason_str

    # -- queries ----------------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        """``True`` when every configured symbol is accounted for.

        A symbol is "accounted for" when it appears in exactly one of:
        updated, reused, excluded, failed, or stale.

        There must also be no symbols left in *attempted* that do not
        appear in any terminal state (i.e. every attempt must have been
        resolved).
        """
        for market, symbols in self.configured.items():
            configured_set = set(symbols)
            terminal: set[str] = set()
            for state_name in ("updated", "reused", "excluded", "failed", "stale"):
                terminal |= set(getattr(self, state_name).get(market, set()))
            if configured_set - terminal:
                return False
        return True

    def market_summary(self, market: str) -> dict[str, int]:
        """Return symbol counts for a single market."""
        market = str(market).lower()
        return {
            "configured": len(self.configured.get(market, [])),
            "attempted": len(self.attempted.get(market, set())),
            "updated": len(self.updated.get(market, set())),
            "reused": len(self.reused.get(market, set())),
            "excluded": len(self.excluded.get(market, set())),
            "failed": len(self.failed.get(market, set())),
            "stale": len(self.stale.get(market, set())),
        }

    def summary_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary for API/dashboard consumption.

        Includes per-market counts, a global ``is_complete`` flag, and the
        failure reasons ledger.
        """
        markets = sorted(self.configured)
        per_market: dict[str, Any] = {}
        for market in markets:
            per_market[market] = self.market_summary(market)

        total_configured = sum(m["configured"] for m in per_market.values())
        total_updated = sum(m["updated"] for m in per_market.values())
        total_reused = sum(m["reused"] for m in per_market.values())
        total_failed = sum(m["failed"] for m in per_market.values())
        total_stale = sum(m["stale"] for m in per_market.values())
        total_excluded = sum(m["excluded"] for m in per_market.values())

        return {
            "is_complete": self.is_complete,
            "total_configured": total_configured,
            "total_updated": total_updated,
            "total_reused": total_reused,
            "total_excluded": total_excluded,
            "total_failed": total_failed,
            "total_stale": total_stale,
            "markets": per_market,
            "reasons": copy.deepcopy(self.reasons),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the full ledger as a JSON-serialisable dict.

        Preserves per-market symbol lists (not just counts) so the
        manifest ``update_summary`` field retains full provenance.
        """
        markets = sorted(self.configured)
        result: dict[str, Any] = {
            "configured": {market: list(self.configured[market]) for market in markets}
        }
        for state in ACCOUNTING_STATES[1:]:
            values = getattr(self, state)
            result[state] = {market: sorted(values.get(market, set())) for market in markets}
        result["reasons"] = copy.deepcopy(self.reasons)
        result["is_complete"] = self.is_complete
        return result

    # -- publish gate -----------------------------------------------------------

    def _categorize_symbol(self, market: str, symbol: str) -> tuple[str, str]:
        """Return (type, importance)."""
        market = market.lower()
        if market == "cn":
            if symbol.startswith("51") or symbol.startswith("15"):
                return "etf", "optional"
            if symbol in {"000001", "000300", "000905", "399006", "000800", "000852", "000999"}:
                return "index", "optional"
            return "stock", "core"
        elif market == "us":
            if symbol in {"SPY", "QQQ"}:
                return "etf", "optional"
            if symbol.startswith("^"):
                return "index", "optional"
            return "stock", "core"
        elif market == "hk":
            return "stock", "unsupported"
        return "unknown", "optional"

    def validate_for_publish(
        self, 
        *, 
        selected_markets: set[str], 
        strict: bool = False, 
        max_missing_pct: float = 0.05,
        max_missing_count: int = 20
    ) -> list[str]:
        warnings = []
        selected_markets = {str(market).lower() for market in selected_markets}
        selected_symbols = {
            (market, symbol)
            for market in selected_markets
            for symbol in self.configured.get(market, [])
        }
        attempted = {
            (market, symbol)
            for market, symbols in self.attempted.items()
            for symbol in symbols
            if market in selected_markets
        }
        failed = {
            (market, symbol)
            for state in (self.failed, self.stale)
            for market, symbols in state.items()
            for symbol in symbols
            if market in selected_markets
        }
        accounted = {
            (market, symbol)
            for state in (self.updated, self.reused)
            for market, symbols in state.items()
            for symbol in symbols
            if market in selected_markets
        }
        
        if attempted != selected_symbols or failed or accounted != selected_symbols:
            missing = sorted(selected_symbols - accounted)
            
            # Grouping
            grouped = {"core": [], "optional": [], "unsupported": []}
            for market, symbol in missing:
                typ, imp = self._categorize_symbol(market, symbol)
                grouped[imp].append(f"{market}:{symbol}({typ})")
                
            core_missing_count = len(grouped["core"])
            core_expected_count = sum(1 for m, s in selected_symbols if self._categorize_symbol(m, s)[1] == "core")
            core_missing_pct = core_missing_count / max(1, core_expected_count)
            
            is_within_threshold = core_missing_pct <= max_missing_pct and core_missing_count <= max_missing_count
            
            report = (
                f"Missing symbols grouped by importance:\n"
                f"  - Core missing ({core_missing_count}): {grouped['core'][:10]}{'...' if core_missing_count > 10 else ''}\n"
                f"  - Optional missing ({len(grouped['optional'])}): {grouped['optional'][:10]}{'...' if len(grouped['optional']) > 10 else ''}\n"
                f"  - Unsupported missing ({len(grouped['unsupported'])}): {grouped['unsupported'][:10]}{'...' if len(grouped['unsupported']) > 10 else ''}\n"
            )
            
            if strict or not is_within_threshold:
                raise DataUpdateFailure(
                    f"partial update failed (strict={strict}, core_max_missing={max_missing_pct:.1%}, core_max_count={max_missing_count}): \n"
                    f"{report}\n"
                    f"Overall attempted={len(attempted)}/{len(selected_symbols)} "
                    f"(core_missing_pct={core_missing_pct:.1%}, core_count={core_missing_count})"
                )
            else:
                msg = f"Partial update accepted. Core missing within thresholds ({core_missing_pct:.1%} <= {max_missing_pct:.1%} AND {core_missing_count} <= {max_missing_count}).\n{report}"
                warnings.append(msg)

        updated_count = sum(
            len(symbols) for market, symbols in self.updated.items() if market in selected_markets
        )
        if updated_count == 0 and selected_symbols:
            raise DataUpdateFailure("zero symbols updated")

        for market, symbols in self.configured.items():
            if market in selected_markets:
                self.stale[market] = set(symbols) - set(self.updated.get(market, [])) - set(self.reused.get(market, []))
                continue
            expected = set(symbols)
            if not expected.issubset(self.excluded.get(market, set())):
                raise DataUpdateFailure(f"unselected market is not excluded: {market}")
            if not expected.issubset(self.reused.get(market, set())):
                raise DataUpdateFailure(f"secondary market bytes are not fully reused: {market}")

        return warnings


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def create_accounting_report(
    configured: dict[str, list[str]],
) -> UpdateAccountingReport:
    """Create a new ``UpdateAccountingReport`` for the given configured symbols."""
    return UpdateAccountingReport(configured=configured)
