"""Strategy execution domain models, engine, and adapters."""

from src.execution.adapter import StrategyExecutionAdapter, build_execution_request
from src.execution.engine import StrategyExecutionEngine
from src.execution.grade_weight_assigner import GradeAllocation, GradeWeightAssigner
from src.execution.regime_filter import RegimeFilter, RegimeSignal
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import (
    ExecutionDiagnostics,
    SignalExecutionEngine,
)

__all__ = [
    # Existing
    "StrategyExecutionAdapter",
    "StrategyExecutionEngine",
    "build_execution_request",
    # New — P0 execution pipeline
    "SignalExecutionConfig",
    "RegimeFilter",
    "RegimeSignal",
    "GradeWeightAssigner",
    "GradeAllocation",
    "SignalExecutionEngine",
    "ExecutionDiagnostics",
]
