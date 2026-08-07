#!/usr/bin/env python3
"""Refresh the active QQQ Rotation v4.3 formal package through a new cutoff."""
from __future__ import annotations

import argparse
import math
from collections.abc import Mapping
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import yaml

from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.artifacts.qqq_v4_3_formal import JOINT_STRATEGY, MODEL_ID, build_formal_package
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison


class QqqV43RefreshError(FormalRefreshError):
    """Raised when the accepted v4.3 package cannot be reproduced exactly."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _report_prefix(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = package.get("report")
    if not isinstance(rows, list) or not rows:
        raise QqqV43RefreshError("current v4.3 report is missing")
    return {
        str(row["date"]): row
        for row in rows
        if isinstance(row, Mapping) and row.get("date")
    }


def _verify_historical_prefix(
    current: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    old = _report_prefix(current)
    new = _report_prefix(candidate)
    fields = (
        "period_return",
        "gross_return",
        "transaction_cost",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "weight_SGOV",
        "position_state",
    )
    for date, prior in old.items():
        refreshed = new.get(date)
        if refreshed is None:
            raise QqqV43RefreshError(f"v4.3 historical row disappeared: {date}")
        for field in fields:
            if field not in prior:
                continue
            left = prior[field]
            right = refreshed.get(field)
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                if right is None or not math.isclose(
                    float(left), float(right), rel_tol=0.0, abs_tol=1e-10
                ):
                    raise QqqV43RefreshError(
                        f"v4.3 historical overlap changed on {date}: {field}"
                    )
            elif left != right:
                raise QqqV43RefreshError(
                    f"v4.3 historical overlap changed on {date}: {field}"
                )


def refresh(
    *,
    current_package: Path,
    bundle_dir: Path,
    bridge_contract_path: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    current = load_object(current_package)
    if current.get("model_id") != MODEL_ID:
        raise QqqV43RefreshError("QQQ refresh requires the accepted v4.3 package")

    contract = yaml.safe_load(bridge_contract_path.read_text(encoding="utf-8"))
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
        start=contract["data"]["start_date"],
        end=cutoff,
        bundle_dir=bundle_dir,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=cutoff)
    _, results, diagnostics = run_v4_33_comparison(
        bars,
        contract,
        fear_greed,
        cash_symbol="SGOV",
    )
    result = results[JOINT_STRATEGY]
    latest_economic = result.daily.index.max().date().isoformat()
    evidence = _json_safe(
        {
            **dict(current.get("evidence") or {}),
            "refresh_adapter": "refresh_qqq_v4_3_formal",
            "refresh_source_package_sha256": sha256(current_package),
            "baseline_contract_path": bridge_contract_path.as_posix(),
            "baseline_contract_sha256": sha256(bridge_contract_path),
            "bundle_manifest_sha256": sha256(bundle_dir / "bundle_manifest.json"),
            "data_identity": data_identity,
            "coverage": coverage.to_dict("records"),
            "retrospective_diagnostics": diagnostics,
            "model_selection_reopened": False,
        }
    )
    freshness = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": latest_economic,
        "model_selection_reopened": False,
        "data_bundle_id": data_identity.get("bundle_id"),
        "research_only": True,
        "trade_ready": False,
    }
    candidate = _json_safe(
        build_formal_package(
            result,
            bars,
            generated_at=generated_at,
            evidence_cutoff=cutoff,
            backtest_id=f"{MODEL_ID}-through-{cutoff.replace('-', '_')}",
            evidence=evidence,
            freshness=freshness,
        )
    )
    _verify_historical_prefix(current, candidate)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_object(output, candidate)
    return {
        "model_id": MODEL_ID,
        "status": "refreshed",
        "evidence_cutoff": cutoff,
        "economic_end": latest_economic,
        "output_sha256": sha256(output),
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-package", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument(
        "--bridge-contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
    )
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = refresh(
        current_package=args.current_package,
        bundle_dir=args.bundle_dir,
        bridge_contract_path=args.bridge_contract,
        cutoff=args.cutoff,
        generated_at=args.generated_at,
        output=args.output,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
