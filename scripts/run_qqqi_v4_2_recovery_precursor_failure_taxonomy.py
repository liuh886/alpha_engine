#!/usr/bin/env python3
"""Run the governed v4.2 recovery-precursor failure taxonomy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_recovery_precursor_failure_taxonomy import (
    run_recovery_precursor_failure_taxonomy,
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
            "qqqi_qqq_tqqq_v4_2_recovery_precursor_failure_taxonomy_v4_7_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_recovery_precursor_failure_taxonomy_v4_7_research"
        ),
    )
    args = parser.parse_args()

    taxonomy_contract = _load(args.contract)
    boundaries = taxonomy_contract["boundaries"]
    paths = {
        "taxonomy": args.contract,
        "baseline": Path(boundaries["baseline_contract"]),
        "sgov": Path(boundaries["sgov_contract"]),
        "attribution": Path(boundaries["attribution_contract"]),
        "prior_release": Path(boundaries["prior_release_contract"]),
        "bold": Path(boundaries["bold_contract"]),
        "proxy": Path(boundaries["proxy_contract"]),
    }
    contracts = {key: _load(path) for key, path in paths.items()}

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(taxonomy_contract["data"]["required_symbols"])),
        start=taxonomy_contract["data"]["start_date"],
        end=args.end_date or taxonomy_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    result = run_recovery_precursor_failure_taxonomy(
        bars,
        contracts["baseline"],
        contracts["sgov"],
        contracts["attribution"],
        contracts["prior_release"],
        contracts["bold"],
        contracts["proxy"],
        contracts["taxonomy"],
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    result["event_taxonomy"].to_csv(
        output / "recovery_precursor_event_taxonomy.csv", index=False
    )
    result["feature_separation"].to_csv(
        output / "feature_separation.csv", index=False
    )
    result["leave_one_event_out"].to_csv(
        output / "leave_one_event_out.csv", index=False
    )
    result["failure_type_summary"].to_csv(
        output / "failure_type_summary.csv", index=False
    )

    proxy_result = result["proxy_result"]
    proxy_result["proxy_marginal_events"].to_csv(
        output / "marginal_50_vs_25_qqq_proxy.csv", index=False
    )
    proxy_result["overlap_concordance"].to_csv(
        output / "actual_qqqi_overlap_concordance.csv", index=False
    )

    summary = {
        "schema_version": "1.0",
        "experiment_id": taxonomy_contract["experiment_id"],
        "parent_experiment_id": taxonomy_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contracts": {
            key: {"path": str(path), "sha256": _sha256(path)}
            for key, path in paths.items()
        },
        "decision": result["decision"],
        "top_feature_separation": result["feature_separation"]
        .head(10)
        .to_dict(orient="records"),
        "events": result["event_taxonomy"].to_dict(orient="records"),
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
        "experiment_id": taxonomy_contract["experiment_id"],
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
