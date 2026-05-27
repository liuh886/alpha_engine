import threading

import qlib

from src.common.logging import get_logger

logger = get_logger(__name__)

_qlib_lock = threading.Lock()
_initialized_regions = set()


def ensure_qlib_init(provider_uri: str, region: str = "cn"):
    """
    Ensures Qlib is initialized only once per region within a single process.
    Thread-safe implementation for MCP/API server environments.
    """
    global _initialized_regions

    with _qlib_lock:
        cache_key = f"{provider_uri}_{region}"
        if cache_key in _initialized_regions:
            return True

        logger.info("Initializing Qlib", region=region, provider_uri=str(provider_uri))
        try:
            # If Qlib was already initialized by another call with same settings,
            # qlib.init is usually fast but we skip it entirely to be sure.
            qlib.init(provider_uri=str(provider_uri), region=region)
            _initialized_regions.add(cache_key)
            logger.info("Qlib initialized successfully")
            return True
        except Exception as e:
            logger.error("Qlib initialization failed", error=str(e))
            return False


def get_qlib_status():
    """Returns a summary of initialized Qlib instances."""
    return list(_initialized_regions)
