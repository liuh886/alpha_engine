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
from src.research.v4_16_action_advantage_runtime import (
    run_action_advantage_model,
    run_action_advantage_policy,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research"
)
BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(table: pd.DataFrame, strategy: str, column: str) -> float:
    return float(table.loc[strategy, column])


def _headline(table: pd.DataFrame) -> list[str]:
    lines = [
        "| Strategy | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in table.index:
        lines.append(
            f"| {strategy}"
            + f" | {_metric(table, strategy, 'cagr'):.2%}"
            + f" | {_metric(table, strategy, 'sharpe'):.3f}"
            + f" | {_metric(table, strategy, 'sortino'):.3f}"
            + f" | {_metric(table, strategy, 'max_drawdown'):.2%}"
            + f" | {_metric(table, strategy, 'calmar'):.3f}"
            + f" | {_metric(table, strategy, 'turnover_units'):.1f} |"
        )
    return lines


def _decision(model: Any, policy: Any) -> tuple[str, dict[str, Any]]:
    checks = {
        "model_gate": bool(model.model_gate["passed"]),
        "portfolio_gate": bool(policy.portfolio_gate["passed"]),
        "actual_contradiction_gate": bool(policy.contradiction_gate["passed"]),
    }
    if not checks["model_gate"]:
        decision = "regularized_action_advantage_model_not_stable"
    elif not checks["portfolio_gate"]:
        decision = "regularized_action_policy_does_not_beat_v4_2_oof"
    elif not checks["actual_contradiction_gate"]:
        decision = "regularized_action_policy_blocked_by_actual_contradiction"
    else:
        decision = "regularized_action_policy_prospective_shadow_supported"
    return decision, {"checks": checks, "passed": bool(all(checks.values()))}


def _report(model: Any, policy: Any, decision: str, gate: dict[str, Any]) -> str:
    lines = [
        "# v4.16 strongly regularized multi-action advantage model",
        "",
        f"Decision: `{decision}`",
        "",
        "## Frozen model boundary",
        "",
        f"- continuous features and interactions: {len(model.feature_names)}",
        "- one multi-output Ridge model with alpha=100.0;",
        "- every tenth session training samples and a ten-session embargo;",
        "- four discrete advantages relative to the frozen v4.2 path;",
        "- events require a fresh 0.50% predicted advantage and 0.25% lead;",
        "- historical success can authorize only a prospective shadow.",
        "",
        "## OOF action evidence",
        "",
        "| Action | Observations | Spearman IC | Quintile spread | Base positive rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in model.action_metrics.itertuples(index=False):
        lines.append(
            f"| {row.action} | {int(row.observations)}"
            + f" | {float(row.spearman_ic):.3f}"
            + f" | {float(row.top_bottom_quintile_spread):.2%}"
            + f" | {float(row.unconditional_positive_rate):.1%} |"
        )
    lines.extend(
        [
            "",
            "## Model gate",
            "",
            f"- OOF triggered events: {len(model.oof_events)}",
            f"- model gate passed: {bool(model.model_gate['passed'])}",
            f"- coefficient cosine median: {float(model.model_gate['metrics']['coefficient_cosine_similarity_median']):.3f}",
            f"- triggered precision lift: {float(model.model_gate['metrics']['triggered_precision_lift']):.1%}",
            f"- median triggered advantage: {float(model.model_gate['metrics']['median_triggered_advantage']):.2%}",
            "",
            "## Nested OOF policy: 2016-2023",
            "",
        ]
    )
    lines.extend(_headline(policy.oof_headline))
    lines.extend(["", "## Actual QQQI/SGOV feasibility: 2024+", ""])
    lines.extend(_headline(policy.actual_headline))
    lines.extend(
        [
            "",
            "## Decision gates",
            "",
            f"- model gate: {gate['checks']['model_gate']}",
            f"- portfolio gate: {gate['checks']['portfolio_gate']}",
            f"- actual contradiction gate: {gate['checks']['actual_contradiction_gate']}",
            f"- prospective shadow authorized: {gate['passed']}",
            "- v4.2, Telegram and Issue #348 remain unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
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
    actual_baseline = actual_results[BASELINE_KEY]
    proxy_baseline = proxy_results[BASELINE_KEY]

    model = run_action_advantage_model(
        bars, proxy_baseline.daily, contract
    )
    policy = run_action_advantage_policy(
        bars,
        proxy_baseline.daily,
        actual_baseline.daily,
        model,
        contract,
    )
    decision, decision_gate = _decision(model, policy)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    model.frame.reset_index().to_csv(
        output / "feature_label_frame.csv", index=False
    )
    model.oof_predictions.reset_index(names="date").to_csv(
        output / "oof_predictions.csv", index=False
    )
    model.fold_coefficients.to_csv(
        output / "fold_coefficients.csv", index=False
    )
    model.actual_coefficients.to_csv(
        output / "actual_coefficients.csv", index=False
    )
    model.action_metrics.to_csv(output / "action_metrics.csv", index=False)
    pd.DataFrame(
        model.model_gate.get("coefficient_cosine_pairs", [])
    ).to_csv(output / "coefficient_cosine_pairs.csv", index=False)
    model.oof_events.to_csv(output / "oof_event_ledger.csv", index=False)
    model.actual_predictions.reset_index(names="date").to_csv(
        output / "actual_predictions.csv", index=False
    )
    model.actual_events.to_csv(output / "actual_event_ledger.csv", index=False)
    policy.oof_headline.reset_index().to_csv(
        output / "oof_headline.csv", index=False
    )
    policy.actual_headline.reset_index().to_csv(
        output / "actual_headline.csv", index=False
    )
    policy.oof_action_trace.reset_index(names="date").to_csv(
        output / "oof_action_trace.csv", index=False
    )
    policy.actual_action_trace.reset_index(names="date").to_csv(
        output / "actual_action_trace.csv", index=False
    )
    policy.oof_attribution.to_csv(
        output / "oof_event_attribution.csv", index=False
    )
    policy.actual_attribution.to_csv(
        output / "actual_event_attribution.csv", index=False
    )
    for scope, results in (
        ("oof", policy.oof_results),
        ("actual", policy.actual_results),
    ):
        for strategy, result in results.items():
            result.daily.reset_index(names="date").to_csv(
                output / f"{scope}_{strategy}_daily.csv", index=False
            )
            result.trades.to_csv(
                output / f"{scope}_{strategy}_trades.csv", index=False
            )

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "decision_gate": decision_gate,
        "model_gate": model.model_gate,
        "portfolio_gate": policy.portfolio_gate,
        "contradiction_gate": policy.contradiction_gate,
        "policy": policy.diagnostics,
        "shadow_candidate_authorized": bool(decision_gate["passed"]),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(
        _report(model, policy, decision, decision_gate), encoding="utf-8"
    )
    files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "bridge_contract_path": str(args.bridge_contract),
        "bridge_contract_sha256": _sha256(args.bridge_contract),
        "decision": decision,
        "shadow_candidate_authorized": bool(decision_gate["passed"]),
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _json_safe(
                {
                    "decision": decision,
                    "decision_gate": decision_gate,
                    "model_gate": model.model_gate,
                    "portfolio_gate": policy.portfolio_gate,
                    "contradiction_gate": policy.contradiction_gate,
                    "oof_events": len(model.oof_events),
                    "actual_events": len(model.actual_events),
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
