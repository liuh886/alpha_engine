import os
import subprocess
import time
from collections.abc import Callable
from typing import Any


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
                        raise Exception(f"Pipeline error: {result.get('error', 'Unknown returncode')}")
                    return result
                except Exception as e:
                    last_err = e
                    print(f"[Robustness] Attempt {attempt + 1}/{max_retries} failed for {func.__name__}. Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= backoff_factor
            return {"success": False, "error": f"Max retries ({max_retries}) exceeded: {str(last_err)}"}
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
        script_path = "scripts/update_data.py" if os.path.exists("scripts/update_data.py") else "src/data/fetch_watchlist.py"
        cmd = ["python", script_path, "--market", market]
        
        # Adding a strict timeout to prevent hanging data pipelines
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode
        }
        
    try:
        return _execute()
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Subprocess execution timed out."}
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
