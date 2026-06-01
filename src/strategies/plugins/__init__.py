"""
Auto-discovers and registers all strategy plugins in this directory.

Each plugin module should either:
  1. Define a `register(registry)` function that registers plugins, or
  2. Expose a top-level `plugin` variable that is a StrategyPlugin instance, or
  3. Expose any module-level object satisfying the StrategyPlugin protocol.
"""
