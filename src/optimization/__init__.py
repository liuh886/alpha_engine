"""Model Optimization Infrastructure — public API.

Usage:
    from src.optimization import (
        ExperimentContract, CandidateSpec, CostStructure, WindowSpec,
        ModelType, GateProfile,
        build_ranker_experiment, build_rotator_experiment, build_timer_experiment,
        BaseOptimizationRunner,
    )
"""
from src.optimization.contracts import (
    CandidateSpec,
    CostStructure,
    ExperimentContract,
    GateProfile,
    ModelType,
    WindowSpec,
)
from src.optimization.metrics import (
    CandidateResult,
    GateResult,
    WindowResult,
    aggregate_windows,
    check_gates,
    compound_returns,
    relative_excess,
)
from src.optimization.receipts import experiment_identity, save_receipt
from src.optimization.runner import BaseOptimizationRunner

__all__ = [
    # Contracts
    "ExperimentContract",
    "CandidateSpec",
    "CostStructure",
    "WindowSpec",
    "ModelType",
    "GateProfile",
    # Metrics
    "WindowResult",
    "CandidateResult",
    "GateResult",
    "aggregate_windows",
    "check_gates",
    "compound_returns",
    "relative_excess",
    # Receipts
    "experiment_identity",
    "save_receipt",
    # Runner
    "BaseOptimizationRunner",
]
