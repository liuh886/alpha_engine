import os

from src.common.logging import get_logger

logger = get_logger(__name__)

MAX_DRAWDOWN_THRESHOLD = float(os.environ.get("ALPHA_ENGINE_MAX_DRAWDOWN_THRESHOLD", "0.15"))


def check_backtest_risk(run_id, metrics) -> bool:
    """Return ``True`` when a backtest must be blocked by the drawdown guardrail.

    The guardrail is intentionally framework-neutral. Callers must stop the
    current workflow or prevent model promotion when this function returns
    ``True``. The browser product has no execution or emergency-stop authority.
    """

    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    blocked = max_drawdown > MAX_DRAWDOWN_THRESHOLD

    if blocked:
        logger.error(
            "backtest_risk_blocked",
            run_id=str(run_id),
            max_drawdown=max_drawdown,
            threshold=MAX_DRAWDOWN_THRESHOLD,
            action="stop_workflow_or_reject_promotion",
        )
    else:
        logger.info(
            "backtest_risk_accepted",
            run_id=str(run_id),
            max_drawdown=max_drawdown,
            threshold=MAX_DRAWDOWN_THRESHOLD,
        )

    return blocked


if __name__ == "__main__":
    sample_metrics = {"max_drawdown": 0.18, "annualized_return": 0.22}
    raise SystemExit(1 if check_backtest_risk("test_run_001", sample_metrics) else 0)
