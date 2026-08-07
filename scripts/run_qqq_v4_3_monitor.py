#!/usr/bin/env python3
"""Evaluate the formal QQQ Rotation v4.3 current-open and next-open targets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.qqq_v4_3_monitor import build_v4_3_monitor_summary
from src.research.vix_rotation_experiment import _normalise_close, config_from_contract
from src.research.vxn_bridge_allocation_experiment import run_bridge_allocation_comparison
from src.research.vxn_leverage_overlay_experiment import generate_vxn_leverage_veto_states


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqq_rotation_v4_3_current_monitor"),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
        start=contract["data"]["start_date"],
        end=args.end_date or contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    _, _, prepared, _ = run_bridge_allocation_comparison(bars, contract)
    decisions = generate_vxn_leverage_veto_states(
        prepared,
        config=config_from_contract(contract),
    )
    fear_greed = fetch_cnn_fear_greed(end_date=args.end_date)
    qqq_close = _normalise_close(bars["QQQ"], "QQQ")
    summary = build_v4_3_monitor_summary(
        prepared,
        decisions,
        fear_greed,
        qqq_close,
        data_identity=data_identity,
    )
    summary["coverage"] = coverage.to_dict("records")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / "current_summary.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    coverage.to_csv(output / "coverage.csv", index=False)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
