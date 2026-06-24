from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

ORCHESTRATOR_MODULE = "src.orchestrator"


@dataclass(frozen=True)
class WorkflowCommandEnvelope:
    """Stable workflow/job command intent mapped to the legacy orchestrator CLI."""

    action: str
    market: str
    model_type: str = "lgbm"
    profile_path: str = "configs/strategy_profile.json"
    model_path: str | None = None
    start: str = "2025-01-01"
    end: str = "latest"
    tag: str | None = None
    strategy_template: str | None = None
    cost_params: dict[str, Any] | str | None = None
    snapshot_id: str | None = None

    @classmethod
    def from_backtest_request(
        cls,
        *,
        market: str,
        model_type: str = "lgbm",
        profile_path: str = "configs/strategy_profile.json",
        mode: str = "train",
        model_path: str | None = None,
        start: str = "2025-01-01",
        end: str = "latest",
        tag: str | None = None,
        strategy_template: str | None = None,
        cost_params: dict[str, Any] | str | None = None,
        snapshot_id: str | None = None,
    ) -> WorkflowCommandEnvelope:
        market = _require_market(market)
        profile_path = _require_profile_path(profile_path)
        mode = (mode or "train").lower().strip()
        if mode not in {"train", "rebacktest"}:
            raise ValueError("mode must be 'train' or 'rebacktest'")
        return cls(
            action="run" if mode == "train" else "rebacktest",
            market=market,
            model_type=str(model_type),
            profile_path=profile_path,
            model_path=str(model_path) if model_path else None,
            start=str(start),
            end=str(end),
            tag=str(tag) if tag else None,
            strategy_template=str(strategy_template) if strategy_template else None,
            cost_params=cost_params,
            snapshot_id=str(snapshot_id) if snapshot_id else None,
        )

    def to_argv(self, *, python_exe: str | list[str]) -> list[str]:
        """Render this envelope as a subprocess-ready argv list.

        Parameters
        ----------
        python_exe : str or list[str]
            Interpreter command.  A string like ``"uv run python"`` is
            automatically split into ``["uv", "run", "python"]`` so each
            token is a separate argv element (required by ``subprocess.Popen``
            with a list).
        """
        exe = _normalize_interpreter(python_exe)

        if self.action == "run":
            cmd = [
                *exe,
                "-m",
                ORCHESTRATOR_MODULE,
                "run",
                "--market",
                self.market,
                "--model_type",
                self.model_type,
                "--profile",
                self.profile_path,
            ]
            return _append_optional_flags(
                cmd,
                tag=self.tag,
                strategy_template=self.strategy_template,
                cost_params=self.cost_params,
                snapshot_id=self.snapshot_id,
            )

        if self.action == "rebacktest":
            cmd = [
                *exe,
                "-m",
                ORCHESTRATOR_MODULE,
                "rebacktest",
                "--market",
                self.market,
                "--model_type",
                self.model_type,
            ]
            if self.model_path:
                cmd += ["--model_path", self.model_path]
            cmd += [
                "--start",
                self.start,
                "--end",
                self.end,
                "--profile",
                self.profile_path,
            ]
            return _append_optional_flags(
                cmd,
                tag=self.tag,
                strategy_template=self.strategy_template,
                cost_params=self.cost_params,
                snapshot_id=self.snapshot_id,
            )

        raise ValueError(f"unsupported workflow command action: {self.action}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "market": self.market,
            "model_type": self.model_type,
            "profile_path": self.profile_path,
            "model_path": self.model_path,
            "start": self.start,
            "end": self.end,
            "tag": self.tag,
            "strategy_template": self.strategy_template,
            "cost_params": self.cost_params,
            "snapshot_id": self.snapshot_id,
        }


def build_workflow_commands(
    *,
    python_exe: str | list[str],
    envelopes: list[WorkflowCommandEnvelope],
) -> list[list[str]]:
    return [envelope.to_argv(python_exe=python_exe) for envelope in envelopes]


def _normalize_interpreter(python_exe: str | list[str]) -> list[str]:
    """Normalize interpreter to a list of argv tokens.

    ``"uv run python"`` → ``["uv", "run", "python"]``
    ``["uv", "run", "python"]`` → ``["uv", "run", "python"]``
    """
    if isinstance(python_exe, list):
        return [str(x) for x in python_exe]
    return str(python_exe).split()


def build_backtest_command_envelopes(
    *,
    market: str,
    model_type: str = "lgbm",
    profile_path: str = "configs/strategy_profile.json",
    mode: str = "train",
    model_path: str | None = None,
    start: str = "2025-01-01",
    end: str = "latest",
    tag: str | None = None,
    strategy_template: str | None = None,
    cost_params: dict[str, Any] | str | None = None,
    snapshot_id: str | None = None,
) -> list[WorkflowCommandEnvelope]:
    return [
        WorkflowCommandEnvelope.from_backtest_request(
            market=market,
            model_type=model_type,
            profile_path=profile_path,
            mode=mode,
            model_path=model_path,
            start=start,
            end=end,
            tag=tag,
            strategy_template=strategy_template,
            cost_params=cost_params,
            snapshot_id=snapshot_id,
        )
    ]


def build_backtest_commands(
    *,
    python_exe: str | list[str],
    market: str,
    model_type: str = "lgbm",
    profile_path: str = "configs/strategy_profile.json",
    mode: str = "train",
    model_path: str | None = None,
    start: str = "2025-01-01",
    end: str = "latest",
    tag: str | None = None,
    strategy_template: str | None = None,
    cost_params: dict[str, Any] | str | None = None,
    snapshot_id: str | None = None,
) -> list[list[str]]:
    envelopes = build_backtest_command_envelopes(
        market=market,
        model_type=model_type,
        profile_path=profile_path,
        mode=mode,
        model_path=model_path,
        start=start,
        end=end,
        tag=tag,
        strategy_template=strategy_template,
        cost_params=cost_params,
        snapshot_id=snapshot_id,
    )
    return build_workflow_commands(python_exe=python_exe, envelopes=envelopes)


def _require_market(market: str) -> str:
    market = (market or "").lower().strip()
    if not market:
        raise ValueError("market is required")
    return market


def _require_profile_path(profile_path: str) -> str:
    profile_path = str(profile_path)
    if not profile_path:
        raise ValueError("profile_path is required")
    return profile_path


def _append_optional_flags(
    cmd: list[str],
    *,
    tag: str | None,
    strategy_template: str | None,
    cost_params: dict[str, Any] | str | None,
    snapshot_id: str | None = None,
) -> list[str]:
    if tag:
        cmd += ["--tag", str(tag)]
    if strategy_template:
        cmd += ["--strategy_template", str(strategy_template)]
    if cost_params:
        if isinstance(cost_params, dict):
            cmd += ["--cost_params", json.dumps(cost_params)]
        else:
            cmd += ["--cost_params", str(cost_params)]
    if snapshot_id:
        cmd += ["--snapshot_id", str(snapshot_id)]
    return cmd
