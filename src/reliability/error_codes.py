from dataclasses import dataclass

@dataclass(frozen=True)
class ReliabilityCode:
    code: str
    category: str
    retryable: bool
    severity: str
    default_action: str

# 定义统一错误码 (Phase 4 Reliability Contract v1)
ERR_DATA_GAP = ReliabilityCode("ERR_DATA_GAP", "data", True, "high", "refresh_data_then_retry")
ERR_PROVIDER_TIMEOUT = ReliabilityCode("ERR_PROVIDER_TIMEOUT", "provider", True, "medium", "retry_with_backoff")
ERR_PROVIDER_PAYLOAD_INVALID = ReliabilityCode("ERR_PROVIDER_PAYLOAD_INVALID", "provider", True, "medium", "rotate_provider")
ERR_FEATURE_DRIFT = ReliabilityCode("ERR_FEATURE_DRIFT", "features", False, "high", "recompute_alignment")
ERR_MODEL_STALE = ReliabilityCode("ERR_MODEL_STALE", "model", False, "high", "schedule_retrain")
ERR_MODEL_MISSING = ReliabilityCode("ERR_MODEL_MISSING", "model", False, "high", "resolve_from_registry")
ERR_BACKTEST_CACHE_MISS = ReliabilityCode("ERR_BACKTEST_CACHE_MISS", "cache", False, "low", "compute_and_populate")
ERR_BACKTEST_ARTIFACT_MISSING = ReliabilityCode("ERR_BACKTEST_ARTIFACT_MISSING", "artifacts", True, "medium", "rebuild_artifacts")
ERR_QLIB_INIT_CONFLICT = ReliabilityCode("ERR_QLIB_INIT_CONFLICT", "runtime", True, "medium", "reroute_to_isolated_process")
ERR_PIPELINE_SUBPROCESS_FAILED = ReliabilityCode("ERR_PIPELINE_SUBPROCESS_FAILED", "runtime", True, "medium", "classify_and_retry")
ERR_GOVERNANCE_STORAGE_UNAVAILABLE = ReliabilityCode("ERR_GOVERNANCE_STORAGE_UNAVAILABLE", "governance", True, "medium", "fallback_to_json_log")

CODES = {
    c.code: c for c in [
        ERR_DATA_GAP, ERR_PROVIDER_TIMEOUT, ERR_PROVIDER_PAYLOAD_INVALID,
        ERR_FEATURE_DRIFT, ERR_MODEL_STALE, ERR_MODEL_MISSING,
        ERR_BACKTEST_CACHE_MISS, ERR_BACKTEST_ARTIFACT_MISSING,
        ERR_QLIB_INIT_CONFLICT, ERR_PIPELINE_SUBPROCESS_FAILED,
        ERR_GOVERNANCE_STORAGE_UNAVAILABLE
    ]
}
