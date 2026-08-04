"""Machine-readable governance for fast and authoritative backtest engines."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ExecutionMode = Literal["fast_array_research", "authoritative_qlib"]


@dataclass(frozen=True)
class BacktestExecutionReceipt:
    execution_mode: ExecutionMode
    engine: str
    authoritative_execution: bool
    precompute_status: str
    fallback_used: bool = False
    research_only: bool = True
    trade_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_execution_receipt(
    mode: ExecutionMode,
    *,
    precompute_status: str = "not_applicable",
) -> BacktestExecutionReceipt:
    """Build a fail-closed receipt for an explicitly selected engine."""
    if mode == "fast_array_research":
        return BacktestExecutionReceipt(
            execution_mode=mode,
            engine="numpy_portfolio_intent",
            authoritative_execution=False,
            precompute_status=precompute_status,
        )
    if precompute_status in {"failed", "skipped", "fallback"}:
        raise ValueError(
            "Authoritative Qlib execution cannot be claimed without required "
            "vectorized precomputation evidence"
        )
    return BacktestExecutionReceipt(
        execution_mode=mode,
        engine="qlib_port_analysis",
        authoritative_execution=True,
        precompute_status=precompute_status,
    )


def require_authoritative_execution(receipt: BacktestExecutionReceipt) -> None:
    """Reject diagnostic fast-path evidence at an authoritative promotion gate."""
    if not receipt.authoritative_execution or receipt.fallback_used:
        raise ValueError(
            f"Execution mode {receipt.execution_mode!r} is research diagnostic "
            "evidence and cannot satisfy an authoritative backtest gate"
        )
