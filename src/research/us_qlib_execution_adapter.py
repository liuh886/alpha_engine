"""US Qlib execution adapter for the shared fixed-10D execution contract.

The US adapter consumes the same :class:`SpecBoundExecutionPlan` and returns
the same :class:`SpecBoundExecutionResult` as the CN adapter.  This module
owns only the US-specific Qlib runtime and the public
``execute_us_qlib_plan`` wrapper.  All execution mechanics live in the shared
:mod:`~src.research.qlib_execution_common` engine.
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
USExecutionRuntime = ExecutionRuntime


@dataclass
class QlibUSExecutionRuntime:
    """Production pyqlib runtime for the US adapter."""

    provider_uri: str | Path | None = None
    _resolved_provider_uri: str = ""
    _provider_identity_sha256: str = ""

    def initialize(self, repository_root: Path) -> None:
        provider = (
            Path(self.provider_uri)
            if self.provider_uri is not None
            else market_provider_path(repository_root, "us")
        )
        manifest = load_provider_manifest(
            provider,
            expected_market="us",
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
                market="us",
                provider_uri_default=self._resolved_provider_uri,
            )
        )

    def available_symbols(self) -> set[str]:
        from qlib.data import D

        values = D.list_instruments(
            D.instruments("all"),
            freq="day",
            as_list=True,
        )
        if isinstance(values, dict):
            return {str(item) for item in values}
        if hasattr(values, "tolist"):
            return {str(item) for item in values.tolist()}
        return {str(item) for item in values}

    def date_coverage(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
    ) -> dict[str, dict[str, Any]]:
        return load_symbol_date_coverage(list(symbols), start, end)

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        from qlib.data import D

        return pd.DatetimeIndex(
            D.calendar(start_time=start, end_time=end, freq="day")
        )

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
            "market": "us",
        }


def execute_us_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    runtime: USExecutionRuntime | None = None,
) -> SpecBoundExecutionResult:
    """Execute one US spec exactly and return identity-bound evidence."""
    return execute_qlib_plan(
        plan,
        run_dir,
        market="us",
        runtime=runtime if runtime is not None else QlibUSExecutionRuntime(),
    )
