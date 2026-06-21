"""WeeklyQuantRating strategy plugin wrapper."""

from __future__ import annotations

import inspect
from typing import Any

from ..registry import StrategyPlugin, _schema_from_constructor
from ..weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

_NAME = "weekly_quant_rating"
_VERSION = "1.0.0"
_DESCRIPTION = "Weekly quant-rating strategy with StrongBuy streak filtering"

_EXCLUDE_PARAMS: set[str] = set()


class WeeklyQuantRatingPlugin:
    """StrategyPlugin wrapper around WeeklyQuantRatingStrategy."""

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
        return WeeklyQuantRatingStrategy

    @property
    def default_params(self) -> dict[str, Any]:
        sig = inspect.signature(WeeklyQuantRatingStrategy.__init__)
        return {
            name: param.default
            for name, param in sig.parameters.items()
            if name not in ("self", "kwargs", "args", *_EXCLUDE_PARAMS)
            and param.default is not inspect.Parameter.empty
        }

    @property
    def param_schema(self) -> dict[str, Any]:
        return _schema_from_constructor(WeeklyQuantRatingStrategy, exclude=_EXCLUDE_PARAMS)

    def create_instance(self, **params: Any) -> WeeklyQuantRatingStrategy:
        """Create a WeeklyQuantRatingStrategy instance with validated params."""
        return WeeklyQuantRatingStrategy(**params)


# Module-level plugin instance for auto-discovery
plugin: StrategyPlugin = WeeklyQuantRatingPlugin()  # type: ignore[assignment]
