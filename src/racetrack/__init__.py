"""Racetrack Minimal Stack & NAV Engine (Phase 1).

Authoritative minimal investment-research evaluation infrastructure for
cryptographically verifiable, tamper-evident continuous NAV tracking.
"""

from __future__ import annotations

from src.racetrack.contracts import (
    CalendarSessionError,
    EngineConfig,
    LedgerTamperedError,
    LifecycleIntegrityError,
    MissingPriceDataError,
    NAVPoint,
    PriceMatrix,
    PrivacyViolationError,
    RebalanceEvent,
    SimulationResult,
    UnauthorizedAssetError,
    WeightConstraintError,
    assert_privacy_clean,
    canonical_json_dumps,
    compute_canonical_sha256,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.ledger import EventLedger
from src.racetrack.matrix import load_price_matrix
from src.racetrack.pool_index import generate_equal_weight_pool_index

__all__ = [
    "CalendarSessionError",
    "EngineConfig",
    "EventLedger",
    "LedgerTamperedError",
    "LifecycleIntegrityError",
    "MissingPriceDataError",
    "NAVPoint",
    "PriceMatrix",
    "PrivacyViolationError",
    "RebalanceEvent",
    "SimulationResult",
    "UnauthorizedAssetError",
    "WeightConstraintError",
    "assert_privacy_clean",
    "canonical_json_dumps",
    "compute_canonical_sha256",
    "generate_equal_weight_pool_index",
    "load_price_matrix",
    "simulate_portfolio",
]
