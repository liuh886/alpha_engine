from __future__ import annotations

import os

from src.common.market import get_region_for_market
from src.common.paths import MLRUNS_DIR


def build_qlib_init_cfg(base_cfg: dict | None, *, market: str, provider_uri_default: str = "data/watchlist") -> dict:
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


def safe_qlib_init(cfg: dict) -> None:
    import qlib

    try:
        qlib.init(**cfg)
    except Exception:
        # Qlib is usually a singleton; repeat initialization can raise depending on version.
        pass

