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
from src.research.v4_2_donor_state2_sgov_tqqq_runtime import (
    run_donor_state2_sgov_tqqq,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_donor_state2_sgov_tqqq_v4_13_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_qqq_tqqq_donor_state2_sgov_tqqq_v4_13_research"
)


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


def _report(
    model: Any,
    headlines: dict[str, pd.DataFrame],
    predictions: dict[str, pd.DataFrame],
    diagnostics: dict[str, Any],
) -> str:
    lines = [
        "# v4.13 donor formal-state2 SGOV/TQQQ budget",
        "",
        f"Decision: `{diagnostics['decision']}`",
        "",
        "## Donor evidence",
        "",
        f"- formal state-2 episodes: {int(model.cluster_metrics['donor_episodes'])}",
        f"- macro clusters: {int(model.cluster_metrics['macro_clusters'])}",
        f"- cluster OOF AUC: {float(model.cluster_metrics['roc_auc']):.3f}",
        f"- cluster OOF IC: {float(model.cluster_metrics['spearman_ic']):.3f}",
        f"- cluster quartile spread: {float(model.cluster_metrics['top_bottom_quartile_spread']):.2%}",
        f"- LOAO AUC: {float(model.loao_metrics['roc_auc']):.3f}",
        f"- LOAO IC: {float(model.loao_metrics['spearman_ic']):.3f}",
        f"- LOAO quartile spread: {float(model.loao_metrics['top_bottom_quartile_spread']):.2%}",
        f"- donor gate passed: {bool(diagnostics['donor_gate']['passed'])}",
        "",
    ]
    for scope in ("primary", "quarantine", "actual"):
        table = headlines[scope]
        lines.extend(
            [
                f"## {scope}",
                "",
                f"Predicted state-2 episodes: {len(predictions[scope])}",
                "",
                "| Strategy | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
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
        lines.append("")
    lines.extend(
        [
            "## Gates",
            "",
            f"- primary gate: {bool(diagnostics['primary_gate']['passed'])}",
            f"- contradiction gate: {bool(diagnostics['contradiction_gate']['passed'])}",
            f"- prospective shadow authorized: {bool(diagnostics['shadow_candidate_authorized'])}",
            "- v4.2 and actionable alerts remain unchanged.",
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
    (
        model,
        predictions,
        headlines,
        results,
        attribution,
        diagnostics,
    ) = run_donor_state2_sgov_tqqq(bars, bridge_contract, contract)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    model.donor_episodes.to_csv(output / "donor_state2_episodes.csv", index=False)
    model.cluster_oof.to_csv(output / "donor_cluster_oof.csv", index=False)
    model.cluster_fold_metrics.to_csv(
        output / "donor_cluster_fold_metrics.csv", index=False
    )
    model.loao_predictions.to_csv(output / "donor_loao_predictions.csv", index=False)
    model.loao_asset_metrics.to_csv(
        output / "donor_loao_asset_metrics.csv", index=False
    )
    model.asset_spreads.to_csv(output / "donor_asset_spreads.csv", index=False)
    model.cluster_contributions.to_csv(
        output / "donor_cluster_contributions.csv", index=False
    )
    model.coefficients.to_csv(output / "donor_coefficients.csv", index=False)
    _write_json(output / "donor_cluster_metrics.json", model.cluster_metrics)
    _write_json(output / "donor_loao_metrics.json", model.loao_metrics)

    for scope, table in predictions.items():
        table.to_csv(output / f"{scope}_target_predictions.csv", index=False)
    for scope, table in headlines.items():
        table.reset_index().to_csv(output / f"{scope}_headline.csv", index=False)
    for scope, table in attribution.items():
        table.to_csv(output / f"{scope}_episode_attribution.csv", index=False)
    for scope, scope_results in results.items():
        for strategy, result in scope_results.items():
            result.daily.reset_index(names="date").to_csv(
                output / f"{scope}_{strategy}_daily.csv", index=False
            )
            result.trades.to_csv(
                output / f"{scope}_{strategy}_trades.csv", index=False
            )

    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(
        _report(model, headlines, predictions, diagnostics), encoding="utf-8"
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
        "decision": diagnostics["decision"],
        "shadow_candidate_authorized": diagnostics[
            "shadow_candidate_authorized"
        ],
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _json_safe(
                {
                    "decision": diagnostics["decision"],
                    "donor_gate": diagnostics["donor_gate"],
                    "primary_gate": diagnostics["primary_gate"],
                    "contradiction_gate": diagnostics["contradiction_gate"],
                    "scope_samples": diagnostics["scope_samples"],
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
