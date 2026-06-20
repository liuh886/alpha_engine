from __future__ import annotations

import importlib
import inspect
import pkgutil
import threading
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

log = structlog.get_logger()


@runtime_checkable
class StrategyPlugin(Protocol):
    """Protocol that all strategy plugins must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def strategy_class(self) -> type: ...

    @property
    def default_params(self) -> dict[str, Any]: ...

    @property
    def param_schema(self) -> dict[str, Any]: ...

    def create_instance(self, **params: Any) -> Any:
        """Create a Qlib strategy instance with given params, validated against param_schema."""


@dataclass
class PluginInfo:
    """Serializable metadata about a registered strategy plugin."""

    name: str
    version: str
    description: str
    strategy_class_name: str
    default_params: dict[str, Any]
    param_schema: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "strategy_class": self.strategy_class_name,
            "default_params": self.default_params,
            "param_schema": self.param_schema,
        }


class StrategyRegistry:
    """Singleton registry for strategy plugins. Thread-safe for FastAPI."""

    _instance: StrategyRegistry | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._plugins: dict[str, StrategyPlugin] = {}
        self._registry_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> StrategyRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = StrategyRegistry()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def register(self, plugin: StrategyPlugin) -> None:
        """Register a strategy plugin. Logs warning if overwriting."""
        with self._registry_lock:
            if plugin.name in self._plugins:
                log.warning(
                    "overwriting existing plugin",
                    name=plugin.name,
                    old_version=getattr(self._plugins[plugin.name], "version", "?"),
                    new_version=plugin.version,
                )
            self._plugins[plugin.name] = plugin
            log.info("plugin registered", name=plugin.name, version=plugin.version)

    def get(self, name: str) -> StrategyPlugin | None:
        """Get a registered strategy by name."""
        return self._plugins.get(name)

    def list_strategies(self) -> list[PluginInfo]:
        """List all registered strategies with metadata."""
        return [
            PluginInfo(
                name=p.name,
                version=p.version,
                description=p.description,
                strategy_class_name=p.strategy_class.__name__,
                default_params=p.default_params,
                param_schema=p.param_schema,
            )
            for p in self._plugins.values()
        ]

    def create(self, name: str, **params: Any) -> Any:
        """Create a strategy instance by name with validation."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise KeyError(f"Strategy plugin '{name}' not found")
        return plugin.create_instance(**params)

    def auto_discover(self) -> None:
        """Auto-discover plugins from src/strategies/plugins/ directory."""
        import src.strategies.plugins as plugins_pkg

        package_path = plugins_pkg.__path__  # type: ignore[attr-defined]
        for importer, module_name, is_pkg in pkgutil.iter_modules(
            package_path, prefix="src.strategies.plugins."
        ):
            if is_pkg:
                continue
            try:
                module = importlib.import_module(module_name)
            except Exception:
                log.warning("failed to import plugin module", module=module_name, exc_info=True)
                continue

            # Convention 1: module has a `register(registry)` function
            register_fn = getattr(module, "register", None)
            if callable(register_fn):
                try:
                    register_fn(self)
                    continue
                except Exception:
                    log.warning(
                        "plugin register() failed",
                        module=module_name,
                        exc_info=True,
                    )
                    continue

            # Convention 2: module has a top-level `plugin` variable that is a StrategyPlugin
            plugin_obj = getattr(module, "plugin", None)
            if plugin_obj is not None and isinstance(plugin_obj, StrategyPlugin):
                self.register(plugin_obj)
                continue

            # Convention 3: any module-level object satisfying StrategyPlugin protocol
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                candidate = getattr(module, attr_name)
                if (
                    candidate is not None
                    and not isinstance(candidate, type)
                    and isinstance(candidate, StrategyPlugin)
                ):
                    self.register(candidate)

        log.info("auto_discovery complete", count=len(self._plugins))


def _schema_from_constructor(cls: type, exclude: set[str] | None = None) -> dict[str, Any]:
    """Auto-generate a JSON Schema from a class constructor signature.

    Only includes keyword-only and regular parameters that have defaults (optional)
    or no defaults (required).  Parameters listed in *exclude* are skipped.
    Handles ``from __future__ import annotations`` by using ``typing.get_type_hints``.
    """
    import typing

    exclude = exclude or set()
    sig = inspect.signature(cls.__init__)

    # Resolve forward references / string annotations
    try:
        type_hints = typing.get_type_hints(cls.__init__)
    except Exception:
        type_hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    TYPE_MAP = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
    }

    for name, param in sig.parameters.items():
        if name in ("self", "kwargs", "args") or name in exclude:
            continue

        prop: dict[str, Any] = {}
        # Prefer resolved hint over raw annotation
        ann = type_hints.get(name, param.annotation)
        if isinstance(ann, str):
            # Still a string — try to eval it in the class module namespace
            try:
                ann = eval(ann, getattr(cls, "__module__", None) and vars(__import__(cls.__module__, fromlist=["*"])))
            except Exception:
                pass

        # Resolve Optional[X] -> X
        origin = getattr(ann, "__origin__", None)
        if origin is type(None) or ann is type(None):
            continue

        # Handle X | None union (typing.Union / PEP 604)
        if hasattr(ann, "__args__"):
            args = [a for a in ann.__args__ if a is not type(None)]
            if args:
                ann = args[0]

        json_type = TYPE_MAP.get(ann)
        if json_type:
            prop["type"] = json_type
        else:
            prop["type"] = "object"

        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(name)

        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema
