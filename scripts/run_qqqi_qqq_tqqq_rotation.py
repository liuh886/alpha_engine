#!/usr/bin/env python3
"""Run the research-only QQQI/QQQ/TQQQ rotation experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_recovery_events import (
    build_recovery_event_frame,
    recovery_config_from_mapping,
    summarize_recovery_returns,
    summarize_recovery_speed,
)
from src.research.etf_rotation_evidence import (
    long_history_asset_context,
    long_history_signal_audit,
    parameter_activity_audit,
    state_reachability_summary,
)
from src.research.etf_rotation_experiment import (
    RotationConfig,
    chronological_split_metrics,
    conditional_asset_metrics,
    fetch_adjusted_daily_bars,
    phase_metrics,
    run_default_comparison,
    run_sensitivity_grid,
    stability_summary,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_rotation_v1.yaml"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_rotation_v1"),
    )
    parser.add_argument("--skip-sensitivity", action="store_true")
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    config = RotationConfig(**contract["strategy"])
    recovery_config = recovery_config_from_mapping(contract["recovery_study"])
    end_date = args.end_date or contract["data"].get("end_date")
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=contract["boundaries"]["tradable_symbols"],
        start=contract["data"]["start_date"],
        end=end_date,
    )
    metrics, results, prepared = run_default_comparison(bars, config)
    reachability = state_reachability_summary(results["rotation_B"])
    recovery_events = build_recovery_event_frame(prepared, recovery_config)
    recovery_return_summary = summarize_recovery_returns(recovery_events, recovery_config)
    recovery_speed_summary = summarize_recovery_speed(recovery_events, recovery_config)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    conditional_asset_metrics(prepared).to_csv(output / "conditional_asset_metrics.csv")
    recovery_events.to_csv(output / "recovery_events_multi_stage.csv", index=False)
    recovery_return_summary.to_csv(output / "recovery_return_summary.csv")
    recovery_speed_summary.to_csv(output / "recovery_speed_summary.csv")
    periods = {
        name: (dates[0], dates[1]) for name, dates in contract["named_periods"].items()
    }
    phase_metrics(
        results,
        periods,
        minimum_sessions=contract["validation"]["minimum_phase_sessions"],
    ).to_csv(output / "phase_metrics.csv")
    chronological_split_metrics(
        results["rotation_B"],
        train_fraction=contract["validation"]["chronological_train_fraction"],
    ).to_csv(output / "chronological_split.csv")
    long_history_asset_context(
        bars,
        periods,
        annual_risk_free_rate=config.annual_risk_free_rate,
    ).to_csv(output / "long_history_asset_context.csv")
    long_history_signal_audit(
        bars["QQQ"],
        config,
        periods,
        version="B",
    ).to_csv(output / "long_history_signal_audit.csv")
    (output / "state_reachability.json").write_text(
        json.dumps(
            reachability,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)

    sensitivity_summary_payload: dict[str, Any] | None = None
    if not args.skip_sensitivity:
        grid = run_sensitivity_grid(bars, config, contract["sensitivity"], version="B")
        grid.to_csv(output / "sensitivity_grid.csv", index=False)
        sensitivity_summary_payload = stability_summary(
            grid, baseline_metrics=results["rotation_B"].metrics
        )
        activity = parameter_activity_audit(
            grid,
            parameter_columns=list(contract["sensitivity"]),
        )
        activity.to_csv(output / "parameter_activity.csv")
        metric_pass = bool(sensitivity_summary_payload.pop("heuristic_robust"))
        inactive_parameters = activity.index[~activity["active"]].tolist()
        sensitivity_summary_payload.update(
            {
                "metric_dispersion_heuristic_pass": metric_pass,
                "structurally_complete": bool(reachability["structurally_complete"]),
                "inactive_parameters": inactive_parameters,
                "overall_robust": bool(
                    metric_pass
                    and reachability["structurally_complete"]
                    and not inactive_parameters
                ),
                "interpretation": (
                    "Metric dispersion is not enough: intended states must be reached and "
                    "sensitivity parameters must affect at least one matched outcome."
                ),
            }
        )
        (output / "stability_summary.json").write_text(
            json.dumps(
                sensitivity_summary_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=_json_default,
            ),
            encoding="utf-8",
        )

    recovery_overview = {
        "shock_episodes": int(recovery_events["shock_episode"].nunique())
        if not recovery_events.empty
        else 0,
        "event_count": int(len(recovery_events)),
        "families": sorted(recovery_events["event_family"].unique().tolist())
        if not recovery_events.empty
        else [],
        "method": (
            "One first trigger per family per material-drawdown episode; signal at close t, "
            "measurement begins at the next open."
        ),
    }
    summary = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "common_price_sample_start": prepared.index.min().date().isoformat(),
        "common_price_sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": results["rotation_B"].metrics["start_date"],
        "economic_return_end": results["rotation_B"].metrics["end_date"],
        "strategy_metrics": metrics.reset_index().to_dict(orient="records"),
        "recovery_study": recovery_overview,
        "state_reachability": reachability,
        "stability": sensitivity_summary_payload,
        "limitations": [
            "QQQI inception is 2024-01-29; 2020 and 2022 cannot be direct three-asset tests.",
            "The common live sample is short and contains limited independent market regimes.",
            "Recovery families are diagnostic definitions, not independently optimized entry rules.",
            "The sensitivity grid is diagnostic and must not be used to promote a fitted winner.",
            (
                "Rotation B did not reach all intended states in the frozen common sample; "
                "TQQQ-specific sensitivity is therefore structurally uninterpretable."
                if not reachability["structurally_complete"]
                else "All intended states were reached in the frozen common sample."
            ),
        ],
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    output_files = sorted(path for path in output.iterdir() if path.is_file())
    manifest = {
        "schema_version": "1.1",
        "research_only": True,
        "trade_ready": False,
        "contract": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "outputs": {path.name: _sha256(path) for path in output_files},
    }
    (output / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
