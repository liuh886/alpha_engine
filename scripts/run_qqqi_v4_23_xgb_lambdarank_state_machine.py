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
from src.research.v4_23_xgb_lambdarank_state_machine import (
    XGBStateMachineResult,
    run_xgb_lambdarank_state_machine,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_xgb_lambdarank_state_machine_v4_23_research.yaml"
)
DEFAULT_V416_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_xgb_lambdarank_state_machine_v4_23_research"
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


def _decision(result: XGBStateMachineResult) -> str:
    if not bool(result.phase1_gate["passed"]):
        return "xgb_action_ranking_not_supported"
    if not bool(result.phase2_gate["passed"]):
        return "xgb_action_ranking_supported_but_policy_not_supported"
    if not bool(result.actual_contradiction_gate["passed"]):
        return "xgb_state_machine_blocked_by_actual_contradiction"
    return "xgb_state_machine_prospective_shadow_supported"


def _fmt(value: Any, *, percent: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.2%}" if percent else f"{number:.4f}"


def _report(result: XGBStateMachineResult, decision: str) -> str:
    phase1 = result.phase1_gate
    lines = [
        "# v4.23 XGBoost LambdaRank 10D allocation state machine",
        "",
        f"Decision: `{decision}`",
        "",
        "## Frozen design",
        "",
        "- five discrete actions: defense, balanced, core, leveraged and accelerated;",
        "- one grouped XGBoost ranker using 39 frozen market, credit/duration, v4.2-context and action inputs;",
        "- signal at close, execution next open, exact ten-session non-overlapping holding blocks;",
        "- four chronological outer folds with a ten-session embargo;",
        "- Phase 2 portfolio construction is prohibited unless all Phase 1 ranking gates pass.",
        "",
        "## Phase 1 ranking",
        "",
        f"- selected NDCG@1: {_fmt(phase1.get('selected_ndcg_at_1'))};",
        f"- v4.2-action comparator NDCG@1: {_fmt(phase1.get('comparator_ndcg_at_1'))};",
        f"- NDCG improvement: {_fmt(phase1.get('ndcg_improvement'))};",
        f"- regret reduction: {_fmt(phase1.get('regret_reduction'), percent=True)};",
        f"- median selected advantage versus v4.2: {_fmt(phase1.get('median_advantage_vs_v4_2'), percent=True)};",
        f"- positive outer folds: {phase1.get('positive_outer_folds')};",
        f"- selected top-two rate: {_fmt(phase1.get('top_two_rate'), percent=True)};",
        f"- placebo beat rate: {_fmt(phase1.get('placebo_beat_rate'), percent=True)};",
        f"- largest single-feature SHAP share: {_fmt(phase1.get('largest_single_feature_share'), percent=True)};",
        f"- largest feature-family SHAP share: {_fmt(phase1.get('largest_feature_family_share'), percent=True)};",
        f"- unsupported low-frequency actions: {phase1.get('unsupported_actions', [])};",
        f"- Phase 1 passed: {bool(phase1['passed'])}.",
        "",
        "## Outer-fold evidence",
        "",
        "| Fold | Groups | NDCG improvement | Regret reduction | Top-two rate | Total advantage vs v4.2 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result.ranking_by_fold.itertuples(index=False):
        lines.append(
            f"| {row.fold} | {int(row.groups)} | {float(row.ndcg_improvement):.4f}"
            + f" | {float(row.regret_reduction):.2%}"
            + f" | {float(row.top_two_rate):.2%}"
            + f" | {float(row.total_advantage_vs_v4_2):.2%} |"
        )
    lines.extend(
        [
            "",
            "## Action selection",
            "",
            "| Action | Selected blocks | Top-two rate | Median advantage | Total advantage |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in result.ranking_by_action.itertuples(index=False):
        lines.append(
            f"| {row.action} | {int(row.selected_groups)}"
            + f" | {_fmt(row.top_two_rate, percent=True)}"
            + f" | {_fmt(row.median_advantage_vs_v4_2, percent=True)}"
            + f" | {_fmt(row.total_advantage_vs_v4_2, percent=True)} |"
        )
    lines.extend(["", "## Phase 2 and actual-product gates", ""])
    lines.append(f"- Phase 2 skipped: {bool(result.phase2_gate.get('skipped', False))};")
    lines.append(f"- Phase 2 passed: {bool(result.phase2_gate.get('passed', False))};")
    lines.append(
        f"- 2024+ contradiction gate passed: {bool(result.actual_contradiction_gate.get('passed', False))};"
    )
    lines.append(
        f"- prospective shadow authorized: {bool(result.final_gate['prospective_shadow_authorized'])};"
    )
    lines.append("- direct promotion, v4.2 changes and Telegram changes remain unauthorized.")
    lines.append("")
    if not result.oof_headline.empty:
        lines.extend(
            [
                "## OOF state-machine portfolio",
                "",
                "| Strategy | CAGR | Sortino | Max drawdown | Calmar | Turnover |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for key, row in result.oof_headline.iterrows():
            lines.append(
                f"| {key} | {_fmt(row.get('cagr'), percent=True)}"
                + f" | {_fmt(row.get('sortino'))}"
                + f" | {_fmt(row.get('max_drawdown'), percent=True)}"
                + f" | {_fmt(row.get('calmar'))}"
                + f" | {_fmt(row.get('turnover_units'))} |"
            )
    if not result.actual_headline.empty:
        lines.extend(
            [
                "",
                "## Actual 2024+ product window",
                "",
                "| Strategy | CAGR | Sortino | Max drawdown | Calmar | Turnover |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for key, row in result.actual_headline.iterrows():
            lines.append(
                f"| {key} | {_fmt(row.get('cagr'), percent=True)}"
                + f" | {_fmt(row.get('sortino'))}"
                + f" | {_fmt(row.get('max_drawdown'), percent=True)}"
                + f" | {_fmt(row.get('calmar'))}"
                + f" | {_fmt(row.get('turnover_units'))} |"
            )
    lines.extend(
        [
            "",
            "## Research boundary",
            "",
            "This result is a governed retrospective research record. No result may be used to retune the fixed XGBoost parameters, remove an action after inspection, change the ten-session horizon, modify v4.2, or alter alerts.",
            "",
        ]
    )
    return "\n".join(lines)


def _save_daily(prefix: str, frames: dict[str, pd.DataFrame], output: Path) -> None:
    for name, frame in frames.items():
        if frame.empty:
            continue
        frame.reset_index(names="date").to_csv(
            output / f"{prefix}_{name}_daily.csv", index=False
        )


def _save_trades(prefix: str, frames: dict[str, pd.DataFrame], output: Path) -> None:
    for name, frame in frames.items():
        frame.to_csv(output / f"{prefix}_{name}_trades.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--v4-16-contract", type=Path, default=DEFAULT_V416_CONTRACT)
    parser.add_argument("--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    v416_contract = yaml.safe_load(args.v4_16_contract.read_text(encoding="utf-8"))
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
    result = run_xgb_lambdarank_state_machine(
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
    result.proxy_group_frame.to_csv(
        output / "proxy_grouped_action_labels.csv", index=False
    )
    result.actual_group_frame.to_csv(
        output / "actual_grouped_action_labels.csv", index=False
    )
    result.fold_coverage.to_csv(output / "fold_coverage.csv", index=False)
    result.oof_scores.to_csv(output / "oof_action_scores.csv", index=False)
    result.actual_scores.to_csv(output / "actual_action_scores.csv", index=False)
    result.ranking_by_fold.to_csv(output / "ranking_by_fold.csv", index=False)
    result.ranking_by_action.to_csv(output / "ranking_by_action.csv", index=False)
    result.placebo_metrics.to_csv(output / "placebo_metrics.csv", index=False)
    result.feature_importance.to_csv(
        output / "feature_gain_importance.csv", index=False
    )
    result.shap_importance.to_csv(
        output / "feature_shap_importance.csv", index=False
    )
    result.concentration_metrics.to_csv(
        output / "concentration_metrics.csv", index=False
    )
    result.oof_selected_blocks.to_csv(
        output / "oof_selected_blocks.csv", index=False
    )
    result.actual_selected_blocks.to_csv(
        output / "actual_selected_blocks.csv", index=False
    )
    if not result.oof_headline.empty:
        result.oof_headline.reset_index().to_csv(
            output / "oof_headline.csv", index=False
        )
    if not result.actual_headline.empty:
        result.actual_headline.reset_index().to_csv(
            output / "actual_headline.csv", index=False
        )
    _save_daily("oof", result.oof_daily, output)
    _save_daily("actual", result.actual_daily, output)
    _save_trades("oof", result.oof_trades, output)
    _save_trades("actual", result.actual_trades, output)

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "phase1_gate": result.phase1_gate,
        "phase2_gate": result.phase2_gate,
        "actual_contradiction_gate": result.actual_contradiction_gate,
        "final_gate": result.final_gate,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(_report(result, decision), encoding="utf-8")

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
        "prospective_shadow_authorized": bool(
            result.final_gate["prospective_shadow_authorized"]
        ),
        "direct_promotion_authorized": False,
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _safe(
                {
                    "decision": decision,
                    "phase1_gate": result.phase1_gate,
                    "phase2_gate": result.phase2_gate,
                    "actual_contradiction_gate": result.actual_contradiction_gate,
                    "final_gate": result.final_gate,
                    "oof_groups": int(
                        result.oof_selected_blocks["decision_date"].nunique()
                    ),
                    "actual_groups": int(
                        result.actual_selected_blocks["decision_date"].nunique()
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
