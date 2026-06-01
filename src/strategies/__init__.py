from .registry import StrategyRegistry

# Auto-register built-in strategy plugins on import
registry = StrategyRegistry.get_instance()
registry.auto_discover()
