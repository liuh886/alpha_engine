#!/usr/bin/env python3
"""Run the frozen BYD v1.2 promotion challenge from immutable inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    prepare_common_dataset,
)
from src.research.byd_v1_2_promotion_challenge import (
    BASELINE,
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    build_evaluation,
    decide,
    episode_attribution,
    period_attribution,
    run_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    primary_results, diagnostics = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress_results, stress_diagnostics = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    if not diagnostics.equals(stress_diagnostics):
        raise RuntimeError("candidate decisions drifted across cost scenarios")

    evaluation = build_evaluation(primary_results, stress_results)
    periods = period_attribution(primary_results)
    episodes = episode_attribution(primary_results)
    decision = decide(evaluation, periods, episodes)

    evaluation.to_csv(
        output / "evaluation.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    periods.to_csv(
        output / "period_attribution.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    episodes.to_csv(
        output / "episode_attribution.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    diagnostics.to_csv(
        output / "state_and_budget_ledger.csv",
        index=True,
        float_format="%.12f",
        lineterminator="\n",
    )

    daily_root = output / "daily"
    trades_root = output / "trades"
    daily_root.mkdir(exist_ok=True)
    trades_root.mkdir(exist_ok=True)
    for name, result in primary_results.items():
        result.daily.to_csv(
            daily_root / f"{name}_primary.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )
        result.trades.to_csv(
            trades_root / f"{name}_primary.csv",
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        stress_results[name].daily.to_csv(
            daily_root / f"{name}_stress.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )

    full_primary = evaluation.loc[
        (evaluation["scenario"] == "primary")
        & (evaluation["window"] == "full_overlap")
    ].set_index("model")
    baseline = full_primary.loc[BASELINE]
    headline = {}
    for model, row in full_primary.iterrows():
        headline[str(model)] = {
            "cagr": float(row["cagr"]),
            "cagr_delta_vs_v1_1": float(row["cagr"] - baseline["cagr"]),
            "total_return": float(row["total_return"]),
            "max_drawdown": float(row["max_drawdown"]),
            "calmar": float(row["calmar"]),
            "financed_sessions": int(row["financed_sessions"]),
            "round_trips_per_year": float(row["round_trips_per_year"]),
        }

    manifest = {
        "schema_version": "byd_v1_2_promotion_challenge_result_v1",
        "experiment_id": "byd_v1_2_promotion_challenge_v1",
        "issue": 592,
        "contract_path": str(args.contract),
        "contract_sha256": sha256(args.contract),
        "data_cutoff": str(common.index.max().date()),
        "session_count": int(len(common)),
        "decision": asdict(decision),
        "headline": headline,
        "historical_evidence_consumed": True,
        "promotion_authorized": False,
        "research_only": True,
        "trade_ready": False,
    }
    manifest_path = output / "decision.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
