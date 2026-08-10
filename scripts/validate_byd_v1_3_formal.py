#!/usr/bin/env python3
"""Reproduce and certify the frozen BYD v1.3 challenger."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.byd_515180_allocation import prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import CANDIDATE as V12_MODEL_ID
from src.research.byd_v1_3_candidate import (
    BEAR_DEFENSE_BYD,
    CONVEX_POWER,
    FULL_INCREMENT_MOMENTUM,
    MAX_FINANCED_INCREMENT,
    MIN_HOLD_SESSIONS,
    MODEL_ID,
    evaluate_challenge,
    run_primary_and_stress,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--formal-package", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-supported", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_contract(contract: dict[str, Any]) -> None:
    delta = contract["frozen_delta"]
    expansion = delta["expansion"]
    if contract["candidate_id"] != MODEL_ID:
        raise ValueError("candidate_id does not match implementation")
    if int(delta["minimum_hold_sessions"]) != MIN_HOLD_SESSIONS:
        raise ValueError("minimum-hold contract mismatch")
    if not math.isclose(float(delta["bear_defense"]["BYD"]), BEAR_DEFENSE_BYD):
        raise ValueError("bear-defense contract mismatch")
    if not math.isclose(
        float(expansion["maximum_financed_increment"]), MAX_FINANCED_INCREMENT
    ):
        raise ValueError("expansion-cap contract mismatch")
    if not math.isclose(
        float(expansion["full_increment_momentum"]), FULL_INCREMENT_MOMENTUM
    ):
        raise ValueError("full-increment momentum contract mismatch")
    if not math.isclose(float(expansion["convex_power"]), CONVEX_POWER):
        raise ValueError("convex-power contract mismatch")


def _verify_formal_baseline(
    formal_package: dict[str, Any],
    baseline_daily: pd.DataFrame,
) -> dict[str, float]:
    from src.research.byd_515180_allocation import metrics

    observed = metrics(baseline_daily)
    published = formal_package["metrics"]
    expected = {
        "cagr": float(published["CAGR"]),
        "sharpe": float(published["Sharpe Ratio"]),
        "max_drawdown": float(published["Max Drawdown"]),
        "total_return": float(published["Total Return"]),
    }
    for key, expected_value in expected.items():
        if not math.isclose(
            float(observed[key]), expected_value, rel_tol=0.0, abs_tol=1e-12
        ):
            raise RuntimeError(
                f"exact formal V1.2 baseline mismatch for {key}: "
                f"{observed[key]} != {expected_value}"
            )
    return {key: float(observed[key]) for key in expected}


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    raise TypeError(f"cannot JSON serialize {type(value).__name__}")


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    _verify_contract(contract)
    formal_package = json.loads(args.formal_package.read_text(encoding="utf-8"))
    if formal_package.get("model_id") != V12_MODEL_ID:
        raise RuntimeError("formal package is not the current BYD v1.2 champion")

    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    primary, stress = run_primary_and_stress(common, signals)
    baseline_identity = _verify_formal_baseline(
        formal_package, primary[V12_MODEL_ID].daily
    )

    gates = contract["formal_gates"]
    result = evaluate_challenge(
        primary,
        stress,
        maximum_cagr_shortfall_pp=float(
            gates["maximum_full_cagr_shortfall_percentage_points"]
        ),
        minimum_drawdown_improvement_pp=float(
            gates["minimum_full_drawdown_improvement_percentage_points"]
        ),
        maximum_round_trips_per_year=float(gates["maximum_round_trips_per_year"]),
        maximum_positive_period_share=float(gates["maximum_positive_period_share"]),
    )

    v12_path = args.output_dir / "v1_2_daily.csv"
    v13_path = args.output_dir / "v1_3_daily.csv"
    comparison_path = args.output_dir / "comparison.csv"
    attribution_path = args.output_dir / "period_attribution.csv"
    decision_path = args.output_dir / "decision.json"

    primary[V12_MODEL_ID].daily.to_csv(v12_path, float_format="%.12f")
    primary[MODEL_ID].daily.to_csv(v13_path, float_format="%.12f")
    result.comparison.to_csv(comparison_path, index=False, float_format="%.12f")
    result.period_attribution.to_csv(
        attribution_path, index=False, float_format="%.12f"
    )

    decision = {
        "schema_version": "1.0",
        "candidate_id": MODEL_ID,
        "champion_id": V12_MODEL_ID,
        "decision": result.decision,
        "promotion_authorized": result.decision == "byd_v1_3_supported",
        "research_only": True,
        "trade_ready": False,
        "fresh_historical_holdout": False,
        "historical_evidence_consumed": True,
        "baseline_identity": baseline_identity,
        "gates": result.gates,
        "failed_gates": [name for name, passed in result.gates.items() if not passed],
        "diagnostics": result.diagnostics,
    }
    decision_path.write_text(
        json.dumps(
            decision,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_safe,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "1.0",
        "candidate_id": MODEL_ID,
        "contract": args.contract.as_posix(),
        "formal_package": args.formal_package.as_posix(),
        "files": {
            path.name: _sha256(path)
            for path in (
                v12_path,
                v13_path,
                comparison_path,
                attribution_path,
                decision_path,
            )
        },
        "immutable_data": contract["immutable_data"],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(decision, ensure_ascii=False, sort_keys=True, default=_json_safe))
    if args.require_supported and result.decision != "byd_v1_3_supported":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
