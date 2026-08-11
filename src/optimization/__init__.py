"""Model Optimization Infrastructure — v2 public API.

Complete optimization framework with:
- 3 model-type runners (Ranker, Rotator, Timer)
- Data caching (one load, many uses)
- Sector cap + guardrail integration
- Standardized receipts and gate checking

Usage:
    from src.optimization import (
        ExperimentContract, CandidateSpec, CostStructure, WindowSpec,
        ModelType, GateProfile,
        RankerOptimizer, RotatorOptimizer, TimerOptimizer,
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
from src.optimization.cache import OptimizationDataCache
from src.optimization.foundation import DataFoundation
from src.optimization.factor_library import FactorLibrary, FactorRecord, FactorGroup, get_factor_library
from src.optimization.runner import BaseOptimizationRunner
from src.optimization.ranker_runner import RankerOptimizer
from src.optimization.rotator_runner import RotatorOptimizer
from src.optimization.timer_runner import TimerOptimizer

__all__ = [
    # Contracts
    "ExperimentContract", "CandidateSpec", "CostStructure", "WindowSpec",
    "ModelType", "GateProfile",
    # Metrics
    "WindowResult", "CandidateResult", "GateResult",
    "aggregate_windows", "check_gates", "compound_returns", "relative_excess",
    # Infrastructure
    "OptimizationDataCache", "DataFoundation",
    "FactorLibrary", "FactorRecord", "FactorGroup", "get_factor_library",
    "experiment_identity", "save_receipt",
    # Runners
    "BaseOptimizationRunner", "RankerOptimizer", "RotatorOptimizer", "TimerOptimizer",
]
