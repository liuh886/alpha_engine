"""Racetrack core immutable contract definitions and data structures.

Enforces ADR-0004 / ADR-0005 personal privacy isolation, canonical JSON hashing,
and fail-closed integrity boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping
import uuid

import pandas as pd

# Sensitive keywords strictly forbidden from research ledgers
SENSITIVE_FIELD_NAMES = frozenset({
    "shares",
    "qty",
    "lots",
    "total_cost",
    "cost_basis",
    "cash_balance",
    "capital",
    "broker",
    "brokerage_account",
    "account_id",
    "executed_price",
    "execution_fee",
    "commission_paid",
    "realized_pnl",
    "unrealized_pnl",
    "pnl",
})


class PrivacyViolationError(ValueError):
    """Raised when personal account sensitive data is injected into research objects."""


class LedgerTamperedError(ValueError):
    """Raised when ledger hash chain fails verification or has been tampered with."""


class CalendarSessionError(ValueError):
    """Raised when session is not a valid official exchange trading session."""


class WeightConstraintError(ValueError):
    """Raised when target weights violate constraints (sum > 1.0 or negative)."""


class UnauthorizedAssetError(ValueError):
    """Raised when an asset outside the allowed universe is assigned non-zero weight."""


class MissingPriceDataError(ValueError):
    """Raised when price data for a held asset is missing (NaN)."""


class LifecycleIntegrityError(MissingPriceDataError):
    """Raised when an asset is traded before its listing date."""


def assert_privacy_clean(data: Any) -> None:
    """Recursively inspect data to ensure zero sensitive personal account fields are present.

    Raises:
        PrivacyViolationError: If any prohibited field keyword is detected.
    """
    if isinstance(data, Mapping):
        for key, value in data.items():
            key_str = str(key).strip().lower()
            if key_str in SENSITIVE_FIELD_NAMES:
                raise PrivacyViolationError(
                    f"Privacy violation: sensitive field '{key}' detected in research data"
                )
            for forbidden in ("shares", "total_cost", "broker", "account_id", "pnl", "cost_basis"):
                if forbidden in key_str:
                    raise PrivacyViolationError(
                        f"Privacy violation: sensitive keyword '{forbidden}' detected in key '{key}'"
                    )
            assert_privacy_clean(value)
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            assert_privacy_clean(item)


def canonical_json_dumps(obj: Any) -> str:
    """Produce deterministic, whitespace-stripped canonical JSON with sorted keys."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_canonical_sha256(obj: Any) -> str:
    """Calculate SHA-256 hash of canonical JSON representation."""
    encoded = canonical_json_dumps(obj).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RebalanceEvent:
    """Immutable single rebalance decision event on the Q(t, s) sparse ledger."""

    event_id: str
    parent_hash: str
    timestamp_utc: str
    effective_session: str
    runner_id: str
    runner_version: str
    target_weights: dict[str, float]
    cash_weight: float
    reason: str
    event_hash: str

    def __post_init__(self) -> None:
        # Strict privacy audit
        assert_privacy_clean({
            "event_id": self.event_id,
            "parent_hash": self.parent_hash,
            "timestamp_utc": self.timestamp_utc,
            "effective_session": self.effective_session,
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "target_weights": self.target_weights,
            "cash_weight": self.cash_weight,
            "reason": self.reason,
            "event_hash": self.event_hash,
        })

        # Validate weights
        sum_w = sum(self.target_weights.values())
        for s, w in self.target_weights.items():
            if w < -1e-8:
                raise WeightConstraintError(f"Target weight for '{s}' cannot be negative: {w}")
        if sum_w > 1.000001:
            raise WeightConstraintError(f"Target weights sum to {sum_w:.6f} > 1.0")

        # Validate event hash
        expected_hash = self.compute_hash(
            event_id=self.event_id,
            parent_hash=self.parent_hash,
            timestamp_utc=self.timestamp_utc,
            effective_session=self.effective_session,
            runner_id=self.runner_id,
            runner_version=self.runner_version,
            target_weights=self.target_weights,
            cash_weight=self.cash_weight,
            reason=self.reason,
        )
        if self.event_hash != expected_hash:
            raise LedgerTamperedError(
                f"Event hash verification failed: got {self.event_hash}, expected {expected_hash}"
            )

    @staticmethod
    def compute_hash(
        event_id: str,
        parent_hash: str,
        timestamp_utc: str,
        effective_session: str,
        runner_id: str,
        runner_version: str,
        target_weights: dict[str, float],
        cash_weight: float,
        reason: str,
    ) -> str:
        """Compute canonical SHA-256 hash excluding the event_hash field itself."""
        payload = {
            "event_id": event_id,
            "parent_hash": parent_hash,
            "timestamp_utc": timestamp_utc,
            "effective_session": effective_session,
            "runner_id": runner_id,
            "runner_version": runner_version,
            "target_weights": {k: float(v) for k, v in target_weights.items()},
            "cash_weight": float(cash_weight),
            "reason": reason,
        }
        return compute_canonical_sha256(payload)

    @classmethod
    def create(
        cls,
        parent_hash: str,
        effective_session: str,
        runner_id: str,
        runner_version: str,
        target_weights: dict[str, float],
        reason: str,
        event_id: str | None = None,
        timestamp_utc: str | None = None,
    ) -> "RebalanceEvent":
        """Factory method to construct a validated, cryptographically hashed RebalanceEvent."""
        assert_privacy_clean(target_weights)
        if event_id is None:
            event_id = str(uuid.uuid4())
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc).isoformat()

        sum_w = sum(target_weights.values())
        if sum_w > 1.000001:
            raise WeightConstraintError(f"Target weights sum to {sum_w:.6f} > 1.0")
        for s, w in target_weights.items():
            if w < -1e-8:
                raise WeightConstraintError(f"Target weight for '{s}' cannot be negative: {w}")

        cash_weight = max(0.0, round(1.0 - sum_w, 8))
        event_hash = cls.compute_hash(
            event_id=event_id,
            parent_hash=parent_hash,
            timestamp_utc=timestamp_utc,
            effective_session=effective_session,
            runner_id=runner_id,
            runner_version=runner_version,
            target_weights=target_weights,
            cash_weight=cash_weight,
            reason=reason,
        )
        return cls(
            event_id=event_id,
            parent_hash=parent_hash,
            timestamp_utc=timestamp_utc,
            effective_session=effective_session,
            runner_id=runner_id,
            runner_version=runner_version,
            target_weights=target_weights,
            cash_weight=cash_weight,
            reason=reason,
            event_hash=event_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "event_id": self.event_id,
            "parent_hash": self.parent_hash,
            "timestamp_utc": self.timestamp_utc,
            "effective_session": self.effective_session,
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "target_weights": self.target_weights,
            "cash_weight": self.cash_weight,
            "reason": self.reason,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RebalanceEvent":
        """Load from dictionary with privacy assertions and hash verification."""
        assert_privacy_clean(data)
        return cls(
            event_id=str(data["event_id"]),
            parent_hash=str(data["parent_hash"]),
            timestamp_utc=str(data["timestamp_utc"]),
            effective_session=str(data["effective_session"]),
            runner_id=str(data["runner_id"]),
            runner_version=str(data["runner_version"]),
            target_weights={str(k): float(v) for k, v in data["target_weights"].items()},
            cash_weight=float(data["cash_weight"]),
            reason=str(data["reason"]),
            event_hash=str(data["event_hash"]),
        )


@dataclass(frozen=True)
class EngineConfig:
    """Configuration parameters for the V & NAV conversion engine."""

    friction_rate: float = 0.0008  # Default 8 bps (one-sided)
    risk_free_rate_annual: float = 0.02  # Annual risk-free rate 2.0%
    annual_trading_days: int = 252


@dataclass(frozen=True)
class NAVPoint:
    """Daily snapshot point of portfolio value, return, friction, and weights."""

    session: str
    nav: float
    gross_return: float
    net_return: float
    turnover: float
    friction: float
    drawdown: float
    weights: dict[str, float]
    cash_weight: float


@dataclass(frozen=True)
class SimulationResult:
    """Authoritative outcome of running simulate_portfolio."""

    runner_id: str
    runner_version: str
    start_session: str
    end_session: str
    total_sessions: int
    cumulative_return: float
    annualized_cagr: float
    annualized_volatility: float
    annualized_sharpe: float
    max_drawdown: float
    cumulative_turnover: float
    annualized_excess_return: float
    nav_history: tuple[NAVPoint, ...]

    def to_dataframe(self) -> pd.DataFrame:
        """Convert NAV timeseries into a pandas DataFrame."""
        records = []
        for pt in self.nav_history:
            records.append({
                "session": pt.session,
                "nav": pt.nav,
                "gross_return": pt.gross_return,
                "net_return": pt.net_return,
                "turnover": pt.turnover,
                "friction": pt.friction,
                "drawdown": pt.drawdown,
                "cash_weight": pt.cash_weight,
            })
        df = pd.DataFrame(records)
        if not df.empty:
            df.set_index("session", inplace=True)
        return df

    def to_dict(self) -> dict[str, Any]:
        """Convert KPI summary into dictionary."""
        return {
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "start_session": self.start_session,
            "end_session": self.end_session,
            "total_sessions": self.total_sessions,
            "cumulative_return": self.cumulative_return,
            "annualized_cagr": self.annualized_cagr,
            "annualized_volatility": self.annualized_volatility,
            "annualized_sharpe": self.annualized_sharpe,
            "max_drawdown": self.max_drawdown,
            "cumulative_turnover": self.cumulative_turnover,
            "annualized_excess_return": self.annualized_excess_return,
        }


@dataclass(frozen=True)
class PriceMatrix:
    """Immutable market price matrix P(t, s) aligned to official exchange calendar."""

    market: str
    pool_id: str
    reference_symbol: str
    calendar: str
    start_session: str
    end_session: str
    sessions: tuple[str, ...]
    candidate_symbols: tuple[str, ...]
    symbols: tuple[str, ...]
    prices: pd.DataFrame
    matrix_sha256: str
    source_evidence_hashes: dict[str, str]

    def get_price(self, session: str, symbol: str) -> float:
        """Get adjusted close price for symbol on session. Returns np.nan if missing."""
        if session not in self.prices.index:
            raise CalendarSessionError(f"Session '{session}' is not in price matrix calendar")
        if symbol not in self.prices.columns:
            raise UnauthorizedAssetError(f"Symbol '{symbol}' is not in price matrix universe")
        return float(self.prices.loc[session, symbol])
