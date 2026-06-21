"""DualLayer strategy plugin wrapper."""

from __future__ import annotations

import inspect
from typing import Any

from ..dual_layer_strategy import DualLayerStrategy
from ..registry import StrategyPlugin, _schema_from_constructor

_NAME = "dual_layer"
_VERSION = "1.0.0"
_DESCRIPTION = "Dual-layer strategy: stock-level decision engine + portfolio management"

# Parameters to exclude from the schema (Qlib internals passed by the framework)
_EXCLUDE_PARAMS = {"n_drop"}


class DualLayerPlugin:
    """StrategyPlugin wrapper around DualLayerStrategy."""

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
        return DualLayerStrategy

    @property
    def default_params(self) -> dict[str, Any]:
        sig = inspect.signature(DualLayerStrategy.__init__)
        return {
            name: param.default
            for name, param in sig.parameters.items()
            if name not in ("self", "kwargs", "args", *_EXCLUDE_PARAMS)
            and param.default is not inspect.Parameter.empty
        }

    @property
    def param_schema(self) -> dict[str, Any]:
        return _schema_from_constructor(DualLayerStrategy, exclude=_EXCLUDE_PARAMS)

    def create_instance(self, **params: Any) -> DualLayerStrategy:
        """Create a DualLayerStrategy instance with validated params."""
        return DualLayerStrategy(**params)


# Module-level plugin instance for auto-discovery
plugin: StrategyPlugin = DualLayerPlugin()  # type: ignore[assignment]
