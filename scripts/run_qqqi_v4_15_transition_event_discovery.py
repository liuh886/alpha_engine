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
from src.research.v4_14_multifactor_event_discovery import (
    build_multifactor_feature_frame,
)
from src.research.v4_15_transition_event_discovery import (
    run_nested_transition_discovery,
)
from src.research.v4_15_transition_event_policy import (
    run_transition_event_policy,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_transition_events_v4_15_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_tqqq_sgov_voo_transition_events_v4_15_research"
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


def _decision(discovery: Any, policy: Any) -> tuple[str, dict[str, Any]]:
    passing = discovery.family_gates.loc[
        discovery.family_gates["passed"].astype(bool), "event_family"
    ].tolist()
    actual_base = policy.actual_headline.loc["frozen_v4_2"]
    actual_policy = policy.actual_headline.loc["full_event_policy"]
    actual_cagr_delta = float(actual_policy["cagr"] - actual_base["cagr"])
    actual_calmar_delta = float(actual_policy["calmar"] - actual_base["calmar"])
    drawdown_worsening_pp = max(
        0.0,
        float(
            (actual_base["max_drawdown"] - actual_policy["max_drawdown"])
            * 100.0
        ),
    )
    contradiction = bool(
        (actual_cagr_delta < 0.0 and actual_calmar_delta < 0.0)
        or drawdown_worsening_pp > 2.0
    )
    checks = {
        "at_least_one_family_passes": bool(passing),
        "oof_portfolio_gate_passes": bool(policy.portfolio_gate["passed"]),
        "actual_no_material_contradiction": not contradiction,
    }
    if not passing:
        decision = "no_fresh_transition_event_family_stable"
    elif not policy.portfolio_gate["passed"]:
        decision = "fresh_transition_policy_does_not_beat_v4_2_oof"
    elif contradiction:
        decision = "fresh_transition_policy_blocked_by_actual_contradiction"
    else:
        decision = "fresh_transition_policy_prospective_shadow_supported"
    return decision, {
        "checks": checks,
        "passing_families": passing,
        "actual_cagr_delta": actual_cagr_delta,
        "actual_calmar_delta": actual_calmar_delta,
        "actual_drawdown_worsening_pp": drawdown_worsening_pp,
        "actual_contradiction": contradiction,
        "passed": bool(all(checks.values())),
    }


def _report(discovery: Any, policy: Any, decision: str, gate: dict[str, Any]) -> str:
    lines = [
        "# v4.15 fresh transition-event discovery",
        "",
        f"Decision: `{decision}`",
        "",
        "## Search boundary",
        "",
        f"- transition rule structures: {discovery.diagnostics['unique_rule_structures']}",
        f"- development evaluations: {discovery.diagnostics['development_evaluations']}",
        f"- untouched outer events: {discovery.diagnostics['outer_events']}",
        "- all conditions are first crossings or first confirmations inside a three-session window;",
        "- repair/acceleration signals above +5% from MA20 are rejected;",
        "- development FDR selects rules; outer results do not modify thresholds or actions.",
        "",
        "## Event-family gates",
        "",
        "| Family | Events | Clusters | Positive folds | Lift | Median excess | Motif recurrence | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in discovery.family_gates.itertuples(index=False):
        lines.append(
            f"| {row.event_family} | {int(row.events)} | {int(row.macro_clusters)}"
            + f" | {float(row.positive_outer_fold_rate):.1%}"
            + f" | {float(row.conditional_win_rate_lift):.1%}"
            + f" | {float(row.median_excess_return):.2%}"
            + f" | {float(row.motif_recurrence_rate):.1%} | {bool(row.passed)} |"
        )
    lines.extend(["", "## Nested OOF portfolio: 2016-2023", ""])
    lines.extend(_headline(policy.oof_headline))
    lines.extend(["", "## Actual QQQI/SGOV feasibility: 2024+", ""])
    lines.extend(_headline(policy.actual_headline))
    lines.extend(
        [
            "",
            "## Decision gates",
            "",
            f"- passing event families: {gate['passing_families']}",
            f"- OOF portfolio gate: {bool(policy.portfolio_gate['passed'])}",
            f"- actual contradiction: {bool(gate['actual_contradiction'])}",
            f"- prospective shadow authorized: {bool(gate['passed'])}",
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

    features = build_multifactor_feature_frame(bars, proxy_baseline.daily)
    discovery = run_nested_transition_discovery(features, contract)
    policy = run_transition_event_policy(
        bars,
        proxy_baseline.daily,
        actual_baseline.daily,
        discovery,
        contract,
    )
    decision, decision_gate = _decision(discovery, policy)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    discovery.features.reset_index().to_csv(
        output / "base_features.csv", index=False
    )
    discovery.transition_flags.reset_index().to_csv(
        output / "transition_flags.csv", index=False
    )
    discovery.rule_catalog.to_csv(output / "rule_catalog.csv", index=False)
    discovery.candidate_metrics.to_csv(
        output / "development_candidate_metrics.csv", index=False
    )
    discovery.selected_rules.to_csv(
        output / "outer_selected_rules.csv", index=False
    )
    discovery.outer_events.to_csv(output / "outer_event_ledger.csv", index=False)
    discovery.fold_metrics.to_csv(output / "outer_fold_metrics.csv", index=False)
    discovery.family_gates.to_csv(output / "event_family_gates.csv", index=False)
    policy.actual_selected_rules.to_csv(
        output / "actual_selected_rules.csv", index=False
    )
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
        "discovery": discovery.diagnostics,
        "portfolio": policy.diagnostics,
        "portfolio_gate": policy.portfolio_gate,
        "shadow_candidate_authorized": bool(decision_gate["passed"]),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(
        _report(discovery, policy, decision, decision_gate), encoding="utf-8"
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
                    "family_gates": discovery.family_gates.to_dict(
                        orient="records"
                    ),
                    "portfolio_gate": policy.portfolio_gate,
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
