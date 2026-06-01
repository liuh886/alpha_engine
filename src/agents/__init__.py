"""
Agents package — Alpha Engine AI agents.

The former multi-agent system (Alpha, Risk, Governance, Developer) has been
consolidated into a single ``ResearchAssistant``.  Old import paths are kept
for backward compatibility but emit deprecation warnings.
"""
from __future__ import annotations

import warnings

from .research_assistant import ResearchAssistant  # noqa: F401 — primary export

__all__ = ["ResearchAssistant"]


# ---------------------------------------------------------------------------
# Backward-compatible deprecated imports
# ---------------------------------------------------------------------------

def _deprecated_import(name: str, module_path: str):
    """Emit a deprecation warning and return the class."""
    warnings.warn(
        f"{name} is deprecated, use ResearchAssistant instead. "
        f"(imported from {module_path})",
        DeprecationWarning,
        stacklevel=2,
    )


class _DeprecatedProxy:
    """Lazy proxy that warns on first access."""

    def __init__(self, name: str, module_path: str, class_name: str):
        self._name = name
        self._module_path = module_path
        self._class_name = class_name
        self._resolved = None

    def _resolve(self):
        if self._resolved is None:
            _deprecated_import(self._name, self._module_path)
            import importlib
            mod = importlib.import_module(self._module_path)
            self._resolved = getattr(mod, self._class_name)
        return self._resolved

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._resolve(), item)


# Provide module-level names so ``from src.agents import AlphaAgent`` still works
AlphaAgent = _DeprecatedProxy("AlphaAgent", "src.agents.alpha.alpha_agent", "AlphaAgent")
RiskAgent = _DeprecatedProxy("RiskAgent", "src.agents.risk.risk_agent", "RiskAgent")
GovernanceAgent = _DeprecatedProxy("GovernanceAgent", "src.agents.governance.governance_agent", "GovernanceAgent")
DeveloperAgent = _DeprecatedProxy("DeveloperAgent", "src.agents.developer.developer_agent", "DeveloperAgent")
