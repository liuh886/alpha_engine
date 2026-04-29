from __future__ import annotations

from pathlib import Path


def build_backtest_commands(
    *,
    python_exe: str,
    market: str,
    model_type: str = "lgbm",
    profile_path: str = "configs/strategy_profile.json",
    mode: str = "train",
    model_path: str | None = None,
    start: str = "2025-01-01",
    end: str = "latest",
    tag: str | None = None,
    strategy_template: str | None = None,
    cost_params: dict | str | None = None,
) -> list[list[str]]:
    """
    Build the subprocess command(s) to run a backtest from the dashboard.

    We always run the orchestrator with a profile, so it compiles the workflow config
    from `profile_path` for the selected market before training/backtesting.
    """
    market = (market or "").lower().strip()
    if not market:
        raise ValueError("market is required")

    profile_path = str(profile_path)
    if not profile_path:
        raise ValueError("profile_path is required")

    mode = (mode or "train").lower().strip()
    if mode not in {"train", "rebacktest"}:
        raise ValueError("mode must be 'train' or 'rebacktest'")

    if mode == "train":
        cmd = [
            str(python_exe),
            "-m",
            "src.orchestrator",
            "run",
            "--market",
            market,
            "--model_type",
            str(model_type),
            "--profile",
            profile_path,
        ]
        if tag:
            cmd += ["--tag", str(tag)]
        if strategy_template:
            cmd += ["--strategy_template", str(strategy_template)]
        if cost_params:
            if isinstance(cost_params, dict):
                import json

                cmd += ["--cost_params", json.dumps(cost_params)]
            else:
                cmd += ["--cost_params", str(cost_params)]
        return [cmd]

    if not model_path:
        raise ValueError("model_path is required for rebacktest")

    cmd = [
        str(python_exe),
        "-m",
        "src.orchestrator",
        "rebacktest",
        "--market",
        market,
        "--model_type",
        str(model_type),
        "--model_path",
        str(model_path),
        "--start",
        str(start),
        "--end",
        str(end),
        "--profile",
        profile_path,
    ]
    if tag:
        cmd += ["--tag", str(tag)]
    if strategy_template:
        cmd += ["--strategy_template", str(strategy_template)]
    if cost_params:
        if isinstance(cost_params, dict):
            import json

            cmd += ["--cost_params", json.dumps(cost_params)]
        else:
            cmd += ["--cost_params", str(cost_params)]

    return [cmd]


def resolve_profile_path(*, project_root: Path) -> Path:
    return Path(project_root) / "configs" / "strategy_profile.json"
