"""Vectorized Biweekly strategy plugin wrapper."""
from __future__ import annotations

import inspect
from typing import Any

from ..registry import StrategyPlugin, _schema_from_constructor
from ..vectorized_strategy import VectorizedBiweeklyStrategy

_NAME = "vectorized_biweekly"
_VERSION = "1.0.0"
_DESCRIPTION = "Vectorized biweekly strategy with pre-computed signals"

_EXCLUDE_PARAMS = {"n_drop"}


class VectorizedBiweeklyPlugin:
    """StrategyPlugin wrapper around VectorizedBiweeklyStrategy."""

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
        return VectorizedBiweeklyStrategy

    @property
    def default_params(self) -> dict[str, Any]:
        sig = inspect.signature(VectorizedBiweeklyStrategy.__init__)
        return {
            name: param.default
            for name, param in sig.parameters.items()
            if name not in ("self", "kwargs", "args", *_EXCLUDE_PARAMS)
            and param.default is not inspect.Parameter.empty
        }

    @property
    def param_schema(self) -> dict[str, Any]:
        return _schema_from_constructor(VectorizedBiweeklyStrategy, exclude=_EXCLUDE_PARAMS)

    def create_instance(self, **params: Any) -> VectorizedBiweeklyStrategy:
        """Create a VectorizedBiweeklyStrategy instance with validated params."""
        return VectorizedBiweeklyStrategy(**params)


# Module-level plugin instance for auto-discovery
plugin: StrategyPlugin = VectorizedBiweeklyPlugin()  # type: ignore[assignment]
