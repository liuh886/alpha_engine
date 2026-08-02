#!/usr/bin/env python3
"""Run the predeclared SGOV defensive-asset challengers against v4.2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_sgov_defense_experiment import run_sgov_defense_comparison


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment-contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_sgov_defense_v4_3_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqqi_qqq_tqqq_v4_2_sgov_defense_v4_3_research"
        ),
    )
    args = parser.parse_args()

    experiment = yaml.safe_load(
        args.experiment_contract.read_text(encoding="utf-8")
    )
    bridge_contract_path = Path(experiment["boundaries"]["signal_contract"])
    bridge = yaml.safe_load(bridge_contract_path.read_text(encoding="utf-8"))
    symbols = [*experiment["boundaries"]["tradable_symbols"], *experiment["boundaries"]["signal_symbols"]]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=experiment["data"]["start_date"],
        end=args.end_date or experiment["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    metrics, results, chronological, diagnostics = run_sgov_defense_comparison(
        bars, bridge, experiment
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "headline_metrics.csv")
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)

    summary = {
        "schema_version": "1.0",
        "experiment_id": experiment["experiment_id"],
        "parent_experiment_id": experiment["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contract": {
            "path": str(args.experiment_contract),
            "sha256": _sha256(args.experiment_contract),
            "signal_contract_path": str(bridge_contract_path),
            "signal_contract_sha256": _sha256(bridge_contract_path),
        },
        "metrics": metrics.reset_index().to_dict(orient="records"),
        "diagnostics": diagnostics,
        "decision": "research_challengers_only_no_automatic_promotion",
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
        "experiment_id": experiment["experiment_id"],
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
