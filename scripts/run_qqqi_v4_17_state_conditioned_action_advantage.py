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
from src.research.v4_17_state_conditioned_action_advantage import (
    run_state_conditioned_research,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_state_conditioned_action_advantage_v4_17_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_tqqq_sgov_voo_state_conditioned_action_advantage_v4_17_research"
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


def _decision(result: Any) -> str:
    checks = result.final_gate["checks"]
    if not checks["state_model_gate"]:
        return "state_conditioned_action_advantage_model_not_stable"
    if not checks["state_portfolio_gate"]:
        return "state_conditioned_action_policy_does_not_beat_v4_2_oof"
    if not checks["actual_contradiction_gate"]:
        return "state_conditioned_action_policy_blocked_by_actual_contradiction"
    if not checks["v4_16_improvement_gate"]:
        return "state_conditioning_does_not_materially_improve_v4_16"
    return "state_conditioned_action_policy_prospective_shadow_supported"


def _report(result: Any, decision: str) -> str:
    state = result.state_model
    state_policy = result.state_policy
    unconditioned = result.unconditioned_model
    unconditioned_policy = result.unconditioned_policy
    lines = [
        "# v4.17 state-conditioned incremental action advantage",
        "",
        f"Decision: `{decision}`",
        "",
        "## Frozen comparison",
        "",
        f"- state-conditioned model inputs: {len(state.feature_names)}",
        f"- unconditioned v4.16 inputs: {len(unconditioned.feature_names)}",
        "- both use the same Ridge(alpha=100), labels, sampling, embargo and score thresholds;",
        "- only next-open v4.2 state/weights, declared state interactions and the 0.50 L1 novelty guard differ.",
        "",
        "## Pooled action evidence",
        "",
        "| Action | State-conditioned IC | State-conditioned quintile spread | v4.16 IC |",
        "|---|---:|---:|---:|",
    ]
    v416_metrics = unconditioned.action_metrics.set_index("action")
    for row in state.action_metrics.itertuples(index=False):
        lines.append(
            f"| {row.action} | {float(row.spearman_ic):.3f}"
            + f" | {float(row.top_bottom_quintile_spread):.2%}"
            + f" | {float(v416_metrics.loc[row.action, 'spearman_ic']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Action-state cells",
            "",
            "| Action | State | Observations | IC | Quintile spread | Events | Precision | Median advantage |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result.action_state_metrics.itertuples(index=False):
        lines.append(
            f"| {row.action} | {int(row.state)} | {int(row.observations)}"
            + f" | {float(row.spearman_ic):.3f}"
            + f" | {float(row.top_bottom_quintile_spread):.2%}"
            + f" | {int(row.triggered_events)}"
            + f" | {float(row.triggered_precision):.1%}"
            + f" | {float(row.median_triggered_advantage):.2%} |"
        )
    lines.extend(["", "## State-conditioned OOF policy", ""])
    lines.extend(_headline(state_policy.oof_headline))
    lines.extend(["", "## Reproduced unconditioned v4.16 OOF policy", ""])
    lines.extend(_headline(unconditioned_policy.oof_headline))
    lines.extend(["", "## Actual 2024+ state-conditioned feasibility", ""])
    lines.extend(_headline(state_policy.actual_headline))
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- state model gate: {bool(state.model_gate['passed'])}",
            f"- state portfolio gate: {bool(state_policy.portfolio_gate['passed'])}",
            f"- actual contradiction gate: {bool(state_policy.contradiction_gate['passed'])}",
            f"- v4.16 improvement gate: {bool(result.improvement_gate['passed'])}",
            f"- prospective shadow authorized: {bool(result.final_gate['passed'])}",
            "- v4.2, Telegram and Issue #348 remain unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def _save_model(prefix: str, model: Any, output: Path) -> None:
    model.frame.reset_index().to_csv(output / f"{prefix}_feature_label_frame.csv", index=False)
    model.oof_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_oof_predictions.csv", index=False
    )
    model.fold_coefficients.to_csv(
        output / f"{prefix}_fold_coefficients.csv", index=False
    )
    model.actual_coefficients.to_csv(
        output / f"{prefix}_actual_coefficients.csv", index=False
    )
    model.action_metrics.to_csv(
        output / f"{prefix}_action_metrics.csv", index=False
    )
    model.oof_events.to_csv(output / f"{prefix}_oof_events.csv", index=False)
    model.actual_predictions.reset_index(names="date").to_csv(
        output / f"{prefix}_actual_predictions.csv", index=False
    )
    model.actual_events.to_csv(output / f"{prefix}_actual_events.csv", index=False)


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
    parser.add_argument("--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
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
    actual_baseline = actual_results[BASELINE_KEY]
    proxy_baseline = proxy_results[BASELINE_KEY]
    result = run_state_conditioned_research(
        bars,
        proxy_baseline.daily,
        actual_baseline.daily,
        contract,
    )
    decision = _decision(result)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    _save_model("state_conditioned", result.state_model, output)
    _save_model("unconditioned_v4_16", result.unconditioned_model, output)
    result.action_state_metrics.to_csv(
        output / "state_conditioned_action_state_metrics.csv", index=False
    )
    _save_policy("state_conditioned", result.state_policy, output)
    _save_policy("unconditioned_v4_16", result.unconditioned_policy, output)

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "state_model_gate": result.state_model.model_gate,
        "state_portfolio_gate": result.state_policy.portfolio_gate,
        "state_actual_contradiction_gate": result.state_policy.contradiction_gate,
        "unconditioned_model_gate": result.unconditioned_model.model_gate,
        "unconditioned_portfolio_gate": result.unconditioned_policy.portfolio_gate,
        "improvement_gate": result.improvement_gate,
        "final_gate": result.final_gate,
        "shadow_candidate_authorized": bool(result.final_gate["passed"]),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(_report(result, decision), encoding="utf-8")
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
        "shadow_candidate_authorized": bool(result.final_gate["passed"]),
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _json_safe(
                {
                    "decision": decision,
                    "state_model_gate": result.state_model.model_gate,
                    "state_portfolio_gate": result.state_policy.portfolio_gate,
                    "actual_contradiction_gate": result.state_policy.contradiction_gate,
                    "improvement_gate": result.improvement_gate,
                    "final_gate": result.final_gate,
                    "state_oof_events": len(result.state_model.oof_events),
                    "state_actual_events": len(result.state_model.actual_events),
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
