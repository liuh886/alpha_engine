#!/usr/bin/env python3
"""Compile or execute one fixed-context model optimization campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cross_sectional_experiment_runner import run_cross_sectional_experiment
from src.research.optimization_campaign import (
    OptimizationCampaignError,
    compile_optimization_campaign,
    verify_compiled_optimization_campaign,
)
from src.research.research_receipt import write_research_receipt


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--campaign", type=Path)
    mode.add_argument("--manifest", type=Path)
    parser.add_argument("--submissions", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute a previously compiled manifest after re-verifying all context",
    )
    args = parser.parse_args()

    try:
        if args.campaign is not None:
            if args.execute:
                parser.error("compile and execute are separate fail-closed phases")
            if args.submissions is None or args.output_dir is None:
                parser.error("--campaign requires --submissions and --output-dir")
            compiled = compile_optimization_campaign(
                args.campaign,
                args.submissions,
                args.output_dir,
            )
            payload = {
                "campaign_id": compiled.campaign_id,
                "context_sha256": compiled.context_sha256,
                "model_data_bundle_id": compiled.model_data_bundle_id,
                "compiled_spec": str(compiled.compiled_spec_path),
                "manifest": str(compiled.manifest_path),
                "candidate_trial_ids": dict(compiled.candidate_trial_ids),
                "status": "compiled",
                "research_only": True,
                "trade_ready": False,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if not args.execute:
            parser.error("--manifest requires --execute")
        manifest_path = args.manifest.resolve()
        manifest = verify_compiled_optimization_campaign(manifest_path)
        spec_path = manifest_path.parent / str(manifest["compiled_spec"])
        run_dir = manifest_path.parent / "run"
        receipt = run_cross_sectional_experiment(spec_path, output_dir=run_dir)
        receipt = write_research_receipt(spec_path, receipt, output_dir=run_dir)
        verify_compiled_optimization_campaign(manifest_path)
        campaign_receipt = {
            "schema_version": "1.0",
            "campaign_id": manifest["campaign_id"],
            "context_sha256": manifest["context_sha256"],
            "compiled_spec_sha256": manifest["compiled_spec_sha256"],
            "model_data_bundle_id": manifest["context"]["model_data_bundle"][
                "bundle_id"
            ],
            "candidate_trial_ids": manifest["candidate_trial_ids"],
            "candidate_count": manifest["candidate_count"],
            "shared_execution": "single_experiment_union_feature_load",
            "status": receipt.get("status"),
            "decision": receipt.get("decision"),
            "supported": receipt.get("supported", False),
            "automatic_promotion": False,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(manifest_path.parent / "optimization-receipt.json", campaign_receipt)
        print(json.dumps(campaign_receipt, indent=2, sort_keys=True))
        return 0 if receipt.get("status") == "completed" else 2
    except OptimizationCampaignError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
