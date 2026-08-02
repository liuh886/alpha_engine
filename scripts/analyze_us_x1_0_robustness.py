#!/usr/bin/env python3
"""Analyze a complete US x1.0 run for cost, window and selection robustness."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONTRACT = Path(
    "configs/research_experiments/us_x1_0_robustness_v1.yaml"
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must contain a mapping: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def _window_label(path: Path) -> str:
    stem = path.stem
    label = stem.rsplit("_", 1)[-1]
    if len(label) != 6 or label[4] != "H":
        raise ValueError(f"Cannot derive half-year label from {path.name}")
    return label


def _candidate_for_window(
    payload: dict[str, Any],
    *,
    candidate_name: str,
    orientation: str,
) -> dict[str, Any]:
    report = payload.get("comparison_report")
    if not isinstance(report, dict):
        raise ValueError("Window artifact has no comparison_report")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Window comparison_report has no candidate list")
    matches = [
        dict(item)
        for item in candidates
        if isinstance(item, dict)
        and item.get("candidate_name") == candidate_name
        and item.get("orientation") == orientation
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one {candidate_name}/{orientation} candidate, "
            f"found {len(matches)}"
        )
    return matches[0]


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def _relative(strategy_return: float, benchmark_return: float) -> float:
    return (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0


def _cost_stress(
    rows: list[dict[str, Any]],
    cost_bps_values: list[int],
    base_cost_bps: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    benchmark = _compound([float(row["benchmark_return"]) for row in rows])
    for cost_bps in cost_bps_values:
        multiplier = cost_bps / base_cost_bps
        stressed_window_returns = [
            float(row["total_return"])
            - (multiplier - 1.0) * float(row["costs"])
            for row in rows
        ]
        strategy = _compound(stressed_window_returns)
        output.append(
            {
                "cost_bps": cost_bps,
                "compounded_strategy_return": strategy,
                "compounded_benchmark_return": benchmark,
                "compounded_relative_excess": _relative(strategy, benchmark),
                "window_returns": stressed_window_returns,
            }
        )
    return output


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# US x1.0 robustness experiment",
        "",
        f"**Decision:** `{report['decision']}`  ",
        "**Research only:** `trade_ready=false`",
        "",
        "## Identity",
        "",
        f"- Parent model: `{report['parent_model_id']}`",
        f"- Provider identity: `{report['provider_identity_sha256']}`",
        f"- Candidate: `{report['candidate_name']}` / `{report['orientation']}`",
        "- Effective XGBoost learning rate: `0.05`",
        "- Development windows: 2024H1, 2024H2, 2025H1, 2025H2",
        "- 2026H1 is reporting-only and was not used in the decision.",
        "",
        "## Development windows",
        "",
        "| Window | Return | QQQ | Excess | Costs | Drawdown |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["development_windows"]:
        lines.append(
            f"| {row['window']} | {row['total_return']:.2%} | "
            f"{row['benchmark_return']:.2%} | {row['excess_return']:.2%} | "
            f"{row['costs']:.2%} | {row['max_drawdown']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Cost stress",
            "",
            "| Cost | Compounded return | Relative excess |",
            "|---:|---:|---:|",
        ]
    )
    for row in report["cost_stress"]:
        lines.append(
            f"| {row['cost_bps']} bps | "
            f"{row['compounded_strategy_return']:.2%} | "
            f"{row['compounded_relative_excess']:.2%} |"
        )
    lines.extend(
        [
            "",
            "The stress scales the recorded cumulative 20 bps costs linearly. "
            "It is not an order-book or market-impact simulation.",
            "",
            "## Concentration and tail risk",
            "",
            f"- Strongest positive-window share: "
            f"{report['strongest_positive_window_share']:.2%}.",
            f"- Worst development drawdown: "
            f"{report['worst_development_drawdown']:.2%}.",
            f"- Names present in all four final Top-15 lists: "
            f"{report['all_window_recurring_name_count']}.",
            f"- Recurring names: "
            f"{', '.join(report['all_window_recurring_names']) or 'none'}.",
            "",
            "Final Top-15 recurrence is a selection-concentration diagnostic; "
            "it is not a complete security-contribution ledger.",
            "",
            "## Leave-one-window-out relative excess",
            "",
        ]
    )
    for label, value in report["leave_one_window_out_relative_excess"].items():
        lines.append(f"- Excluding {label}: {value:.2%}")
    lines.extend(["", "## Blocking reasons", ""])
    for reason in report["blocking_reasons"]:
        lines.append(f"- {reason}")
    if not report["blocking_reasons"]:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            report["interpretation"],
            "",
            "This experiment cannot mutate US x1.0 or create US x1.1 without "
            "a reviewed design and one new untouched challenge window.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_report(
    run_dir: Path,
    contract_path: Path,
    model_path: Path,
) -> dict[str, Any]:
    contract = _load_yaml(contract_path)
    model = _load_yaml(model_path)
    if contract["parent_model_id"] != model["model_id"]:
        raise ValueError("Experiment parent model does not match model config")
    if model["display_name"] != "US x1.0":
        raise ValueError("Robustness experiment requires US x1.0")
    if float(model["model"]["learning_rate"]) != 0.05:
        raise ValueError("US x1.0 effective XGBoost learning rate must be 0.05")

    run_status = _load_json(run_dir / "run_status.json")
    if run_status.get("status") != "passed":
        raise ValueError(f"Full backtest did not pass: {run_status.get('status')}")
    runtime = run_status.get("runtime_metadata")
    if not isinstance(runtime, dict):
        raise ValueError("run_status has no runtime_metadata")
    provider_identity = str(runtime.get("provider_identity_sha256", ""))
    required_provider = str(contract["provider"]["required_identity_sha256"])
    if provider_identity != required_provider:
        raise ValueError(
            f"Provider identity mismatch: {provider_identity} != {required_provider}"
        )

    candidate_name = str(contract["candidate"]["candidate_name"])
    orientation = str(contract["candidate"]["orientation"])
    artifacts: dict[str, dict[str, Any]] = {}
    for path in sorted((run_dir / "windows").glob("*.json")):
        label = _window_label(path)
        if label in artifacts:
            raise ValueError(f"Duplicate window artifact: {label}")
        artifacts[label] = _candidate_for_window(
            _load_json(path),
            candidate_name=candidate_name,
            orientation=orientation,
        )

    development_labels = [str(item) for item in contract["windows"]["development"]]
    reporting_labels = [
        str(item)
        for item in contract["windows"]["reporting_only_consumed_holdout"]
    ]
    required_labels = set(development_labels + reporting_labels)
    if set(artifacts) != required_labels:
        raise ValueError(
            f"Window set mismatch: {sorted(artifacts)} != {sorted(required_labels)}"
        )

    development_rows: list[dict[str, Any]] = []
    for label in development_labels:
        candidate = artifacts[label]
        top_names = candidate.get("top_selected_stocks")
        if not isinstance(top_names, list) or len(top_names) != 15:
            raise ValueError(f"{label}: expected exactly 15 final selected names")
        development_rows.append(
            {
                "window": label,
                "total_return": float(candidate["total_return"]),
                "benchmark_return": float(candidate["benchmark_return"]),
                "excess_return": float(candidate["excess_return"]),
                "costs": float(candidate["costs"]),
                "max_drawdown": float(candidate["max_drawdown"]),
                "icir": float(candidate["icir"]),
                "rank_ic": float(candidate["rank_ic"]),
                "turnover": float(candidate["turnover"]),
                "top_selected_stocks": [str(item) for item in top_names],
            }
        )

    cost_bps_values = [int(item) for item in contract["stress_tests"]["cost_bps"]]
    base_cost_bps = int(model["strategy"]["cost_bps"])
    cost_stress = _cost_stress(development_rows, cost_bps_values, base_cost_bps)

    positive_excess = [
        row["excess_return"]
        for row in development_rows
        if row["excess_return"] > 0
    ]
    strongest_share = max(positive_excess) / sum(positive_excess)
    worst_drawdown = min(row["max_drawdown"] for row in development_rows)

    leave_one_out: dict[str, float] = {}
    for excluded in development_labels:
        retained = [row for row in development_rows if row["window"] != excluded]
        strategy = _compound([row["total_return"] for row in retained])
        benchmark = _compound([row["benchmark_return"] for row in retained])
        leave_one_out[excluded] = _relative(strategy, benchmark)

    recurrence = Counter(
        name
        for row in development_rows
        for name in row["top_selected_stocks"]
    )
    recurring_names = sorted(
        name
        for name, count in recurrence.items()
        if count == len(development_labels)
    )

    blocks = contract["block_conditions"]
    blocking_reasons: list[str] = []
    if worst_drawdown < float(blocks["worst_development_drawdown_below"]):
        blocking_reasons.append(
            f"Worst development drawdown {worst_drawdown:.2%} is below "
            f"{float(blocks['worst_development_drawdown_below']):.2%}."
        )
    recurrence_limit = int(
        blocks["minimum_names_present_in_all_development_final_top15"]
    )
    if len(recurring_names) >= recurrence_limit:
        blocking_reasons.append(
            f"{len(recurring_names)} names appear in every development "
            f"final Top-15 list; block threshold is {recurrence_limit}."
        )
    share_limit = float(blocks["maximum_strongest_positive_window_share"])
    if strongest_share > share_limit:
        blocking_reasons.append(
            f"Strongest positive window supplies {strongest_share:.2%} of "
            f"positive simple excess; limit is {share_limit:.2%}."
        )

    sixty_bps = next(
        row for row in cost_stress if int(row["cost_bps"]) == 60
    )
    economics_failed = sixty_bps["compounded_relative_excess"] <= 0 or any(
        value <= 0 for value in leave_one_out.values()
    )
    if economics_failed:
        decision = "economics_not_cost_robust"
        interpretation = (
            "US x1.0 does not retain positive benchmark-relative economics "
            "under the preregistered robustness stresses."
        )
    elif blocking_reasons:
        decision = "tail_risk_or_concentration_blocks_x1_1"
        interpretation = (
            "US x1.0 remains strongly positive under 60 bps and every "
            "leave-one-window-out test, but tail risk and recurring selections "
            "block immediate x1.1 design. The next experiment should target "
            "position/sector concentration and drawdown control, not a broad grid."
        )
    else:
        decision = "robustness_supported_for_x1_1_design"
        interpretation = (
            "US x1.0 passes the preregistered economic, concentration and "
            "tail-risk gates and may proceed to a bounded x1.1 design."
        )

    reporting_only = {
        label: {
            key: artifacts[label].get(key)
            for key in (
                "total_return",
                "benchmark_return",
                "excess_return",
                "icir",
                "rank_ic",
                "max_drawdown",
                "turnover",
            )
        }
        for label in reporting_labels
    }
    return {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "parent_model_id": contract["parent_model_id"],
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "candidate_name": candidate_name,
        "orientation": orientation,
        "provider_identity_sha256": provider_identity,
        "development_windows": development_rows,
        "reporting_only_consumed_holdout": reporting_only,
        "cost_stress_method": contract["stress_tests"]["method"],
        "cost_stress": cost_stress,
        "strongest_positive_window_share": strongest_share,
        "worst_development_drawdown": worst_drawdown,
        "leave_one_window_out_relative_excess": leave_one_out,
        "final_top15_name_frequency": dict(sorted(recurrence.items())),
        "all_window_recurring_names": recurring_names,
        "all_window_recurring_name_count": len(recurring_names),
        "blocking_reasons": blocking_reasons,
        "interpretation": interpretation,
        "automatic_model_update": False,
        "new_untouched_challenge_required": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--model-config",
        type=Path,
        default=Path("configs/models/us_x1_0.yaml"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = build_report(args.run_dir, args.contract, args.model_config)
        exit_code = 0
    except Exception as exc:
        report = {
            "schema_version": "1.0",
            "experiment_id": "us_x1_0_robustness_v1",
            "research_only": True,
            "trade_ready": False,
            "decision": "data_blocked",
            "error": f"{type(exc).__name__}: {exc}",
        }
        exit_code = 2

    (args.output_dir / "robustness_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    if exit_code == 0:
        (args.output_dir / "robustness_report.md").write_text(
            _render_markdown(report),
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
