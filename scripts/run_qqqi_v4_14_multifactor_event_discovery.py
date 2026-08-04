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
    run_nested_event_discovery,
)
from src.research.v4_14_multifactor_event_policy import (
    run_multifactor_event_policy,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_multifactor_events_v4_14_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_tqqq_sgov_voo_multifactor_events_v4_14_research"
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


def _headline_table(table: pd.DataFrame) -> list[str]:
    lines = [
        "| Strategy | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in table.index:
        lines.append(
            "| "
            + strategy
            + f" | {_metric(table, strategy, 'cagr'):.2%}"
            + f" | {_metric(table, strategy, 'sharpe'):.3f}"
            + f" | {_metric(table, strategy, 'sortino'):.3f}"
            + f" | {_metric(table, strategy, 'max_drawdown'):.2%}"
            + f" | {_metric(table, strategy, 'calmar'):.3f}"
            + f" | {_metric(table, strategy, 'turnover_units'):.1f} |"
        )
    return lines


def _decision(
    family_gates: pd.DataFrame,
    portfolio_gate: dict[str, Any],
    actual_headline: pd.DataFrame,
) -> tuple[str, dict[str, Any]]:
    passing_families = family_gates.loc[
        family_gates["passed"].astype(bool), "event_family"
    ].tolist()
    actual_baseline = actual_headline.loc["frozen_v4_2"]
    actual_policy = actual_headline.loc["full_event_policy"]
    actual_cagr_delta = float(actual_policy["cagr"] - actual_baseline["cagr"])
    actual_calmar_delta = float(actual_policy["calmar"] - actual_baseline["calmar"])
    actual_drawdown_worsening_pp = max(
        0.0,
        float(
            (actual_baseline["max_drawdown"] - actual_policy["max_drawdown"])
            * 100.0
        ),
    )
    actual_contradiction = bool(
        (actual_cagr_delta < 0.0 and actual_calmar_delta < 0.0)
        or actual_drawdown_worsening_pp > 2.0
    )
    checks = {
        "at_least_one_family_passes": bool(passing_families),
        "oof_portfolio_gate_passes": bool(portfolio_gate["passed"]),
        "actual_no_material_contradiction": not actual_contradiction,
    }
    if not passing_families:
        decision = "no_multifactor_event_family_stable"
    elif not portfolio_gate["passed"]:
        decision = "multifactor_event_policy_does_not_beat_v4_2_oof"
    elif actual_contradiction:
        decision = "multifactor_event_policy_blocked_by_actual_contradiction"
    else:
        decision = "multifactor_event_policy_prospective_shadow_supported"
    return decision, {
        "checks": checks,
        "passing_families": passing_families,
        "actual_cagr_delta": actual_cagr_delta,
        "actual_calmar_delta": actual_calmar_delta,
        "actual_drawdown_worsening_pp": actual_drawdown_worsening_pp,
        "actual_contradiction": actual_contradiction,
        "passed": bool(all(checks.values())),
    }


def _render_report(
    discovery: Any,
    policy: Any,
    decision: str,
    decision_gate: dict[str, Any],
) -> str:
    lines = [
        "# v4.14 VIX/VXN/RSI20/Bollinger multi-factor event discovery",
        "",
        f"Decision: `{decision}`",
        "",
        "## Search boundary",
        "",
        f"- unique rule structures: {discovery.diagnostics['unique_rule_structures']}",
        f"- development evaluations: {discovery.diagnostics['rules_evaluated']}",
        f"- untouched outer events: {discovery.diagnostics['outer_events']}",
        "- every rule contains one volatility and one price condition, with at most one QQQ/VOO condition;",
        "- thresholds, folds, FDR, 10-session holding and 5-session cooldown were frozen before results;",
        "- historical evidence is research-only and cannot directly replace v4.2.",
        "",
        "## Event-family gates",
        "",
        "| Family | Events | Macro clusters | Positive folds | Win-rate lift | Median excess | Recurrence | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in discovery.family_gates.itertuples(index=False):
        lines.append(
            f"| {row.event_family} | {int(row.events)} | {int(row.macro_clusters)}"
            + f" | {float(row.positive_outer_fold_rate):.1%}"
            + f" | {float(row.conditional_win_rate_lift):.1%}"
            + f" | {float(row.median_excess_return):.2%}"
            + f" | {float(row.rule_recurrence_rate):.1%} | {bool(row.passed)} |"
        )
    lines.extend(["", "## Nested OOF portfolio: 2016-2023", ""])
    lines.extend(_headline_table(policy.oof_headline))
    lines.extend(["", "## Actual QQQI/SGOV feasibility: 2024+", ""])
    lines.extend(_headline_table(policy.actual_headline))
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- event families passing: {decision_gate['passing_families']}",
            f"- OOF portfolio gate: {bool(policy.portfolio_gate['passed'])}",
            f"- actual contradiction: {bool(decision_gate['actual_contradiction'])}",
            f"- prospective shadow authorized: {bool(decision_gate['passed'])}",
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
    _, actual_base_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    _, proxy_base_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    actual_baseline = actual_base_results[BASELINE_KEY]
    proxy_baseline = proxy_base_results[BASELINE_KEY]

    features = build_multifactor_feature_frame(
        bars, proxy_baseline.daily
    )
    discovery = run_nested_event_discovery(features, contract)
    policy = run_multifactor_event_policy(
        bars,
        proxy_baseline.daily,
        actual_baseline.daily,
        discovery,
        contract,
    )
    decision, decision_gate = _decision(
        discovery.family_gates,
        policy.portfolio_gate,
        policy.actual_headline,
    )

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    discovery.features.reset_index().to_csv(
        output / "multifactor_features.csv", index=False
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
        _render_report(discovery, policy, decision, decision_gate),
        encoding="utf-8",
    )
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
