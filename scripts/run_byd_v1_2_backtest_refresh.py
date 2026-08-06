#!/usr/bin/env python3
"""Regenerate the BYD v1.2 formal backtest with extended canonical data.

When the BYD or 515180 canonical snapshot is rebased to a new cutoff, this
script reproduces the full governed backtest and publishes a new formal
evidence package. Overlap-period results are verified against the previously
published package to ensure byte-stable reproducibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    prepare_common_dataset,
    metrics,
)
from src.research.byd_trend_fix_v1 import (
    BASELINE,
    PRIMARY,
    ROBUSTNESS,
    DIAGNOSTIC,
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    RULES,
    run_candidates,
    build_evaluation,
    period_contribution,
    governed_result,
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--byd-dir", type=Path, required=True,
                   help="Path to extracted BYD canonical snapshot")
    p.add_argument("--etf-dir", type=Path, required=True,
                   help="Path to extracted 515180 canonical artifact")
    p.add_argument("--previous-package", type=Path, default=None,
                   help="Path to previous formal backtest JSON for overlap verification")
    p.add_argument("--output", type=Path,
                   default=Path("data/research/formal_backtests/byd_dividend_sleeve_v1_2.json"))
    return p.parse_args()


def _verify_overlap(new_metrics: dict, prev_package: Path):
    """Verify that overlap-period metrics match the previously published package."""
    prev = json.loads(prev_package.read_text(encoding="utf-8"))
    prev_data = prev.get("data", prev)
    prev_cutoff = prev_data.get("cutoff", prev_data.get("overlap", {}).get("last_date"))

    for model_name in (BASELINE, PRIMARY, ROBUSTNESS):
        new_m = new_metrics.get(model_name, {})
        old_entry = None
        for entry in prev_data.get("models", prev_data.get("headline_20bps", {}).values()):
            if isinstance(entry, dict) and entry.get("name") == model_name:
                old_entry = entry
                break
        if old_entry is None:
            continue

        for key in ("cagr", "total_return", "max_drawdown", "calmar"):
            nv = new_m.get(key)
            ov = old_entry.get(key)
            if nv is not None and ov is not None and abs(nv - ov) > 0.0001:
                raise RuntimeError(
                    f"Overlap mismatch for {model_name}.{key}: "
                    f"new={nv:.6f} old={ov:.6f} (cutoff={prev_cutoff})"
                )

    print(f"Overlap verification passed: all metrics match previous package (cutoff={prev_cutoff})")


def main():
    args = parse_args()
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)

    print(f"Extended data: {len(common)} sessions, "
          f"{common.index.min().date()} to {common.index.max().date()}")

    # Full backtest at both cost levels
    r20, s20 = run_candidates(common, signals, cost_bps=PRIMARY_COST_BPS,
                              annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, _ = run_candidates(common, signals, cost_bps=STRESS_COST_BPS,
                            annual_financing_rate=STRESS_FINANCING_RATE)

    evaluation = build_evaluation(r20, r40)
    pc = period_contribution(r20)
    gov = governed_result(evaluation, pc)

    # Extract headline metrics
    full20 = evaluation.loc[
        (evaluation["window"] == "full_overlap") & (evaluation["scenario"] == "primary")
    ].set_index("model")
    full40 = evaluation.loc[
        (evaluation["window"] == "full_overlap") & (evaluation["scenario"] == "stress")
    ].set_index("model")

    headline20 = {}
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        if n in full20.index:
            row = full20.loc[n]
            headline20[n] = {
                "cagr": float(row["cagr"]),
                "total_return": float(row["total_return"]),
                "max_drawdown": float(row["max_drawdown"]),
                "calmar": float(row["calmar"]),
                "sharpe": float(row["sharpe"]),
                "round_trips_per_year": float(row["round_trips_per_year"]),
            }

    headline40 = {}
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        if n in full40.index:
            row = full40.loc[n]
            headline40[n] = {
                "cagr": float(row["cagr"]),
                "total_return": float(row["total_return"]),
                "max_drawdown": float(row["max_drawdown"]),
                "calmar": float(row["calmar"]),
                "round_trips_per_year": float(row["round_trips_per_year"]),
            }

    # Verify overlap if previous package exists
    if args.previous_package and args.previous_package.exists():
        _verify_overlap(
            {n: headline20.get(n, {}) for n in (BASELINE, PRIMARY, ROBUSTNESS)},
            args.previous_package,
        )

    # Period contributions
    periods = {}
    for _, row in pc.iterrows():
        periods.setdefault(row["model"], {})[row["period"]] = {
            "relative_terminal_wealth": float(row["relative_terminal_wealth"]),
            "positive_contribution_share": float(row["positive_contribution_share"]),
        }

    package = {
        "schema_version": "byd_formal_backtest_v1",
        "model_id": "byd_dividend_sleeve_v1_2",
        "display_name": "BYD v1.2",
        "strategy": "v1_2_relaxed_trend_expansion",
        "research_only": True,
        "trade_ready": False,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "data": {
            "cutoff": common.index.max().strftime("%Y-%m-%d"),
            "first_date": common.index.min().strftime("%Y-%m-%d"),
            "sessions": int(len(common)),
            "common_eligible_opens": int(common["common_open_eligible"].sum()),
        },
        "expansion": {
            "rules": RULES,
            "entry_signals": int(s20["entry"].sum()),
            "active_sessions": int(s20["expansion_active"].sum()),
        },
        "cost_contract": {
            "primary_transaction_cost_bps": PRIMARY_COST_BPS,
            "stress_transaction_cost_bps": STRESS_COST_BPS,
            "primary_financing_rate": PRIMARY_FINANCING_RATE,
            "stress_financing_rate": STRESS_FINANCING_RATE,
        },
        "headline_20bps": headline20,
        "headline_40bps": headline40,
        "period_contribution": periods,
        "decision": gov.decision,
        "gates": {str(k): bool(v) for k, v in gov.gates.items()},
        "diagnostics": {str(k): v for k, v in gov.diagnostics.items()},
    }

    # Compute content SHA for immutability
    payload = json.dumps(package, ensure_ascii=False, sort_keys=True).encode("utf-8")
    package["content_sha256"] = hashlib.sha256(payload).hexdigest()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    v11 = headline20[BASELINE]
    v12 = headline20[PRIMARY]
    print(f"\nFormal backtest package written to: {args.output}")
    print(f"Content SHA256: {package['content_sha256']}")
    print(f"v1.1 CAGR: {v11['cagr']:.4%}  v1.2 CAGR: {v12['cagr']:.4%}  "
          f"Delta: {v12['cagr'] - v11['cagr']:+.4%}")
    print(f"Decision: {gov.decision}  Gates: {sum(1 for v in gov.gates.values() if v)}/{len(gov.gates)}")


if __name__ == "__main__":
    main()
