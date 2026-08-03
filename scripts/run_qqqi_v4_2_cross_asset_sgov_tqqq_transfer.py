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
from src.research.v4_2_cross_asset_sgov_tqqq_transfer_runtime import (
    run_cross_asset_sgov_tqqq_transfer,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_cross_asset_sgov_tqqq_transfer_v4_12_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_qqq_tqqq_cross_asset_sgov_tqqq_transfer_v4_12_research"
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _metric(table: pd.DataFrame, strategy: str, column: str) -> float:
    return float(table.loc[strategy, column])


def _render_report(
    model_metrics: dict[str, Any],
    headlines: dict[str, pd.DataFrame],
    target_events: pd.DataFrame,
    diagnostics: dict[str, Any],
) -> str:
    actual = headlines["actual"]
    proxy = headlines["qqq_proxy"]
    donor_gate = diagnostics["donor_gate"]
    strategy_gate = diagnostics["strategy_gate"]
    lines = [
        "# v4.12 cross-asset independent events and SGOV/TQQQ transfer",
        "",
        f"Decision: `{diagnostics['decision']}`",
        "",
        "## Donor event evidence",
        "",
        f"- donor asset-events: {int(model_metrics['donor_events'])}",
        f"- macro clusters: {int(model_metrics['macro_clusters'])}",
        f"- cluster-OOF ROC AUC: {float(model_metrics['roc_auc']):.3f}",
        f"- cluster-OOF Spearman IC: {float(model_metrics['spearman_ic']):.3f}",
        f"- top-minus-bottom quartile spread: {float(model_metrics['top_bottom_quartile_spread']):.2%}",
        f"- positive donor-asset spread count: {int(model_metrics['positive_asset_spread_count'])}/6",
        f"- donor gate passed: {bool(donor_gate['passed'])}",
        "",
        "## Actual QQQI common window",
        "",
        "| Strategy | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in actual.index:
        lines.append(
            "| "
            + strategy
            + f" | {_metric(actual, strategy, 'cagr'):.2%}"
            + f" | {_metric(actual, strategy, 'sharpe'):.3f}"
            + f" | {_metric(actual, strategy, 'sortino'):.3f}"
            + f" | {_metric(actual, strategy, 'max_drawdown'):.2%}"
            + f" | {_metric(actual, strategy, 'calmar'):.3f}"
            + f" | {_metric(actual, strategy, 'turnover_units'):.1f} |"
        )
    lines.extend(
        [
            "",
            "## QQQ-proxy SGOV common window",
            "",
            "| Strategy | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for strategy in proxy.index:
        lines.append(
            "| "
            + strategy
            + f" | {_metric(proxy, strategy, 'cagr'):.2%}"
            + f" | {_metric(proxy, strategy, 'sharpe'):.3f}"
            + f" | {_metric(proxy, strategy, 'sortino'):.3f}"
            + f" | {_metric(proxy, strategy, 'max_drawdown'):.2%}"
            + f" | {_metric(proxy, strategy, 'calmar'):.3f}"
            + f" | {_metric(proxy, strategy, 'turnover_units'):.1f} |"
        )
    bucket_counts = target_events["probability_bucket"].value_counts().to_dict()
    lines.extend(
        [
            "",
            "## Target events and gates",
            "",
            f"- QQQ target events: {len(target_events)}",
            f"- target probability buckets: {bucket_counts}",
            f"- strategy gate passed: {bool(strategy_gate['passed'])}",
            f"- shadow candidate authorized: {bool(diagnostics['shadow_candidate_authorized'])}",
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
        target_events,
        headlines,
        results_by_scope,
        event_attribution,
        diagnostics,
    ) = run_cross_asset_sgov_tqqq_transfer(
        bars,
        bridge_contract,
        contract,
    )

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    model.donor_events.to_csv(output / "donor_events.csv", index=False)
    model.oof_predictions.to_csv(output / "donor_oof_predictions.csv", index=False)
    model.fold_metrics.to_csv(output / "donor_fold_metrics.csv", index=False)
    model.asset_spreads.to_csv(output / "donor_asset_spreads.csv", index=False)
    model.cluster_contributions.to_csv(
        output / "donor_cluster_contributions.csv", index=False
    )
    model.coefficients.to_csv(output / "donor_model_coefficients.csv", index=False)
    target_events.to_csv(output / "target_qqq_events.csv", index=False)

    for scope, table in headlines.items():
        table.reset_index().to_csv(output / f"{scope}_headline.csv", index=False)
    for scope, table in event_attribution.items():
        table.to_csv(output / f"{scope}_target_event_attribution.csv", index=False)
    for scope, results in results_by_scope.items():
        for strategy, result in results.items():
            result.daily.reset_index(names="date").to_csv(
                output / f"{scope}_{strategy}_daily.csv", index=False
            )
            result.trades.to_csv(
                output / f"{scope}_{strategy}_trades.csv", index=False
            )

    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "donor_aggregate_metrics.json", model.aggregate_metrics)
    report = _render_report(
        model.aggregate_metrics,
        headlines,
        target_events,
        diagnostics,
    )
    (output / "report.md").write_text(report, encoding="utf-8")

    evidence_files = sorted(
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
        "files": {path.name: _sha256(path) for path in evidence_files},
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _json_safe(
                {
                    "decision": diagnostics["decision"],
                    "donor_gate": diagnostics["donor_gate"],
                    "strategy_gate": diagnostics["strategy_gate"],
                    "target_event_count": len(target_events),
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
