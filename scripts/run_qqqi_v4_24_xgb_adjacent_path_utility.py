from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.adapters.yfinance_open_close_research_adapter import (
    YFinanceOpenCloseResearchAdapter,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.v4_24_xgb_adjacent_path_state_machine import (
    AdjacentPathUtilityResult,
    run_adjacent_path_utility_study,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_adjacent_path_utility_v4_24_research.yaml"
)
DEFAULT_V416_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_xgb_adjacent_path_utility_v4_24_research"
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


def _decision(result: AdjacentPathUtilityResult) -> str:
    if not bool(result.phase1_gate["passed"]):
        return "xgb_adjacent_path_utility_not_supported"
    if not bool(result.phase2_gate["passed"]):
        return "xgb_adjacent_path_utility_supported_but_policy_not_supported"
    if not bool(result.actual_contradiction_gate["passed"]):
        return "xgb_adjacent_state_machine_blocked_by_actual_contradiction"
    return "xgb_adjacent_state_machine_prospective_shadow_supported"


def _fmt(value: Any, *, percent: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.2%}" if percent else f"{number:.4f}"


def _report(result: AdjacentPathUtilityResult, decision: str) -> str:
    phase1 = result.phase1_gate
    lines = [
        "# v4.24 XGBoost ordinal adjacent-state path-utility machine",
        "",
        f"Decision: `{decision}`",
        "",
        "## Frozen design",
        "",
        "- four ordered states: defense, bridge, core and leveraged;",
        "- three independent adjacent XGBoost classifiers with 35 fixed inputs and no candidate-action descriptors;",
        "- one decision every ten sessions, execution next open, exact ten-session holding blocks;",
        "- path utility equals terminal net return plus 0.50 times maximum adverse excursion;",
        "- Phase 2 is prohibited unless every Phase 1 gate passes.",
        "",
        "## Phase 1 headline",
        "",
        f"- mean edge AUC: {_fmt(phase1.get('mean_edge_auc'))};",
        f"- minimum edge AUC: {_fmt(phase1.get('minimum_edge_auc'))};",
        f"- mean balanced accuracy: {_fmt(phase1.get('mean_balanced_accuracy'))};",
        f"- utility-regret reduction versus frozen v4.2: {_fmt(phase1.get('utility_regret_reduction'), percent=True)};",
        f"- median selected utility advantage: {_fmt(phase1.get('median_utility_advantage_vs_v4_2'), percent=True)};",
        f"- positive outer folds: {phase1.get('positive_outer_folds')};",
        f"- selected top-two utility rate: {_fmt(phase1.get('top_two_rate'), percent=True)};",
        f"- minimum state selections: {phase1.get('minimum_state_selections')};",
        f"- maximum state share: {_fmt(phase1.get('maximum_state_selection_share'), percent=True)};",
        f"- placebo beat rate: {_fmt(phase1.get('placebo_beat_rate'), percent=True)};",
        f"- largest single-feature SHAP share: {_fmt(phase1.get('largest_single_feature_shap_share'), percent=True)};",
        f"- largest feature-family SHAP share: {_fmt(phase1.get('largest_feature_family_shap_share'), percent=True)};",
        f"- Phase 1 passed: {bool(phase1['passed'])}.",
        "",
        "## Edge diagnostics",
        "",
        "| Edge | Positive rate | AUC | Balanced accuracy | Brier |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result.edge_summary.itertuples(index=False):
        lines.append(
            f"| {row.edge} | {float(row.positive_rate):.2%} | {float(row.roc_auc):.4f}"
            + f" | {float(row.balanced_accuracy):.4f} | {float(row.brier_score):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Chronological selection evidence",
            "",
            "| Fold | Groups | Regret reduction | Top-two rate | Median utility advantage | Total utility advantage |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result.selection_by_fold.itertuples(index=False):
        lines.append(
            f"| {row.fold} | {int(row.groups)} | {_fmt(row.utility_regret_reduction, percent=True)}"
            + f" | {_fmt(row.top_two_rate, percent=True)}"
            + f" | {_fmt(row.median_utility_advantage_vs_v4_2, percent=True)}"
            + f" | {_fmt(row.total_utility_advantage_vs_v4_2, percent=True)} |"
        )
    lines.extend(
        [
            "",
            "## State coverage",
            "",
            "| State | Selected blocks | Share | Top-two rate | Median utility advantage |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in result.selection_by_state.itertuples(index=False):
        lines.append(
            f"| {row.state} | {int(row.selected_groups)} | {_fmt(row.selection_share, percent=True)}"
            + f" | {_fmt(row.top_two_rate, percent=True)}"
            + f" | {_fmt(row.median_utility_advantage_vs_v4_2, percent=True)} |"
        )
    lines.extend(
        [
            "",
            "## Phase 2 boundary",
            "",
            f"- Phase 2 skipped: {bool(result.phase2_gate.get('skipped', False))};",
            f"- Phase 2 passed: {bool(result.phase2_gate.get('passed', False))};",
            f"- actual contradiction gate passed: {bool(result.actual_contradiction_gate.get('passed', False))};",
            f"- prospective shadow authorized: {bool(result.final_gate['prospective_shadow_authorized'])};",
            "- direct promotion, v4.2 changes and Telegram changes remain unauthorized.",
        ]
    )
    if not result.oof_headline.empty:
        lines.extend(
            [
                "",
                "## OOF portfolio",
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
            "The four-state lattice, path-utility coefficient, edge definitions, probability threshold, features and XGBoost parameters were frozen before outcomes. No result may be used to retune this experiment or alter v4.2 and alerts.",
            "",
        ]
    )
    return "\n".join(lines)


def _save_frames(prefix: str, frames: dict[str, pd.DataFrame], output: Path) -> None:
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
        adapter=YFinanceOpenCloseResearchAdapter(),
    )
    coverage["open_close_only_research"] = True
    coverage["provider_adjusted_open_close_preserved"] = True
    coverage["synthetic_high_low_used_for_range_features"] = False
    _, actual_results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    _, proxy_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    result = run_adjacent_path_utility_study(
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
    result.proxy_frame.to_csv(output / "proxy_path_utility_frame.csv", index=False)
    result.actual_frame.to_csv(output / "actual_path_utility_frame.csv", index=False)
    result.fold_coverage.to_csv(output / "fold_coverage.csv", index=False)
    result.oof_scores.to_csv(output / "oof_edge_scores.csv", index=False)
    result.actual_scores.to_csv(output / "actual_edge_scores.csv", index=False)
    result.edge_summary.to_csv(output / "edge_summary.csv", index=False)
    result.edge_by_fold.to_csv(output / "edge_by_fold.csv", index=False)
    result.oof_selected.to_csv(output / "oof_selected_states.csv", index=False)
    result.actual_selected.to_csv(output / "actual_selected_states.csv", index=False)
    result.selection_by_fold.to_csv(output / "selection_by_fold.csv", index=False)
    result.selection_by_state.to_csv(output / "selection_by_state.csv", index=False)
    result.concentration.to_csv(output / "concentration.csv", index=False)
    result.placebo.to_csv(output / "placebo_metrics.csv", index=False)
    result.feature_importance.to_csv(output / "feature_importance.csv", index=False)
    result.family_importance.to_csv(output / "family_importance.csv", index=False)
    if not result.oof_headline.empty:
        result.oof_headline.reset_index().to_csv(output / "oof_headline.csv", index=False)
    if not result.actual_headline.empty:
        result.actual_headline.reset_index().to_csv(
            output / "actual_headline.csv", index=False
        )
    _save_frames("oof", result.oof_daily, output)
    _save_frames("actual", result.actual_daily, output)
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
                    "oof_groups": int(len(result.oof_selected)),
                    "actual_groups": int(len(result.actual_selected)),
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
