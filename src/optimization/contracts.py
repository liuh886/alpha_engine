"""Model Optimization Infrastructure — contracts and data types.

Defines the declarative experiment specification that any agent can use
to define optimization searches without coupling to model internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ModelType(str, Enum):
    RANKER = "ranker"        # Cross-sectional stock ranker (USx, CNx)
    ROTATOR = "rotator"      # ETF rotation strategy (QQQR)
    TIMER = "timer"          # Single-stock timing model (BYD)
    CUSTOM = "custom"        # User-provided evaluation function


class GateProfile(str, Enum):
    STANDARD_TEN_DAY = "ten_day_model_gates_v1"
    CALMAR_FOCUSED = "calmar_focused"
    EXCESS_AND_DRAWDOWN = "excess_and_drawdown"
    CUSTOM = "custom"


@dataclass(frozen=True)
class CostStructure:
    """Transaction cost specification — MUST match baseline model."""
    base_cost_bps: float = 20.0
    stress_cost_bps: tuple[float, ...] = (40.0, 60.0)
    annual_financing_rate: float | None = None  # For margin models like BYD


@dataclass(frozen=True)
class WindowSpec:
    """Evaluation window specification."""
    labels: tuple[str, ...]  # e.g. ("2024H1", "2024H2", "2025H1", "2025H2")
    train_start: str = "2021-01-01"
    first_test_year: int = 2024
    last_test_year: int = 2025
    horizon_sessions: int = 10
    cadence_sessions: int = 10
    min_complete_windows: int = 3
    partial_window_policy: str = "complete_windows_only"
    reporting_windows: tuple[str, ...] = ()  # Consumed, not used for selection


@dataclass(frozen=True)
class CandidateSpec:
    """A single candidate configuration to evaluate."""
    candidate_id: str
    role: str = "challenger"  # "baseline" or "challenger"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ExperimentContract:
    """Complete experiment specification.

    This is the single source of truth that any agent or runner uses.
    """
    experiment_id: str
    model_type: ModelType
    market: str                        # "us" or "cn"
    benchmark: str                     # e.g. "QQQ", "000300"
    cost_structure: CostStructure
    windows: WindowSpec
    candidates: tuple[CandidateSpec, ...]
    baseline_candidate_id: str
    gate_profile: GateProfile = GateProfile.STANDARD_TEN_DAY
    provider_uri: str | None = None    # Path to provider data
    universe_config: str | None = None  # Path to universe YAML
    factor_library: str | None = None   # Path to factor library YAML
    sector_config: str | None = None    # Path to sector classification YAML
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def baseline(self) -> CandidateSpec:
        for c in self.candidates:
            if c.candidate_id == self.baseline_candidate_id:
                return c
        raise ValueError(f"baseline '{self.baseline_candidate_id}' not in candidates")

    @property
    def challengers(self) -> tuple[CandidateSpec, ...]:
        return tuple(c for c in self.candidates if c.role == "challenger")
