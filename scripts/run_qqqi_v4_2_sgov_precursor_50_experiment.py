#!/usr/bin/env python3
"""Run the one-shot 50% TQQQ recovery-precursor experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_sgov_precursor_50_experiment import (
    BOLD_KEY,
    run_precursor_50_comparison,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_sgov_precursor_50_v4_5_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_sgov_precursor_50_v4_5_research"
        ),
    )
    args = parser.parse_args()

    bold_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    boundary_paths = {
        key: Path(bold_contract["boundaries"][key])
        for key in (
            "baseline_contract",
            "sgov_contract",
            "attribution_contract",
            "prior_release_contract",
        )
    }
    contracts = {
        key: yaml.safe_load(path.read_text(encoding="utf-8"))
        for key, path in boundary_paths.items()
    }

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(bold_contract["data"]["required_symbols"])),
        start=bold_contract["data"]["start_date"],
        end=args.end_date or bold_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    (
        headline,
        results,
        chronological,
        episodes,
        events_vs_static,
        marginal_events,
        diagnostics,
    ) = run_precursor_50_comparison(
        bars,
        contracts["baseline_contract"],
        contracts["sgov_contract"],
        contracts["attribution_contract"],
        contracts["prior_release_contract"],
        bold_contract,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    headline.to_csv(output / "headline_metrics.csv")
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    episodes.to_csv(output / "drawdown_episodes_tqqq_precursor_50.csv", index=False)
    episodes.loc[episodes["major_episode"]].sort_values("severity_rank").to_csv(
        output / "major_drawdown_episodes_tqqq_precursor_50.csv", index=False
    )
    events_vs_static.to_csv(output / "precursor_50_events_vs_static.csv", index=False)
    marginal_events.to_csv(output / "precursor_50_marginal_events_vs_25.csv", index=False)
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)

    all_paths = {"bold": args.contract, **boundary_paths}
    summary = {
        "schema_version": "1.0",
        "experiment_id": bold_contract["experiment_id"],
        "parent_experiment_id": bold_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contracts": {
            key: {"path": str(path), "sha256": _sha256(path)}
            for key, path in all_paths.items()
        },
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "chronological_metrics": chronological.to_dict(orient="records"),
        "shadow_gate": diagnostics["shadow_gate"],
        "tail_risk": diagnostics["tail_risk"],
        "sample": {
            "start": diagnostics["common_sample_start"],
            "end": diagnostics["common_sample_end"],
            "observations": diagnostics["observations"],
        },
        "decision": (
            "shadow_monitor_authorized"
            if diagnostics["shadow_gate"]["shadow_monitor_authorized"]
            else "retain_25_percent_precursor_as_deferred_shadow"
        ),
        "candidate": BOLD_KEY,
        "production_alert_change_authorized": False,
        "direct_promotion_authorized": False,
    }
    summary_path = output / "experiment_summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "experiment_id": bold_contract["experiment_id"],
        "outputs": {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
        },
    }
    (output / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
