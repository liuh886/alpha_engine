"""Racetrack Minimal Stack & NAV Engine (Phase 1).

Authoritative minimal investment-research evaluation infrastructure for
cryptographically verifiable, tamper-evident continuous NAV tracking.
"""

from __future__ import annotations

from src.racetrack.contracts import (
    CalendarSessionError,
    ChronologyOrderError,
    DataQualificationError,
    DuplicateSessionError,
    EngineConfig,
    LedgerOverwriteError,
    LedgerTamperedError,
    LifecycleIntegrityError,
    MissingPriceDataError,
    MonthlyRankPoint,
    NAVPoint,
    PITViolationError,
    PriceMatrix,
    PrivacyViolationError,
    RebalanceEvent,
    Scoreboard,
    ScoreboardEntry,
    SimulationResult,
    ThesisMissingError,
    UnauthorizedAssetError,
    WeightConstraintError,
    assert_privacy_clean,
    canonical_json_dumps,
    compute_canonical_sha256,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.ledger import EventLedger
from src.racetrack.matrix import load_price_matrix, resolve_reference_symbol
from src.racetrack.pipeline import (
    PipelineResult,
    publish_racetrack_projection,
    render_racetrack_scoreboard,
)
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import (
    RunnerContract,
    RunnerRegistry,
    validate_runner_thesis,
)
from src.racetrack.scoring import (
    PointsRuleV1,
    calculate_monthly_returns,
    calculate_rolling_window_return,
    evaluate_race_season,
    generate_benchmark_simulation,
)

__all__ = [
    "CalendarSessionError",
    "ChronologyOrderError",
    "DataQualificationError",
    "DuplicateSessionError",
    "EngineConfig",
    "EventLedger",
    "LedgerOverwriteError",
    "LedgerTamperedError",
    "LifecycleIntegrityError",
    "MissingPriceDataError",
    "MonthlyRankPoint",
    "NAVPoint",
    "PITViolationError",
    "PipelineResult",
    "PointsRuleV1",
    "PriceMatrix",
    "PrivacyViolationError",
    "RebalanceEvent",
    "RunnerContract",
    "RunnerRegistry",
    "Scoreboard",
    "ScoreboardEntry",
    "SimulationResult",
    "ThesisMissingError",
    "UnauthorizedAssetError",
    "WeightConstraintError",
    "assert_privacy_clean",
    "calculate_monthly_returns",
    "calculate_rolling_window_return",
    "canonical_json_dumps",
    "compute_canonical_sha256",
    "evaluate_race_season",
    "generate_benchmark_simulation",
    "generate_equal_weight_pool_index",
    "load_price_matrix",
    "publish_racetrack_projection",
    "render_racetrack_scoreboard",
    "resolve_reference_symbol",
    "simulate_portfolio",
    "validate_runner_thesis",
]
