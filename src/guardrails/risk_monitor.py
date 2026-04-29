import os

import requests

# Risk Agent configuration as per AGENTS.md
MAX_DRAWDOWN_THRESHOLD = 0.15
API_BASE = "http://localhost:8000/api"


def check_backtest_risk(run_id, metrics):
    """
    Simulates a Risk Agent audit of a running/finished backtest.
    If MDD violates the contract, trigger SYSTEM_PANIC.
    """
    mdd = metrics.get("max_drawdown", 0.0)

    if mdd > MAX_DRAWDOWN_THRESHOLD:
        print(f"!!! RISK VIOLATION: MDD {mdd:.2%} exceeds threshold {MAX_DRAWDOWN_THRESHOLD:.2%}")

        # Triggering the "Red Button"
        try:
            username = os.getenv("TRADING_UI_USER")
            password = os.getenv("TRADING_UI_PASSWORD")
            if not username or not password:
                print(
                    "Error: TRADING_UI_USER or TRADING_UI_PASSWORD not set. Cannot trigger panic."
                )
                return False

            auth = (username, password)
            resp = requests.post(
                f"{API_BASE}/system/panic",
                json={"reason": f"Risk Agent halt: Run {run_id} violated MDD contract ({mdd:.2%})"},
                auth=auth,
            )
            if resp.status_code == 200:
                print(">>> SYSTEM_PANIC triggered successfully. All jobs halted.")
                return True
        except Exception as e:
            print(f"Failed to trigger Panic Stop: {str(e)}")

    return False


if __name__ == "__main__":
    # Example check for a run
    sample_metrics = {"max_drawdown": 0.18, "annualized_return": 0.22}
    check_backtest_risk("test_run_001", sample_metrics)
