import subprocess
import time
from typing import Any

from src.reliability.classifier import classify_failure
from src.reliability.failure_log import append_failure_event

_DAILY_RUNS_COUNT = 0
_LAST_RUN_DAY = ""


def run_orchestrator(
    market: str = "all",
    mode: str = "run",
    model_type: str = "lgbm",
    profile_path: str = "configs/strategy_profile.json",
    tag: str = "",
    strategy_template: str = "",
) -> dict[str, Any]:
    """
    Run the main trading orchestrator to perform training or inference.

    Args:
        market: Which market to run ('cn', 'us', or 'all').
        mode: The orchestrator command ('run' for train/predict, 'rebacktest' for backtest).
        model_type: Default is 'lgbm'.
        profile_path: Path to the strategy profile json.
        tag: Optional tag for the run.
        strategy_template: Optional strategy template name.

    Returns:
        dict: Containing 'stdout', 'stderr', and 'returncode'.
    """
    global _DAILY_RUNS_COUNT, _LAST_RUN_DAY
    current_day = time.strftime("%Y-%m-%d")
    if current_day != _LAST_RUN_DAY:
        _DAILY_RUNS_COUNT = 0
        _LAST_RUN_DAY = current_day

    if _DAILY_RUNS_COUNT >= 10:
        return {
            "success": False,
            "error": "LLM RATE LIMIT TRIGGERED: Max 10 Orchestrator runs per day allowed for Agent tools.",
        }

    _DAILY_RUNS_COUNT += 1

    # Build command via shared workflow envelope
    from src.workflows.commands import WorkflowCommandEnvelope

    try:
        envelope = WorkflowCommandEnvelope.from_backtest_request(
            market=market,
            model_type=model_type,
            profile_path=profile_path,
            mode="train" if mode == "run" else "rebacktest",
            tag=tag or None,
            strategy_template=strategy_template or None,
        )
        cmd = envelope.to_argv(python_exe="python")
    except ValueError as e:
        return {"success": False, "error": f"Unsupported orchestrator mode '{mode}': {e}"}

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        res = {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

        if not res["success"]:
            event = classify_failure(
                component="tools.orchestrator_tools",
                operation="run_orchestrator",
                stderr=res["stderr"],
                returncode=res["returncode"],
                context={
                    "market": market,
                    "mode": mode,
                    "model_type": model_type,
                    "profile_path": profile_path,
                },
            )
            append_failure_event(event)
            res["event"] = event.to_dict()

        return res
    except Exception as e:
        event = classify_failure(
            component="tools.orchestrator_tools",
            operation="run_orchestrator",
            exc=e,
            context={"market": market, "mode": mode},
        )
        append_failure_event(event)
        return {"success": False, "error": str(e), "event": event.to_dict()}
