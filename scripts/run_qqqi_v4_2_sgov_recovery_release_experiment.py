#!/usr/bin/env python3
"""Run the frozen SGOV-to-QQQI/TQQQ recovery-release ablations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_sgov_recovery_release_experiment import (
    run_sgov_recovery_release_comparison,
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
            "qqqi_qqq_tqqq_v4_2_sgov_recovery_release_v4_4_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_sgov_recovery_release_v4_4_research"
        ),
    )
    args = parser.parse_args()

    release_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    baseline_path = Path(release_contract["boundaries"]["baseline_contract"])
    sgov_path = Path(release_contract["boundaries"]["sgov_contract"])
    attribution_path = Path(
        release_contract["boundaries"]["attribution_contract"]
    )
    baseline_contract = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    sgov_contract = yaml.safe_load(sgov_path.read_text(encoding="utf-8"))
    attribution_contract = yaml.safe_load(
        attribution_path.read_text(encoding="utf-8")
    )

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(release_contract["data"]["required_symbols"])),
        start=release_contract["data"]["start_date"],
        end=args.end_date or release_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    (
        headline,
        results,
        chronological,
        episodes,
        precursor_events,
        diagnostics,
    ) = run_sgov_recovery_release_comparison(
        bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        release_contract,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    headline.to_csv(output / "headline_metrics.csv")
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
    for key, table in episodes.items():
        table.to_csv(output / f"drawdown_episodes_{key}.csv", index=False)
        table.loc[table["major_episode"]].sort_values("severity_rank").to_csv(
            output / f"major_drawdown_episodes_{key}.csv", index=False
        )
    for key, table in precursor_events.items():
        table.to_csv(output / f"precursor_events_{key}.csv", index=False)

    contracts = {
        "release": args.contract,
        "baseline": baseline_path,
        "sgov": sgov_path,
        "attribution": attribution_path,
    }
    summary = {
        "schema_version": "1.0",
        "experiment_id": release_contract["experiment_id"],
        "parent_experiment_id": release_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contracts": {
            key: {"path": str(path), "sha256": _sha256(path)}
            for key, path in contracts.items()
        },
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "chronological_metrics": chronological.to_dict(orient="records"),
        "candidate_gates": diagnostics["candidate_gates"],
        "authorized_candidates": diagnostics["authorized_candidates"],
        "tail_risk": diagnostics["tail_risk"],
        "sample": {
            "start": diagnostics["common_sample_start"],
            "end": diagnostics["common_sample_end"],
            "observations": diagnostics["observations"],
        },
        "decision": (
            "prospective_challenger_authorized"
            if diagnostics["authorized_candidates"]
            else "retain_v4_2_and_static_risk_profiles"
        ),
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
        "experiment_id": release_contract["experiment_id"],
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
