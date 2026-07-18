"""CN Qlib execution adapter for the fixed-10D spec-bound research contract.

The adapter consumes a :class:`SpecBoundExecutionPlan` and delegates to the
shared :func:`~src.research.qlib_execution_common.execute_qlib_plan` engine.
This module owns only the CN-specific Qlib runtime and the public
``execute_cn_qlib_plan`` wrapper.

Qlib imports are lazy. Unit tests can inject a runtime implementation without
installing or initializing Qlib.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.data.market_provider import load_provider_manifest, market_provider_path
from src.research.qlib_execution_common import (
    ExecutionRuntime,
    execute_qlib_plan,
)
from src.research.spec_bound_execution import (
    SpecBoundExecutionPlan,
    SpecBoundExecutionResult,
)
from src.research.universe_robustness import load_symbol_date_coverage

# Re-export the shared Protocol under the market-specific public name.
CNExecutionRuntime = ExecutionRuntime


@dataclass
class QlibCNExecutionRuntime:
    """Production Qlib implementation of :class:`CNExecutionRuntime`."""

    provider_uri: str | Path | None = None
    _resolved_provider_uri: str = ""
    _provider_identity_sha256: str = ""

    def initialize(self, repository_root: Path) -> None:
        provider = (
            Path(self.provider_uri)
            if self.provider_uri is not None
            else market_provider_path(repository_root, "cn")
        )
        manifest = load_provider_manifest(
            provider,
            expected_market="cn",
            required=self.provider_uri is None,
            verify_files=True,
        )
        self._provider_identity_sha256 = (
            "" if manifest is None else str(manifest["provider_identity_sha256"])
        )
        self._resolved_provider_uri = str(provider.resolve())
        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market="cn",
                provider_uri_default=self._resolved_provider_uri,
            )
        )

    def available_symbols(self) -> set[str]:
        from qlib.data import D

        instruments = D.list_instruments(D.instruments("all"), level="market")
        if hasattr(instruments, "tolist"):
            return {str(item) for item in instruments.tolist()}
        return {str(item) for item in instruments}

    def date_coverage(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
    ) -> dict[str, dict[str, Any]]:
        return load_symbol_date_coverage(list(symbols), start, end)

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        from qlib.data import D

        values = D.calendar(start_time=start, end_time=end, freq="day")
        return pd.DatetimeIndex(values)

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        from qlib.data import D

        return D.features(
            list(symbols),
            list(expressions),
            start_time=start,
            end_time=end,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": "qlib",
            "provider_uri": self._resolved_provider_uri,
            "provider_identity_sha256": self._provider_identity_sha256,
            "market": "cn",
        }


def execute_cn_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    runtime: CNExecutionRuntime | None = None,
) -> SpecBoundExecutionResult:
    """Execute the CN research plan and return identity-bound evidence paths."""
    return execute_qlib_plan(
        plan,
        run_dir,
        market="cn",
        runtime=runtime if runtime is not None else QlibCNExecutionRuntime(),
    )
