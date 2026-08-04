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
from src.research.v4_18_state_specific_residual_actions import (
    run_state_specific_research,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_state_specific_residual_actions_v4_18_research.yaml"
)
DEFAULT_V417_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_state_conditioned_action_advantage_v4_17_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_tqqq_sgov_voo_state_specific_residual_actions_v4_18_research"
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
    if not checks["all_state_models_fitted"]:
        return "state_specific_training_coverage_incomplete"
    if not checks["model_gate"]:
        return "state_specific_residual_model_not_stable"
    if not checks["portfolio_gate"]:
        return "state_specific_residual_policy_does_not_beat_v4_2_oof"
    if not checks["actual_contradiction_gate"]:
        return "state_specific_residual_policy_blocked_by_actual_contradiction"
    if not checks["v4_17_improvement_gate"]:
        return "state_specific_models_do_not_materially_improve_v4_17"
    return "state_specific_residual_policy_prospective_shadow_supported"


def _save_model(prefix: str, model: Any, output: Path) -> None:
    model.frame.reset_index().to_csv(output / f"{prefix}_feature_label_frame.csv", index=False)
    model.oof_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_oof_predictions.csv", index=False
    )
    model.fold_coefficients.to_csv(output / f"{prefix}_fold_coefficients.csv", index=False)
    model.actual_coefficients.to_csv(output / f"{prefix}_actual_coefficients.csv", index=False)
    model.action_metrics.to_csv(output / f"{prefix}_action_metrics.csv", index=False)
    model.oof_events.to_csv(output / f"{prefix}_oof_events.csv", index=False)
    model.actual_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_actual_predictions.csv", index=False
    )
    model.actual_events.to_csv(output / f"{prefix}_actual_events.csv", index=False)


def _save_policy(prefix: str, policy: Any, output: Path) -> None:
    policy.oof_headline.reset_index().to_csv(output / f"{prefix}_oof_headline.csv", index=False)
    policy.actual_headline.reset_index().to_csv(output / f"{prefix}_actual_headline.csv", index=False)
    policy.oof_action_trace.reset_index(names="date").to_csv(
        output / f"{prefix}_oof_action_trace.csv", index=False
    )
    policy.actual_action_trace.reset_index(names="date").to_csv(
        output / f"{prefix}_actual_action_trace.csv", index=False
    )
    policy.oof_attribution.to_csv(output / f"{prefix}_oof_attribution.csv", index=False)
    policy.actual_attribution.to_csv(output / f"{prefix}_actual_attribution.csv", index=False)
    for scope, strategies in (("oof", policy.oof_results), ("actual", policy.actual_results)):
        for strategy, strategy_result in strategies.items():
            strategy_result.daily.reset_index(names="date").to_csv(
                output / f"{prefix}_{scope}_{strategy}_daily.csv", index=False
            )
            strategy_result.trades.to_csv(
                output / f"{prefix}_{scope}_{strategy}_trades.csv", index=False
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--v4-17-contract", type=Path, default=DEFAULT_V417_CONTRACT)
    parser.add_argument("--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    v417_contract = yaml.safe_load(args.v4_17_contract.read_text(encoding="utf-8"))
    bridge_contract = yaml.safe_load(args.bridge_contract.read_text(encoding="utf-8"))
    symbols = [str(value) for value in contract["data"]["required_symbols"]]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=str(contract["data"]["start_date"]),
        end=args.end_date or contract["data"].get("end_date"),
    )
    _, actual_results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    _, proxy_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    result = run_state_specific_research(
        bars,
        proxy_results[BASELINE_KEY].daily,
        actual_results[BASELINE_KEY].daily,
        contract,
        v417_contract,
    )
    decision = _decision(result)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    _save_model("state_specific", result.state_specific_model, output)
    _save_policy("state_specific", result.state_specific_policy, output)
    result.action_state_metrics.to_csv(output / "action_state_metrics.csv", index=False)
    result.state_coefficient_stability.to_csv(
        output / "state_coefficient_stability.csv", index=False
    )
    comparator = result.state_conditioned_comparator
    _save_model("v4_17", comparator.state_model, output)
    _save_policy("v4_17", comparator.state_policy, output)
    _save_model("v4_16", comparator.unconditioned_model, output)
    _save_policy("v4_16", comparator.unconditioned_policy, output)

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "state_specific_model_gate": result.state_specific_model.model_gate,
        "state_specific_portfolio_gate": result.state_specific_policy.portfolio_gate,
        "state_specific_actual_contradiction_gate": result.state_specific_policy.contradiction_gate,
        "v4_17_improvement_gate": result.improvement_gate,
        "final_gate": result.final_gate,
        "v4_17_model_gate": comparator.state_model.model_gate,
        "v4_17_portfolio_gate": comparator.state_policy.portfolio_gate,
        "v4_16_model_gate": comparator.unconditioned_model.model_gate,
        "shadow_candidate_authorized": bool(result.final_gate["passed"]),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "v4_17_contract_path": str(args.v4_17_contract),
        "v4_17_contract_sha256": _sha256(args.v4_17_contract),
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
                    "model_gate": result.state_specific_model.model_gate,
                    "portfolio_gate": result.state_specific_policy.portfolio_gate,
                    "actual_gate": result.state_specific_policy.contradiction_gate,
                    "improvement_gate": result.improvement_gate,
                    "final_gate": result.final_gate,
                    "oof_events": len(result.state_specific_model.oof_events),
                    "actual_events": len(result.state_specific_model.actual_events),
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
