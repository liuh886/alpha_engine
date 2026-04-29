from typing import Any

from .error_codes import (
    ERR_BACKTEST_ARTIFACT_MISSING,
    ERR_DATA_GAP,
    ERR_MODEL_MISSING,
    ERR_PROVIDER_TIMEOUT,
    ERR_QLIB_INIT_CONFLICT,
)
from .events import ReliabilityEvent


class GovernanceReliabilityPolicy:
    """
    确定针对不同可靠性事件应采取的自动化自愈动作。
    """

    def resolve_action(self, event: ReliabilityEvent) -> dict[str, Any]:
        code = event.code

        # 默认策略映射 (Phase 4 Reliability Contract)
        if code == ERR_DATA_GAP.code:
            return {
                "action": "refresh_data_then_retry",
                "target_market": event.market,
                "notes": "Triggering data update before retrying original operation.",
            }
        elif code == ERR_PROVIDER_TIMEOUT.code:
            return {
                "action": "retry_with_exponential_backoff",
                "notes": "Provider timed out, scheduling retry.",
            }
        elif code == ERR_MODEL_MISSING.code:
            return {
                "action": "escalate_to_operator",
                "notes": f"Critical model missing: {event.model_path}. Cannot auto-fix without retraining.",
            }
        elif code == ERR_QLIB_INIT_CONFLICT.code:
            return {
                "action": "isolate_process",
                "notes": "Qlib initialization conflict detected. Switching to subprocess isolation.",
            }
        elif code == ERR_BACKTEST_ARTIFACT_MISSING.code:
            return {
                "action": "rebuild_reports",
                "notes": "Backtest finished but artifacts missing. Re-running report generator.",
            }

        # 默认动作
        return {
            "action": "none" if not event.retryable else "retry",
            "notes": "No specialized self-healing policy defined for this error code.",
        }
