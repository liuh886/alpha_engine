from __future__ import annotations

from pathlib import Path

from src.workflows.commands import (
    WorkflowCommandEnvelope,
    build_backtest_command_envelopes,
    build_backtest_commands,
    build_workflow_commands,
)

__all__ = [
    "WorkflowCommandEnvelope",
    "build_backtest_command_envelopes",
    "build_backtest_commands",
    "build_workflow_commands",
    "resolve_profile_path",
]


def resolve_profile_path(*, project_root: Path) -> Path:
    return Path(project_root) / "configs" / "strategy_profile.json"
