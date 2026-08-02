#!/usr/bin/env python3
"""Run actual QQQI and QQQ-proxy long-history precursor comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_qqq_proxy_long_history_experiment import (
    run_qqq_proxy_long_history_comparison,
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


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_qqq_proxy_long_history_v4_6_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_qqq_proxy_long_history_v4_6_research"
        ),
    )
    args = parser.parse_args()

    proxy_contract = _load(args.contract)
    boundaries = proxy_contract["boundaries"]
    paths = {
        "proxy": args.contract,
        "baseline": Path(boundaries["baseline_contract"]),
        "sgov": Path(boundaries["sgov_contract"]),
        "attribution": Path(boundaries["attribution_contract"]),
        "prior_release": Path(boundaries["prior_release_contract"]),
        "bold": Path(boundaries["bold_contract"]),
    }
    contracts = {key: _load(path) for key, path in paths.items()}

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(proxy_contract["data"]["required_symbols"])),
        start=proxy_contract["data"]["start_date"],
        end=args.end_date or proxy_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    result = run_qqq_proxy_long_history_comparison(
        bars,
        contracts["baseline"],
        contracts["sgov"],
        contracts["attribution"],
        contracts["prior_release"],
        contracts["bold"],
        contracts["proxy"],
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    result["actual_headline"].to_csv(output / "headline_actual_qqqi.csv")
    result["proxy_headline"].to_csv(output / "headline_qqq_proxy.csv")
    result["actual_chronological"].to_csv(
        output / "chronological_actual_qqqi.csv", index=False
    )
    result["proxy_chronological"].to_csv(
        output / "chronological_qqq_proxy.csv", index=False
    )
    result["actual_episodes"].to_csv(
        output / "drawdown_episodes_actual_qqqi.csv", index=False
    )
    result["proxy_episodes"].to_csv(
        output / "drawdown_episodes_qqq_proxy.csv", index=False
    )
    result["actual_events_vs_static"].to_csv(
        output / "events_vs_static_actual_qqqi.csv", index=False
    )
    result["proxy_events_vs_static"].to_csv(
        output / "events_vs_static_qqq_proxy.csv", index=False
    )
    result["actual_marginal_events"].to_csv(
        output / "marginal_50_vs_25_actual_qqqi.csv", index=False
    )
    result["proxy_marginal_events"].to_csv(
        output / "marginal_50_vs_25_qqq_proxy.csv", index=False
    )
    result["overlap_concordance"].to_csv(
        output / "overlap_event_concordance.csv", index=False
    )

    for sample in ("actual", "proxy"):
        for key, strategy in result[f"{sample}_results"].items():
            strategy.daily.to_csv(output / f"daily_{sample}_{key}.csv")
            strategy.trades.to_csv(output / f"trades_{sample}_{key}.csv", index=False)

    support_gate = result["support_gate"]
    summary = {
        "schema_version": "1.0",
        "experiment_id": proxy_contract["experiment_id"],
        "parent_experiment_id": proxy_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contracts": {
            key: {"path": str(path), "sha256": _sha256(path)}
            for key, path in paths.items()
        },
        "proxy_definition": result["proxy_definition"],
        "samples": {
            "actual_qqqi": {
                "start": result["actual_diagnostics"]["common_sample_start"],
                "end": result["actual_diagnostics"]["common_sample_end"],
                "observations": result["actual_diagnostics"]["observations"],
            },
            "qqq_proxy": {
                "start": result["proxy_diagnostics"]["common_sample_start"],
                "end": result["proxy_diagnostics"]["common_sample_end"],
                "observations": result["proxy_diagnostics"]["observations"],
            },
        },
        "actual_headline": result["actual_headline"].reset_index().to_dict(
            orient="records"
        ),
        "proxy_headline": result["proxy_headline"].reset_index().to_dict(
            orient="records"
        ),
        "actual_shadow_gate": result["actual_diagnostics"]["shadow_gate"],
        "proxy_shadow_gate": result["proxy_diagnostics"]["shadow_gate"],
        "long_sample_support_gate": support_gate,
        "decision": (
            "qqq_proxy_supports_50_percent_structure"
            if support_gate["structural_support_for_50_percent_hypothesis"]
            else "qqq_proxy_does_not_yet_support_50_percent_structure"
        ),
        "actionable_model_authorized": False,
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
        "experiment_id": proxy_contract["experiment_id"],
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
