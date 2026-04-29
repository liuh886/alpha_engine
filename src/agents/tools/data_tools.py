import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

from src.reliability.classifier import classify_failure
from src.reliability.failure_log import append_failure_event


def with_retry(max_retries: int = 3, backoff_factor: float = 1.5):
    """Robust exponential backoff retry decorator for external IO bounds."""

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            last_err = None
            delay = 1.0
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    # For our subprocess wrapper pattern, check inner success
                    if isinstance(result, dict) and not result.get("success"):
                        # If it has an event, we might not want to retry certain errors
                        # but for now keep legacy retry behavior
                        raise Exception(
                            f"Pipeline error: {result.get('error', 'Unknown returncode')}"
                        )
                    return result
                except Exception as e:
                    last_err = e
                    print(
                        f"[Robustness] Attempt {attempt + 1}/{max_retries} failed for {func.__name__}. Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= backoff_factor

            # If we reach here, it's a final failure
            # Classify it
            event = classify_failure(
                component="tools.data_tools",
                operation=func.__name__,
                exc=last_err,
                context={"max_attempts": max_retries},
            )
            append_failure_event(event)

            return {
                "success": False,
                "error": f"Max retries ({max_retries}) exceeded: {str(last_err)}",
                "event": event.to_dict(),
            }

        return wrapper

    return decorator


def run_data_update(market: str = "cn") -> dict[str, Any]:
    """
    Run the data update pipeline for a specific market to fetch the latest prices and fundamentals.

    Args:
        market: Which market to update ('cn' or 'us').

    Returns:
        dict: Containing execution status and output logs.
    """

    @with_retry(max_retries=3, backoff_factor=2)
    def _execute():
        script_path = (
            "scripts/update_data.py"
            if os.path.exists("scripts/update_data.py")
            else "src/data/fetch_watchlist.py"
        )
        cmd = ["python", script_path, "--market", market]

        # Adding a strict timeout to prevent hanging data pipelines
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            res = {
                "success": result.returncode == 0,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
                "returncode": result.returncode,
            }

            if not res["success"]:
                event = classify_failure(
                    component="tools.data_tools",
                    operation="run_data_update",
                    stderr=res["stderr"],
                    returncode=res["returncode"],
                    context={"market": market},
                )
                res["event"] = event.to_dict()
                # We don't append to log here yet, let decorator handle final failure or
                # keep it for immediate visibility

            return res
        except subprocess.TimeoutExpired as e:
            event = classify_failure(
                component="tools.data_tools",
                operation="run_data_update",
                exc=e,
                context={"market": market, "timeout": 600},
            )
            return {
                "success": False,
                "error": "Subprocess execution timed out.",
                "event": event.to_dict(),
            }

    try:
        return _execute()
    except Exception as e:
        # Final fallback for unexpected errors
        event = classify_failure(
            component="tools.data_tools",
            operation="run_data_update",
            exc=e,
            context={"market": market},
        )
        append_failure_event(event)
        return {"success": False, "error": str(e), "event": event.to_dict()}
