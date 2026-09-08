"""US Qlib execution adapter for the shared fixed-10D execution contract.

Thin facade: all runtime mechanics live in
:mod:`src.research.qlib_execution_common`. This module only fixes the market
discriminator to ``"us"`` and keeps the historical public names stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.research.qlib_execution_common import (
    ExecutionRuntime,
    MarketQlibExecutionRuntime,
    execute_market_qlib_plan,
)
from src.research.spec_bound_execution import (
    SpecBoundExecutionPlan,
    SpecBoundExecutionResult,
)

# Re-export the shared Protocol under the market-specific public name.
USExecutionRuntime = ExecutionRuntime


@dataclass
class QlibUSExecutionRuntime(MarketQlibExecutionRuntime):
    """Production pyqlib runtime for the US adapter."""

    market: Literal["us"] = "us"


def execute_us_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    runtime: USExecutionRuntime | None = None,
) -> SpecBoundExecutionResult:
    """Execute one US spec exactly and return identity-bound evidence."""
    return execute_market_qlib_plan(
        plan,
        run_dir,
        market="us",
        runtime=runtime,
    )
