from typing import Any, Dict, Optional
from .error_codes import ERR_PIPELINE_SUBPROCESS_FAILED, ERR_MODEL_MISSING, ERR_DATA_GAP, ERR_PROVIDER_TIMEOUT, CODES
from .events import ReliabilityEvent

def classify_failure(
    *,
    component: str,
    operation: str = "unknown",
    exc: Optional[Exception] = None,
    stderr: str = "",
    returncode: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None
) -> ReliabilityEvent:
    """
    根据异常、标准错误或退出码，将原始失败归类为结构化的可靠性事件。
    """
    context = context or {}
    code_obj = ERR_PIPELINE_SUBPROCESS_FAILED
    summary = str(exc) if exc else (stderr[:200] if stderr else "Unknown subprocess failure")
    
    # 规则解析
    if exc:
        if isinstance(exc, FileNotFoundError):
            if "pkl" in str(exc) or "model" in str(exc):
                code_obj = ERR_MODEL_MISSING
            else:
                code_obj = ERR_DATA_GAP
        elif "timeout" in str(exc).lower():
            code_obj = ERR_PROVIDER_TIMEOUT
            
    if stderr:
        low_stderr = stderr.lower()
        if "empty universe" in low_stderr or "no tickers" in low_stderr:
            code_obj = ERR_DATA_GAP
        elif "qlib data" in low_stderr and "not found" in low_stderr:
            code_obj = ERR_DATA_GAP
        elif "already initialized" in low_stderr:
            from .error_codes import ERR_QLIB_INIT_CONFLICT
            code_obj = ERR_QLIB_INIT_CONFLICT

    event = ReliabilityEvent(
        code=code_obj.code,
        category=code_obj.category,
        severity=code_obj.severity,
        retryable=code_obj.retryable,
        component=component,
        operation=operation,
        summary=summary,
        details={
            "stderr_tail": stderr[-500:] if stderr else "",
            "returncode": returncode,
            "exception_type": type(exc).__name__ if exc else None
        },
        **{k: v for k, v in context.items() if hasattr(ReliabilityEvent, k)}
    )
    
    # 填充默认治理动作建议
    event.governance_action = {
        "action": code_obj.default_action,
        "status": "pending",
        "notes": f"Detected via classification rules for {code_obj.code}"
    }
    
    return event
