import os

import requests

from src.common.logging import get_logger
from src.common.runtime_settings import get_runtime_settings

logger = get_logger(__name__)

MAX_DRAWDOWN_THRESHOLD = float(os.environ.get("ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD", "0.15"))


def _api_base() -> str:
    settings = get_runtime_settings()
    host = settings.api_host if settings.api_host != "0.0.0.0" else "localhost"
    return f"http://{host}:{settings.api_port}/api"


def check_backtest_risk(run_id, metrics):
    """
    Simulates a Risk Agent audit of a running/finished backtest.
    If MDD violates the contract, trigger SYSTEM_PANIC.
    """
    mdd = metrics.get("max_drawdown", 0.0)

    if mdd > MAX_DRAWDOWN_THRESHOLD:
        logger.warning(
            "Risk violation: MDD exceeds threshold", mdd=mdd, threshold=MAX_DRAWDOWN_THRESHOLD
        )

        # Triggering the "Red Button"
        try:
            settings = get_runtime_settings()
            username = settings.trading_ui_user
            password = settings.trading_ui_password
            if not username or not password:
                logger.error("TRADING_UI_USER or TRADING_UI_PASSWORD not set; cannot trigger panic")
                return False

            auth = (username, password)
            resp = requests.post(
                f"{_api_base()}/system/panic",
                json={"reason": f"Risk Agent halt: Run {run_id} violated MDD contract ({mdd:.2%})"},
                auth=auth,
            )
            if resp.status_code == 200:
                logger.info("SYSTEM_PANIC triggered successfully; all jobs halted")
                return True
        except Exception as e:
            logger.error("Failed to trigger panic stop", error=str(e))

    return False


if __name__ == "__main__":
    # Example check for a run
    sample_metrics = {"max_drawdown": 0.18, "annualized_return": 0.22}
    check_backtest_risk("test_run_001", sample_metrics)
