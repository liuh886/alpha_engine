#!/usr/bin/env python3
"""Run the frozen BYD V1.3 state-conditioned recovery overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.byd_v1_2_recovery_state import (
    build_v1_0_decision_position,
    load_canonical_snapshot,
)
from src.research.byd_v1_3_recovery_overlay import evaluate_v1_3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    raise TypeError(f"cannot JSON serialize {type(value).__name__}")


def _report(result: dict[str, Any]) -> str:
    full = result["metrics"]["full_history"]
    validation = result["metrics"]["fixed_validation"]
    recent = result["metrics"]["retrospective_2025_plus"]
    lines = [
        "# BYD V1.3 state-conditioned recovery overlay",
        "",
        f"- Decision: `{result['decision']}`",
        "- Research only: `true`",
        "- Trade ready: `false`",
        "- Fresh historical holdout: `false`",
        f"- Completed overlay events: `{result['completed_event_count']}`",
        "",
        "## Full-history comparison",
        "",
        "| Model | CAGR | Total return | Max drawdown | Calmar | Exposure | Round trips/year |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in (
        ("v1_3", "BYD V1.3"),
        ("v1_0", "Canonical V1.0"),
        ("buy_hold", "BYD buy-and-hold"),
    ):
        metric = full[key]
        lines.append(
            f"| {label} | {metric['cagr']:.2%} | "
            f"{metric['total_return']:.2%} | "
            f"{metric['max_drawdown']:.2%} | {metric['calmar']:.4f} | "
            f"{metric['exposure']:.2%} | {metric['round_trips_per_year']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Retrospective windows",
            "",
            "| Window | Model | Total return | Max drawdown | Calmar |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for window_name, block in (
        ("2023–2024", validation),
        ("2025+", recent),
    ):
        for key, label in (("v1_3", "V1.3"), ("v1_0", "V1.0")):
            metric = block[key]
            lines.append(
                f"| {window_name} | {label} | {metric['total_return']:.2%} | "
                f"{metric['max_drawdown']:.2%} | {metric['calmar']:.4f} |"
            )
    lines.extend(["", "## Frozen gates", ""])
    for gate, passed in result["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{gate}`")
    lines.extend(
        [
            "",
            "## Overlay concentration",
            "",
            f"- Incremental round trips/year: `{result['incremental_round_trips_per_year']:.4f}`",
            f"- Largest positive episode share: `{result['largest_positive_episode_share']:.2%}`",
            f"- Largest positive period share: `{result['largest_positive_period_share']:.2%}`",
            "",
            "## Governance",
            "",
            "The canonical V1.0 base model is unchanged. The overlay contract, "
            "event duration, cooldown, state definitions, costs and gates were "
            "frozen before this run. All history through 2026-08-03 is already "
            "observed and cannot promote the model without prospective evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    canonical = load_canonical_snapshot(args.canonical_dir)
    result = evaluate_v1_3(canonical, contract)

    result["event_ledger"].to_csv(
        args.output_dir / "overlay_event_ledger.csv",
        index=False,
        float_format="%.12f",
    )
    base_decision = build_v1_0_decision_position(result["dataset"])
    schedule_daily = pd.DataFrame(
        {
            "base_decision_position": base_decision,
            "overlay_active": result["schedule"].overlay_active,
            "overlay_branch": result["schedule"].overlay_branch,
            "final_decision_position": result["schedule"].final_decision_position,
        },
        index=result["dataset"].index,
    )
    schedule_daily.reset_index(names="date").to_csv(
        args.output_dir / "overlay_schedule.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_3"].daily.reset_index(names="date").to_csv(
        args.output_dir / "v1_3_daily.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_3"].trades.to_csv(
        args.output_dir / "v1_3_trades.csv",
        index=False,
        float_format="%.12f",
    )
    result["v1_0"].daily.reset_index(names="date").to_csv(
        args.output_dir / "canonical_v1_0_daily.csv",
        index=False,
        float_format="%.12f",
    )
    result["prospective_ledger"].to_csv(
        args.output_dir / "prospective_signal_ledger.csv",
        index=False,
        float_format="%.12f",
    )

    summary = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "dataset",
            "schedule",
            "event_ledger",
            "v1_3",
            "v1_0",
            "buy_hold",
            "prospective_ledger",
        }
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_safe,
        ),
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(
        _report(result),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "completed_event_count": result["completed_event_count"],
                "gates": result["gates"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
