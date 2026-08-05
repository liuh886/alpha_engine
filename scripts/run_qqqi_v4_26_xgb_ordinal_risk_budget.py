from __future__ import annotations

import argparse
import copy
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
from src.research.v4_26_xgb_ordinal_risk_budget import (
    OrdinalRiskBudgetResult,
    run_ordinal_risk_budget_study,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import run_bridge_allocation_comparison

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_ordinal_risk_budget_v4_26_research.yaml"
)
DEFAULT_V416_CONTRACT = Path(
    "configs/research_paradigms/qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_xgb_ordinal_risk_budget_v4_26_research"
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


def _effective_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Add inherited v4.24 edge labels required only by the shared data builder."""
    output = copy.deepcopy(contract)
    output["states"]["edges"] = [
        {"edge": "defense_vs_bridge", "lower": "defense", "higher": "bridge"},
        {"edge": "bridge_vs_core", "lower": "bridge", "higher": "core"},
        {"edge": "core_vs_leveraged", "lower": "core", "higher": "leveraged"},
    ]
    return output


def _decision(result: OrdinalRiskBudgetResult) -> str:
    if not bool(result.phase1_gate["passed"]):
        return "xgb_ordinal_risk_budget_not_supported"
    if not bool(result.phase2_gate["passed"]):
        return "xgb_ordinal_signal_supported_policy_failed"
    if not bool(result.actual_contradiction_gate["passed"]):
        return "xgb_ordinal_candidate_blocked_by_actual_window"
    return "xgb_ordinal_risk_budget_candidate_shadow_supported"


def _fmt(value: Any, *, percent: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.2%}" if percent else f"{number:.4f}"


def _actual_summary(result: OrdinalRiskBudgetResult) -> dict[str, Any]:
    table = result.actual_scores
    selected_regret = float(table["selected_utility_regret"].mean())
    baseline_regret = float(table["baseline_utility_regret"].mean())
    return {
        "groups": int(len(table)),
        "mean_utility_advantage": float(
            table["selected_utility_advantage_vs_v4_2"].mean()
        ),
        "median_utility_advantage": float(
            table["selected_utility_advantage_vs_v4_2"].median()
        ),
        "total_utility_advantage": float(
            table["selected_utility_advantage_vs_v4_2"].sum()
        ),
        "top_two_rate": float(table["selected_top_two"].mean()),
        "utility_regret_reduction": (
            1.0 - selected_regret / baseline_regret
            if baseline_regret > 1e-12
            else np.nan
        ),
        "state_counts": {
            str(key): int(value)
            for key, value in table["selected_state"].value_counts().sort_index().items()
        },
    }


def _report(
    result: OrdinalRiskBudgetResult,
    decision: str,
    actual_summary: dict[str, Any],
) -> str:
    phase1 = result.phase1_gate
    lines = [
        "# v4.26 XGBoost ordinal risk-budget convergence study",
        "",
        f"Decision: `{decision}`",
        "",
        "## Frozen candidate architecture",
        "",
        "- one four-class `multi:softprob` XGBoost model;",
        "- 35 unchanged v4.24 market, credit/duration and v4.2 context inputs;",
        "- exact v4.24 ten-session path utility and cost labels;",
        "- no action descriptors, thresholds, class calibration or parameter search;",
        "- selected state is the posterior expected risk index rounded half-up;",
        "- Phase 2 is fail-closed unless every Phase 1 check passes.",
        "",
        "## Phase 1 headline",
        "",
        f"- macro one-vs-rest AUC: {_fmt(phase1.get('macro_ovr_auc'))};",
        f"- quadratic weighted kappa: {_fmt(phase1.get('quadratic_weighted_kappa'))};",
        f"- macro recall: {_fmt(phase1.get('macro_recall'))};",
        f"- multiclass log loss: {_fmt(phase1.get('multiclass_log_loss'))};",
        f"- mean absolute state error: {_fmt(phase1.get('mean_absolute_state_error'))};",
        f"- utility-regret reduction vs v4.2: {_fmt(phase1.get('utility_regret_reduction'), percent=True)};",
        f"- median utility advantage: {_fmt(phase1.get('median_utility_advantage_vs_v4_2'), percent=True)};",
        f"- positive outer folds: {phase1.get('positive_outer_folds')};",
        f"- top-two utility rate: {_fmt(phase1.get('top_two_rate'), percent=True)};",
        f"- placebo beat rate: {_fmt(phase1.get('placebo_beat_rate'), percent=True)};",
        f"- minimum state selections: {phase1.get('minimum_state_selections')};",
        f"- maximum state share: {_fmt(phase1.get('maximum_state_selection_share'), percent=True)};",
        f"- largest feature SHAP share: {_fmt(phase1.get('largest_single_feature_shap_share'), percent=True)};",
        f"- largest family SHAP share: {_fmt(phase1.get('largest_feature_family_shap_share'), percent=True)};",
        f"- Phase 1 passed: {bool(phase1['passed'])}.",
        "",
        "## Model metrics",
        "",
        "| Scope | Groups | Macro AUC | QWK | Macro recall | Log loss | Exact accuracy | MA state error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result.model_metrics.itertuples(index=False):
        lines.append(
            f"| {row.scope} | {int(row.groups)} | {_fmt(row.macro_ovr_auc)}"
            f" | {_fmt(row.quadratic_weighted_kappa)} | {_fmt(row.macro_recall)}"
            f" | {_fmt(row.multiclass_log_loss)} | {_fmt(row.exact_state_accuracy)}"
            f" | {_fmt(row.mean_absolute_state_error)} |"
        )
    lines.extend(
        [
            "",
            "## Chronological utility evidence",
            "",
            "| Fold | Groups | Regret reduction | Top-two | Median advantage | Total advantage |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result.selection_by_fold.itertuples(index=False):
        lines.append(
            f"| {row.fold} | {int(row.groups)} | {_fmt(row.utility_regret_reduction, percent=True)}"
            f" | {_fmt(row.top_two_rate, percent=True)}"
            f" | {_fmt(row.median_utility_advantage_vs_v4_2, percent=True)}"
            f" | {_fmt(row.total_utility_advantage_vs_v4_2, percent=True)} |"
        )
    lines.extend(
        [
            "",
            "## Selected-state coverage",
            "",
            "| State | Blocks | Share | Top-two | Median advantage |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in result.selection_by_state.itertuples(index=False):
        lines.append(
            f"| {row.state} | {int(row.selected_groups)} | {_fmt(row.selection_share, percent=True)}"
            f" | {_fmt(row.top_two_rate, percent=True)}"
            f" | {_fmt(row.median_utility_advantage_vs_v4_2, percent=True)} |"
        )
    lines.extend(
        [
            "",
            "## Actual 2024+ quarantine read-through",
            "",
            f"- blocks: {actual_summary['groups']};",
            f"- mean utility advantage: {_fmt(actual_summary['mean_utility_advantage'], percent=True)};",
            f"- median utility advantage: {_fmt(actual_summary['median_utility_advantage'], percent=True)};",
            f"- total utility advantage: {_fmt(actual_summary['total_utility_advantage'], percent=True)};",
            f"- top-two rate: {_fmt(actual_summary['top_two_rate'], percent=True)};",
            f"- regret reduction: {_fmt(actual_summary['utility_regret_reduction'], percent=True)};",
            f"- state counts: `{json.dumps(actual_summary['state_counts'], sort_keys=True)}`.",
            "",
            "## Candidate decision boundary",
            "",
            f"- Phase 2 skipped: {bool(result.phase2_gate.get('skipped', False))};",
            f"- candidate shadow authorized: {bool(result.final_gate['candidate_shadow_authorized'])};",
            "- direct promotion, v4.2 changes, Telegram changes and Issue #348 changes remain prohibited;",
            "- on failure, v4.2 becomes the converged candidate and the current daily-feature XGBoost path closes.",
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
        if frame.empty:
            continue
        frame.to_csv(output / f"{prefix}_{name}_trades.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--v4-16-contract", type=Path, default=DEFAULT_V416_CONTRACT)
    parser.add_argument("--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    declared_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    contract = _effective_contract(declared_contract)
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
    result = run_ordinal_risk_budget_study(
        bars,
        proxy_results[BASELINE_KEY].daily,
        actual_results[BASELINE_KEY].daily,
        contract,
        v416_contract,
    )
    decision = _decision(result)
    actual_summary = _actual_summary(result)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    result.proxy_frame.to_csv(output / "proxy_ordinal_path_utility_frame.csv", index=False)
    result.actual_frame.to_csv(output / "actual_ordinal_path_utility_frame.csv", index=False)
    result.fold_coverage.to_csv(output / "fold_coverage.csv", index=False)
    result.oof_scores.to_csv(output / "oof_ordinal_scores.csv", index=False)
    result.actual_scores.to_csv(output / "actual_ordinal_scores.csv", index=False)
    result.model_metrics.to_csv(output / "model_metrics.csv", index=False)
    result.class_metrics.to_csv(output / "class_metrics.csv", index=False)
    result.confusion.to_csv(output / "confusion_matrix.csv", index=False)
    result.selection_by_fold.to_csv(output / "selection_by_fold.csv", index=False)
    result.selection_by_state.to_csv(output / "selection_by_state.csv", index=False)
    result.concentration.to_csv(output / "concentration.csv", index=False)
    result.placebo.to_csv(output / "placebo_metrics.csv", index=False)
    result.feature_importance.to_csv(output / "feature_importance.csv", index=False)
    result.family_importance.to_csv(output / "family_importance.csv", index=False)
    if not result.oof_headline.empty:
        result.oof_headline.reset_index().to_csv(output / "oof_headline.csv", index=False)
    if not result.actual_headline.empty:
        result.actual_headline.reset_index().to_csv(output / "actual_headline.csv", index=False)
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
        "actual_quarantine_summary": actual_summary,
        "final_gate": result.final_gate,
        "runtime_data_builder_compatibility": {
            "inherited_v4_24_edge_labels_added": True,
            "used_as_model_targets": False,
        },
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(
        _report(result, decision, actual_summary), encoding="utf-8"
    )

    files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": declared_contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "v4_16_contract_path": str(args.v4_16_contract),
        "v4_16_contract_sha256": _sha256(args.v4_16_contract),
        "bridge_contract_path": str(args.bridge_contract),
        "bridge_contract_sha256": _sha256(args.bridge_contract),
        "decision": decision,
        "candidate_shadow_authorized": bool(
            result.final_gate["candidate_shadow_authorized"]
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
                    "actual_summary": actual_summary,
                    "final_gate": result.final_gate,
                    "oof_groups": int(len(result.oof_scores)),
                    "actual_groups": int(len(result.actual_scores)),
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
