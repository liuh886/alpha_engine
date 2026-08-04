#!/usr/bin/env python3
"""Run governed BYD V1.2 recovery/reversal state-model research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    evaluate_v1_2,
    load_canonical_snapshot,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (pd.DataFrame, pd.Series)):
        raise TypeError("dataframes must be written separately")
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    raise TypeError(f"cannot JSON serialize {type(value).__name__}")


def _report(result: dict[str, Any]) -> str:
    full = result["metrics"]["full_history"]
    validation = result["metrics"]["fixed_validation"]
    rows = [
        "# BYD V1.2 recovery/reversal state model",
        "",
        f"- Decision: `{result['decision']}`",
        "- Research only: `true`",
        "- Trade ready: `false`",
        "- Fresh historical holdout: `false`",
        f"- Canonical adjusted SHA-256: `{CANONICAL_ADJUSTED_SHA256}`",
        "",
        "## Frozen model",
        "",
        "A single pre-registered state machine uses long-horizon reversal, "
        "recovery confirmation, momentum transition, and open-return "
        "autocorrelation. It switches only between 75% and 100% BYD and "
        "executes at the next independently confirmed eligible open.",
        "",
        "## Full-history comparison",
        "",
        "| Model | CAGR | Total return | Max drawdown | Calmar | Exposure | "
        "Round trips/year |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in (
        ("v1_2", "BYD V1.2"),
        ("v1_0", "Canonical V1.0"),
        ("buy_hold", "BYD buy-and-hold"),
    ):
        metric = full[key]
        rows.append(
            f"| {label} | {metric['cagr']:.2%} | "
            f"{metric['total_return']:.2%} | "
            f"{metric['max_drawdown']:.2%} | {metric['calmar']:.4f} | "
            f"{metric['exposure']:.2%} | "
            f"{metric['round_trips_per_year']:.3f} |"
        )
    rows.extend(
        [
            "",
            "## Fixed 2023–2024 retrospective validation",
            "",
            "| Model | CAGR | Total return | Max drawdown | Calmar |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("v1_2", "BYD V1.2"),
        ("v1_0", "Canonical V1.0"),
        ("buy_hold", "BYD buy-and-hold"),
    ):
        metric = validation[key]
        rows.append(
            f"| {label} | {metric['cagr']:.2%} | "
            f"{metric['total_return']:.2%} | "
            f"{metric['max_drawdown']:.2%} | {metric['calmar']:.4f} |"
        )
    rows.extend(["", "## Frozen gates", ""])
    for gate, passed in result["gates"].items():
        rows.append(f"- {'PASS' if passed else 'FAIL'} — `{gate}`")
    rows.extend(
        [
            "",
            "## Governance",
            "",
            "The entire history through 2026-08-03 was already observed during "
            "factor discovery. A historically supported result is not a "
            "promotion decision. The prospective ledger begins on 2026-08-04 "
            "and must accumulate before any trade-ready claim.",
        ]
    )
    return "\n".join(rows) + "\n"


def main() -> None:
    args = _parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    canonical = load_canonical_snapshot(args.canonical_dir)
    result = evaluate_v1_2(canonical, contract)

    result["clusters"].to_csv(output / "factor_clusters.csv", index=False)
    result["factor_correlation"].to_csv(
        output / "factor_correlation.csv",
        float_format="%.12f",
    )
    result["conditional_ic"].to_csv(
        output / "conditional_ic.csv",
        index=False,
        float_format="%.12f",
    )
    result["defense_episodes"].to_csv(
        output / "defense_episodes.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_2"].daily.reset_index(names="date").to_csv(
        output / "v1_2_daily.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_2"].trades.to_csv(
        output / "v1_2_trades.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_0"].daily.reset_index(names="date").to_csv(
        output / "canonical_v1_0_daily.csv",
        index=False,
        float_format="%.12f",
    )
    result["prospective_ledger"].to_csv(
        output / "prospective_signal_ledger.csv",
        index=False,
        float_format="%.12f",
    )

    summary = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "clusters",
            "factor_correlation",
            "conditional_ic",
            "defense_episodes",
            "v1_2",
            "v1_0",
            "buy_hold",
            "prospective_ledger",
        }
    }
    (output / "summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_safe,
        ),
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        _report(result),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "gates": result["gates"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
