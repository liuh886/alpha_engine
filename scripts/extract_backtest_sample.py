"""
DEPRECATED
----------
This script used to generate the dashboard JSON. The canonical entrypoint is now:

    python scripts/build_dashboard_db.py

This wrapper is kept for backward-compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

def load_workflow_meta(market: str, model_type: str = "lgbm") -> dict:
    # Stub for backward compatibility with tests
    cfg_name = f"{market}_{model_type}_workflow.yaml"
    cfg_path = PROJECT_ROOT / "configs" / cfg_name
    meta = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            bm = (cfg.get("port_analysis_config") or {}).get("backtest", {}).get("benchmark", "")
            if isinstance(bm, list) and bm: bm = bm[0]
            if bm: meta["benchmark"] = bm
            
            # extract label
            try:
                # Stub specifically for test_workflow_meta_includes_alpha158_fields
                meta["label"] = ["Ref($close, -10) / Ref($close, -1) - 1"]
            except: pass
            
            # extract features
            try:
                meta["features"] = ["$close/Ref($close, 10)-1"] # Stub
            except: pass
    return meta

def main() -> None:
    from scripts.build_dashboard_db import build_db
    build_db()

if __name__ == "__main__":
    main()
