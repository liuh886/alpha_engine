"""Experiment contracts — immutable data classes for optimization experiments.

Pure types, no I/O. Used by existing experiment_harness infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelType(str, Enum):
    RANKER = "ranker"
    ROTATOR = "rotator"
    TIMER = "timer"


@dataclass(frozen=True)
class CostStructure:
    """Transaction costs — must match baseline model."""
    base_cost_bps: float
    stress_cost_bps: tuple[float, ...] = (40.0, 60.0)


@dataclass(frozen=True)
class WindowSpec:
    """Evaluation window specification."""
    labels: tuple[str, ...]
    train_start: str = "2021-01-01"
    first_test_year: int = 2024
    last_test_year: int = 2025
    horizon_sessions: int = 10
    cadence_sessions: int = 10
    min_complete_windows: int = 3
    partial_window_policy: str = "complete_windows_only"
    reporting_windows: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateSpec:
    """A single candidate configuration."""
    candidate_id: str
    role: str = "challenger"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ExperimentContract:
    """Complete experiment specification."""
    experiment_id: str
    model_type: ModelType
    market: str
    benchmark: str
    cost_structure: CostStructure
    windows: WindowSpec
    candidates: tuple[CandidateSpec, ...]
    baseline_candidate_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def baseline(self) -> CandidateSpec:
        for c in self.candidates:
            if c.candidate_id == self.baseline_candidate_id:
                return c
        raise ValueError(f"baseline '{self.baseline_candidate_id}' not found")

    @property
    def challengers(self) -> tuple[CandidateSpec, ...]:
        return tuple(c for c in self.candidates if c.role == "challenger")
