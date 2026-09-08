"""CN Qlib execution adapter for the fixed-10D spec-bound research contract.

Thin facade: all runtime mechanics live in
:mod:`src.research.qlib_execution_common`. This module only fixes the market
discriminator to ``"cn"`` and keeps the historical public names stable.

Qlib imports are lazy. Unit tests can inject a runtime implementation without
installing or initializing Qlib.
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
CNExecutionRuntime = ExecutionRuntime


@dataclass
class QlibCNExecutionRuntime(MarketQlibExecutionRuntime):
    """Production Qlib implementation of :class:`CNExecutionRuntime`."""

    market: Literal["cn"] = "cn"


def execute_cn_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    runtime: CNExecutionRuntime | None = None,
) -> SpecBoundExecutionResult:
    """Execute the CN research plan and return identity-bound evidence paths."""
    return execute_market_qlib_plan(
        plan,
        run_dir,
        market="cn",
        runtime=runtime,
    )
