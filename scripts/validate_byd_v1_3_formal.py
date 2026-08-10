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

BASELINE_METRIC_TOLERANCE = 1e-6


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
    champion = contract["champion"]
    if contract["candidate_id"] != MODEL_ID:
        raise ValueError("candidate_id does not match implementation")
    if champion["model_id"] != V12_MODEL_ID:
        raise ValueError("champion model does not match maintained V1.2")
    if champion["frozen_evidence_cutoff"] != contract["immutable_data"]["cutoff"]:
        raise ValueError("champion and challenge evidence cutoffs differ")
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


def _load_frozen_champion_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    champion = contract["champion"]
    receipt_path = Path(champion["frozen_receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    baseline = receipt.get("baseline")
    if not isinstance(baseline, dict):
        raise RuntimeError("frozen champion receipt lacks baseline identity")
    expected = {
        "model_version_id": champion["model_id"],
        "bundle_id": champion["frozen_bundle_id"],
        "manifest_sha256": champion["frozen_manifest_sha256"],
        "evidence_cutoff": champion["frozen_evidence_cutoff"],
    }
    for key, value in expected.items():
        if baseline.get(key) != value:
            raise RuntimeError(
                f"frozen champion receipt mismatch for {key}: "
                f"{baseline.get(key)!r} != {value!r}"
            )
    if receipt.get("decision") != "formal_baseline_bound":
        raise RuntimeError("frozen champion receipt is not a formal baseline binding")
    return receipt


def _verify_frozen_baseline(
    champion_receipt: dict[str, Any],
    baseline_daily: pd.DataFrame,
) -> dict[str, Any]:
    """Verify the 2026-08-03 rebuilt V1.2 against its immutable bundle receipt.

    The receipt is the durable Research Loop identity for the historical
    champion bundle. Its metrics can differ from the raw research evaluator by
    sub-ppm serialization/annualization precision, so the comparison uses a
    fixed numerical tolerance while model decisions themselves are reused
    directly from maintained V1.2 code.
    """
    from src.research.byd_515180_allocation import metrics

    observed = metrics(baseline_daily)
    frozen = champion_receipt["baseline"]
    published = frozen["metrics"]
    expected = {
        "cagr": float(published["annualized_return"]),
        "sharpe": float(published["sharpe_ratio"]),
        "max_drawdown": float(published["max_drawdown"]),
        "total_return": float(published["total_return"]),
    }
    deltas: dict[str, float] = {}
    for key, expected_value in expected.items():
        observed_value = float(observed[key])
        deltas[key] = observed_value - expected_value
        if not math.isclose(
            observed_value,
            expected_value,
            rel_tol=0.0,
            abs_tol=BASELINE_METRIC_TOLERANCE,
        ):
            raise RuntimeError(
                f"frozen V1.2 champion mismatch for {key}: "
                f"{observed_value} != {expected_value}"
            )
    return {
        "bundle_id": frozen["bundle_id"],
        "manifest_sha256": frozen["manifest_sha256"],
        "evidence_cutoff": frozen["evidence_cutoff"],
        "observed_metrics": {key: float(observed[key]) for key in expected},
        "receipt_metrics": expected,
        "metric_deltas": deltas,
        "absolute_tolerance": BASELINE_METRIC_TOLERANCE,
    }


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

    # The rolling formal package can advance beyond the frozen 2026-08-03
    # challenge cutoff. It proves that V1.2 is still the currently published
    # champion, while the immutable onboarding receipt below owns the exact
    # historical identity used for challenger comparison.
    formal_package = json.loads(args.formal_package.read_text(encoding="utf-8"))
    if formal_package.get("model_id") != V12_MODEL_ID:
        raise RuntimeError("rolling formal package is not the current BYD v1.2 champion")
    champion_receipt = _load_frozen_champion_receipt(contract)

    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    primary, stress = run_primary_and_stress(common, signals)
    baseline_identity = _verify_frozen_baseline(
        champion_receipt, primary[V12_MODEL_ID].daily
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
        "rolling_formal_package": args.formal_package.as_posix(),
        "frozen_champion_receipt": contract["champion"]["frozen_receipt"],
        "frozen_champion_bundle_id": contract["champion"]["frozen_bundle_id"],
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
