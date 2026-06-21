"""BiweeklyTrend strategy plugin wrapper."""

from __future__ import annotations

import inspect
from typing import Any

from ..biweekly_trend_strategy import BiweeklyTrendStrategy
from ..registry import StrategyPlugin, _schema_from_constructor

_NAME = "biweekly_trend"
_VERSION = "1.0.0"
_DESCRIPTION = "Biweekly trend-following strategy with MA filter"

# Parameters to exclude from the schema (Qlib internals passed by the framework)
_EXCLUDE_PARAMS = {"n_drop"}


class BiweeklyTrendPlugin:
    """StrategyPlugin wrapper around BiweeklyTrendStrategy."""

    @property
    def name(self) -> str:
        return _NAME

    @property
    def version(self) -> str:
        return _VERSION

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def strategy_class(self) -> type:
        return BiweeklyTrendStrategy

    @property
    def default_params(self) -> dict[str, Any]:
        sig = inspect.signature(BiweeklyTrendStrategy.__init__)
        return {
            name: param.default
            for name, param in sig.parameters.items()
            if name not in ("self", "kwargs", "args", *_EXCLUDE_PARAMS)
            and param.default is not inspect.Parameter.empty
        }

    @property
    def param_schema(self) -> dict[str, Any]:
        return _schema_from_constructor(BiweeklyTrendStrategy, exclude=_EXCLUDE_PARAMS)

    def create_instance(self, **params: Any) -> BiweeklyTrendStrategy:
        """Create a BiweeklyTrendStrategy instance with validated params."""
        return BiweeklyTrendStrategy(**params)


# Module-level plugin instance for auto-discovery
plugin: StrategyPlugin = BiweeklyTrendPlugin()  # type: ignore[assignment]
