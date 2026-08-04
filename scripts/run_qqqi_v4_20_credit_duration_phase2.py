from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.v4_20_credit_duration_action_policy import (
    run_credit_duration_phase2,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_credit_duration_action_policy_v4_20_research.yaml"
)
DEFAULT_V416_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_credit_duration_action_policy_v4_20_research"
)
BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision(result: Any) -> str:
    checks = result.final_gate["checks"]
    if not checks["ranking_gate"]:
        return "credit_duration_phase2_ranking_gate_failed"
    if not checks["calibration_gate"]:
        return "credit_duration_phase2_calibration_gate_failed"
    if not checks["event_gate"]:
        return "credit_duration_phase2_event_gate_failed"
    if not checks["portfolio_gate"]:
        return "credit_duration_phase2_portfolio_gate_failed"
    if not checks["actual_contradiction_gate"]:
        return "credit_duration_phase2_actual_contradiction"
    return "credit_duration_phase2_prospective_shadow_supported"


def _save_model(prefix: str, model: Any, output: Path) -> None:
    model.oof_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_oof_predictions.csv", index=False
    )
    model.fold_coefficients.to_csv(
        output / f"{prefix}_fold_coefficients.csv", index=False
    )
    model.action_metrics.to_csv(
        output / f"{prefix}_action_metrics.csv", index=False
    )
    model.oof_events.to_csv(output / f"{prefix}_oof_events.csv", index=False)
    model.actual_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_actual_predictions.csv", index=False
    )
    model.actual_events.to_csv(
        output / f"{prefix}_actual_events.csv", index=False
    )
    model.actual_coefficients.to_csv(
        output / f"{prefix}_actual_coefficients.csv", index=False
    )


def _save_policy(prefix: str, policy: Any, output: Path) -> None:
    policy.oof_headline.reset_index().to_csv(
        output / f"{prefix}_oof_headline.csv", index=False
    )
    policy.actual_headline.reset_index().to_csv(
        output / f"{prefix}_actual_headline.csv", index=False
    )
    policy.oof_action_trace.reset_index(names="date").to_csv(
        output / f"{prefix}_oof_action_trace.csv", index=False
    )
    policy.actual_action_trace.reset_index(names="date").to_csv(
        output / f"{prefix}_actual_action_trace.csv", index=False
    )
    policy.oof_attribution.to_csv(
        output / f"{prefix}_oof_attribution.csv", index=False
    )
    policy.actual_attribution.to_csv(
        output / f"{prefix}_actual_attribution.csv", index=False
    )
    for scope, strategies in (
        ("oof", policy.oof_results),
        ("actual", policy.actual_results),
    ):
        for strategy, strategy_result in strategies.items():
            strategy_result.daily.reset_index(names="date").to_csv(
                output / f"{prefix}_{scope}_{strategy}_daily.csv",
                index=False,
            )
            strategy_result.trades.to_csv(
                output / f"{prefix}_{scope}_{strategy}_trades.csv",
                index=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--v4-16-contract", type=Path, default=DEFAULT_V416_CONTRACT
    )
    parser.add_argument(
        "--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    v416_contract = yaml.safe_load(
        args.v4_16_contract.read_text(encoding="utf-8")
    )
    bridge_contract = yaml.safe_load(
        args.bridge_contract.read_text(encoding="utf-8")
    )
    symbols = [str(value) for value in contract["data"]["required_symbols"]]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=str(contract["data"]["start_date"]),
        end=args.end_date or contract["data"].get("end_date"),
    )
    _, actual_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    _, proxy_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    result = run_credit_duration_phase2(
        bars,
        proxy_results[BASELINE_KEY].daily,
        actual_results[BASELINE_KEY].daily,
        contract,
        v416_contract,
    )
    decision = _decision(result)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    result.frame.reset_index(names="date").to_csv(
        output / "feature_label_frame.csv", index=False
    )
    result.same_row_coverage.to_csv(
        output / "same_row_coverage.csv", index=False
    )
    result.rank_action_metrics.to_csv(
        output / "rank_action_metrics.csv", index=False
    )
    result.rank_action_state_metrics.to_csv(
        output / "rank_action_state_metrics.csv", index=False
    )
    result.rank_fold_metrics.to_csv(
        output / "rank_fold_metrics.csv", index=False
    )
    result.calibration_metrics.to_csv(
        output / "calibration_metrics.csv", index=False
    )
    result.event_metrics.to_csv(output / "event_metrics.csv", index=False)
    result.coefficient_cosines.to_csv(
        output / "candidate_coefficient_cosines.csv", index=False
    )
    _save_model("same_endpoint_v4_16", result.base_model, output)
    _save_model("credit_duration_v4_20", result.candidate_model, output)
    _save_policy("same_endpoint_v4_16", result.base_policy, output)
    _save_policy("credit_duration_v4_20", result.candidate_policy, output)

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "ranking_gate": result.ranking_gate,
        "calibration_gate": result.calibration_gate,
        "event_gate": result.event_gate,
        "portfolio_gate": result.portfolio_gate,
        "actual_contradiction_gate": result.actual_contradiction_gate,
        "final_gate": result.final_gate,
        "shadow_candidate_authorized": bool(result.final_gate["passed"]),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    files = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "v4_16_contract_path": str(args.v4_16_contract),
        "v4_16_contract_sha256": _sha256(args.v4_16_contract),
        "bridge_contract_path": str(args.bridge_contract),
        "bridge_contract_sha256": _sha256(args.bridge_contract),
        "decision": decision,
        "shadow_candidate_authorized": bool(result.final_gate["passed"]),
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _safe(
                {
                    "decision": decision,
                    "ranking_gate": result.ranking_gate,
                    "calibration_gate": result.calibration_gate,
                    "event_gate": result.event_gate,
                    "portfolio_gate": result.portfolio_gate,
                    "actual_contradiction_gate": result.actual_contradiction_gate,
                    "final_gate": result.final_gate,
                    "base_oof_events": len(result.base_model.oof_events),
                    "candidate_oof_events": len(
                        result.candidate_model.oof_events
                    ),
                    "base_actual_events": len(
                        result.base_model.actual_events
                    ),
                    "candidate_actual_events": len(
                        result.candidate_model.actual_events
                    ),
                    "output_dir": str(output),
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
