#!/usr/bin/env python3
"""Reproduce the research-only BYD convex-momentum evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from src.research.byd_515180_allocation import prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import run_full_diagnostic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(frame, path: Path, *, index: bool) -> None:
    frame.to_csv(
        path,
        index=index,
        float_format="%.12f",
        lineterminator="\n",
    )


def main() -> int:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    evidence = run_full_diagnostic(common, signals)

    write_csv(evidence["evaluation"], output / "evaluation.csv", index=False)
    write_csv(
        evidence["periods"], output / "period_attribution.csv", index=False
    )
    write_csv(
        evidence["episodes"], output / "episode_attribution.csv", index=False
    )
    write_csv(
        evidence["leave_one_out"],
        output / "leave_one_episode_out.csv",
        index=False,
    )
    write_csv(
        evidence["ledger"], output / "state_and_exposure_ledger.csv", index=True
    )

    daily_root = output / "daily"
    daily_root.mkdir(exist_ok=True)
    for scenario in ("primary", "stress"):
        for model, result in evidence[f"{scenario}_results"].items():
            write_csv(
                result.daily,
                daily_root / f"{model}_{scenario}.csv",
                index=True,
            )

    decision = asdict(evidence["decision"])
    payload = {
        "schema_version": "byd_convex_momentum_evidence_v1",
        "candidate_id": "byd_v1_2_convex_momentum_budget_v1",
        "issue": 596,
        "source_challenge_issue": 592,
        "contract_path": str(args.contract),
        "contract_sha256": file_sha256(args.contract),
        "historical_cutoff": str(common.index.max().date()),
        "session_count": int(len(common)),
        "decision": decision,
        "episode_bootstrap": evidence["bootstrap"],
        "fresh_historical_holdout": False,
        "historical_evidence_consumed": True,
        "promotion_authorized": False,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output / "decision.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
