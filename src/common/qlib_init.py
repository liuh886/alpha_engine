from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from typing import Any

from src.common.logging import get_logger
from src.common.market import get_region_for_market
from src.common.paths import MLRUNS_DIR

logger = get_logger(__name__)

# Cache: track which market/provider pair has been initialized to avoid redundant calls.
_initialized_key: tuple[str, str] | None = None
_list_instruments_original: Callable[..., Any] | None = None


def build_qlib_init_cfg(
    base_cfg: dict | None, *, market: str, provider_uri_default: str = "data/watchlist"
) -> dict:
    cfg = dict(base_cfg or {})
    cfg.setdefault("provider_uri", provider_uri_default)
    cfg.setdefault("region", get_region_for_market(market))

    # Configure MLflow experiment manager to use our centralized artifacts/mlruns directory
    exp_manager_cfg = {
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {
            "uri": "sqlite:///" + str((MLRUNS_DIR.parent / "mlflow.db").resolve().as_posix()),
            "default_exp_name": f"workflow_{market}",
        },
    }
    cfg.setdefault("exp_manager", exp_manager_cfg)

    if os.name == "nt":
        cfg.setdefault("kernels", 1)
        cfg.setdefault("joblib_backend", "threading")

    return cfg


def _market_from_cfg(cfg: dict) -> str:
    exp_manager = cfg.get("exp_manager", {})
    if not isinstance(exp_manager, dict):
        return ""
    kwargs = exp_manager.get("kwargs", {})
    if not isinstance(kwargs, dict):
        return ""
    exp_name = str(kwargs.get("default_exp_name", ""))
    return exp_name.removeprefix("workflow_") if exp_name.startswith("workflow_") else ""


def _provider_from_cfg(cfg: dict) -> str:
    provider = cfg.get("provider_uri", "")
    if isinstance(provider, dict):
        return repr(sorted((str(key), str(value)) for key, value in provider.items()))
    return str(provider)


def _install_list_instruments_compat() -> None:
    """Bridge AlphaEngine's legacy ``level=`` calls across pyqlib versions.

    Current pyqlib exposes ``freq`` and ``as_list`` rather than the historical
    ``level`` keyword.  The bridge activates only when the installed signature
    lacks ``level`` and a caller actually supplies it.  New-style calls retain
    their original behaviour.
    """
    global _list_instruments_original

    from qlib.data import D

    current = D.list_instruments
    try:
        parameters = inspect.signature(current).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "level" in parameters or getattr(current, "_alpha_engine_level_compat", False):
        return

    _list_instruments_original = current

    def list_instruments_compat(
        instruments: Any,
        *args: Any,
        level: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if level is not None:
            kwargs.setdefault("as_list", True)
        assert _list_instruments_original is not None
        return _list_instruments_original(instruments, *args, **kwargs)

    setattr(list_instruments_compat, "_alpha_engine_level_compat", True)
    D.list_instruments = list_instruments_compat


def safe_qlib_init(cfg: dict) -> None:
    """Initialize Qlib and install narrow cross-version compatibility bridges.

    Initialization is cached by both market and provider URI.  This prevents a
    test or notebook from silently reusing a different data provider merely
    because it shares the same market key.
    """
    global _initialized_key

    import qlib

    market = _market_from_cfg(cfg)
    provider = _provider_from_cfg(cfg)
    init_key = (market, provider)

    if init_key == _initialized_key:
        _install_list_instruments_compat()
        return

    try:
        qlib.init(**cfg)
        _initialized_key = init_key
        _install_list_instruments_compat()
    except Exception:
        logger.debug("Qlib init raised (likely singleton re-initialization)", exc_info=True)
        # Even when Qlib rejects a redundant init, its provider may already be
        # usable; install the API bridge without pretending the new key loaded.
        _install_list_instruments_compat()
