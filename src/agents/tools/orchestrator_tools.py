import subprocess
from typing import Any
import time

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
            "error": "LLM RATE LIMIT TRIGGERED: Max 10 Orchestrator runs per day allowed for Agent tools."
        }
        
    _DAILY_RUNS_COUNT += 1
    
    cmd = [
        "python", "-m", "src.orchestrator",
        mode,
        "--market", market,
        "--model_type", model_type,
        "--profile", profile_path,
    ]
    if tag:
        cmd.extend(["--tag", tag])
    if strategy_template:
        cmd.extend(["--strategy_template", strategy_template])
        
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
