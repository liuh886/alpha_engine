"""One-shot validation of the frozen CN130 disclosure-gap overlay against R0."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from scripts.run_cn130_pit_disclosure_reaction import (
    BENCHMARK,
    CALIBRATION,
    REPORTING,
    VALIDATION,
    choose,
    clean,
    disclosures,
    load_score_ledgers,
    reaction_table,
    sha256,
    snapshots,
    write_csv,
    write_json,
)
from src.research.cn130_cross_sectional_ranking import (
    compound,
    forward_returns,
    load_provider_panel,
    max_drawdown,
)
from src.research.cn130_ranking_pipeline import turnover

BASELINE = "E0_r0_sector_4x1"
OVERLAY = "E1_recent_event_rerank"
COMPONENT = "abnormal_gap_1"


def run_portfolio(
    data: pd.DataFrame,
    benchmark: pd.Series,
    architecture: str,
    windows: Sequence[str],
    cost_bps: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    previous: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for window in windows:
        part = data.loc[data["window"] == window]
        for date, day in part.groupby("datetime", sort=True):
            if date not in benchmark.index:
                continue
            selected = choose(day, architecture, COMPONENT)
            exposure = len(selected) / 4.0
            weights = (
                {
                    str(symbol): exposure / len(selected)
                    for symbol in selected["instrument"]
                }
                if len(selected)
                else {}
            )
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000.0
            gross = (
                float(
                    sum(
                        weights[str(row.instrument)]
                        * float(row.execution_forward_return)
                        for row in selected.itertuples(index=False)
                    )
                )
                if len(selected)
                else 0.0
            )
            periods.append(
                {
                    "window": window,
                    "datetime": date,
                    "architecture": architecture,
                    "cost_bps": cost_bps,
                    "net_return": gross - cost,
                    "benchmark_return": float(benchmark.loc[date]),
                    "turnover": period_turnover,
                    "exposure": exposure,
                }
            )
            for row in selected.itertuples(index=False):
                weight = weights[str(row.instrument)]
                holdings.append(
                    {
                        "window": window,
                        "datetime": date,
                        "architecture": architecture,
                        "cost_bps": cost_bps,
                        "instrument": str(row.instrument),
                        "sector": str(row.sector),
                        "score": float(row.score),
                        "abnormal_gap_1": (
                            float(row.abnormal_gap_1)
                            if pd.notna(row.abnormal_gap_1)
                            else np.nan
                        ),
                        "event_age_sessions": (
                            int(row.event_age_sessions)
                            if pd.notna(row.event_age_sessions)
                            else np.nan
                        ),
                        "weight": weight,
                        "net_contribution": (
                            weight * float(row.execution_forward_return)
                            - cost / max(len(selected), 1)
                        ),
                    }
                )
            previous = weights
    period_frame = pd.DataFrame(periods)
    holding_frame = pd.DataFrame(holdings)
    window_results: list[dict[str, Any]] = []
    for window, group in period_frame.groupby("window", sort=False):
        total = compound(group["net_return"])
        benchmark_total = compound(group["benchmark_return"])
        window_results.append(
            {
                "window": window,
                "relative_excess": (1.0 + total) / (1.0 + benchmark_total) - 1.0,
                "total_return": total,
                "benchmark_return": benchmark_total,
            }
        )
    total = compound(period_frame["net_return"])
    benchmark_total = compound(period_frame["benchmark_return"])
    by_name = holding_frame.groupby("instrument")["net_contribution"].sum()
    by_sector = holding_frame.groupby("sector")["net_contribution"].sum()
    summary = {
        "architecture": architecture,
        "cost_bps": cost_bps,
        "relative_excess": (1.0 + total) / (1.0 + benchmark_total) - 1.0,
        "total_return": total,
        "benchmark_return": benchmark_total,
        "max_drawdown": max_drawdown(period_frame["net_return"]),
        "positive_windows": int(
            sum(row["relative_excess"] > 0 for row in window_results)
        ),
        "worst_window_relative_excess": float(
            min(row["relative_excess"] for row in window_results)
        ),
        "turnover": float(period_frame["turnover"].sum()),
        "mean_exposure": float(period_frame["exposure"].mean()),
        "maximum_name_absolute_contribution_share": float(
            by_name.abs().max() / by_name.abs().sum()
        ),
        "maximum_sector_absolute_contribution_share": float(
            by_sector.abs().max() / by_sector.abs().sum()
        ),
        "top_name": str(by_name.abs().idxmax()),
        "top_sector": str(by_sector.abs().idxmax()),
        "window_results": window_results,
    }
    return summary, period_frame, holding_frame


def evaluate_leave_one(
    ledger: pd.DataFrame,
    reactions: pd.DataFrame,
    calendar_index: dict[pd.Timestamp, int],
    benchmark: pd.Series,
    architecture: str,
    windows: Sequence[str],
    cost_bps: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    base_data = snapshots(ledger, reactions, calendar_index, windows)
    result, _, holdings = run_portfolio(
        base_data, benchmark, architecture, windows, cost_bps
    )
    without_name = snapshots(
        ledger,
        reactions,
        calendar_index,
        windows,
        excluded_name=result["top_name"],
    )
    without_sector = snapshots(
        ledger,
        reactions,
        calendar_index,
        windows,
        excluded_sector=result["top_sector"],
    )
    name_result, _, _ = run_portfolio(
        without_name, benchmark, architecture, windows, cost_bps
    )
    sector_result, _, _ = run_portfolio(
        without_sector, benchmark, architecture, windows, cost_bps
    )
    result["leave_one_name_relative_excess"] = name_result["relative_excess"]
    result["leave_one_sector_relative_excess"] = sector_result["relative_excess"]
    return result, holdings


def compact(summary: dict[str, Any]) -> dict[str, Any]:
    output = {key: value for key, value in summary.items() if key != "window_results"}
    output["window_results"] = json.dumps(
        clean(summary["window_results"]), ensure_ascii=False, sort_keys=True
    )
    return output


def window_increment(
    baseline: dict[str, Any], overlay: dict[str, Any]
) -> pd.DataFrame:
    base = {row["window"]: row for row in baseline["window_results"]}
    rows: list[dict[str, Any]] = []
    for row in overlay["window_results"]:
        window = row["window"]
        rows.append(
            {
                "window": window,
                "baseline_relative_excess": base[window]["relative_excess"],
                "overlay_relative_excess": row["relative_excess"],
                "incremental_relative_excess": (
                    row["relative_excess"] - base[window]["relative_excess"]
                ),
            }
        )
    return pd.DataFrame(rows)


def calibration_gate(
    baseline20: dict[str, Any],
    overlay20: dict[str, Any],
    baseline40: dict[str, Any],
    overlay40: dict[str, Any],
    increments: pd.DataFrame,
) -> bool:
    return bool(
        (increments["incremental_relative_excess"] > 0).all()
        and overlay20["relative_excess"] > baseline20["relative_excess"]
        and overlay40["relative_excess"] > baseline40["relative_excess"]
        and overlay20["max_drawdown"] >= baseline20["max_drawdown"]
        and overlay20["leave_one_name_relative_excess"]
        > baseline20["leave_one_name_relative_excess"]
        and overlay20["leave_one_sector_relative_excess"]
        > baseline20["leave_one_sector_relative_excess"]
        and overlay20["turnover"] - baseline20["turnover"] <= 2.0
        and overlay20["maximum_sector_absolute_contribution_share"] <= 0.60
    )


def validation_gate(
    baseline20: dict[str, Any],
    overlay20: dict[str, Any],
    baseline40: dict[str, Any],
    overlay40: dict[str, Any],
    increments: pd.DataFrame,
) -> bool:
    return bool(
        overlay20["relative_excess"] > baseline20["relative_excess"]
        and overlay40["relative_excess"] > baseline40["relative_excess"]
        and overlay20["positive_windows"] == 4
        and int((increments["incremental_relative_excess"] > 0).sum()) >= 3
        and overlay20["worst_window_relative_excess"]
        >= baseline20["worst_window_relative_excess"]
        and overlay20["max_drawdown"] >= baseline20["max_drawdown"]
        and overlay20["leave_one_name_relative_excess"] > 0
        and overlay20["leave_one_sector_relative_excess"] > 0
        and overlay20["leave_one_name_relative_excess"]
        > baseline20["leave_one_name_relative_excess"]
        and overlay20["leave_one_sector_relative_excess"]
        > baseline20["leave_one_sector_relative_excess"]
        and overlay20["maximum_sector_absolute_contribution_share"] <= 0.55
        and overlay20["turnover"] - baseline20["turnover"] <= 3.0
    )


def evaluate_pair(
    ledger: pd.DataFrame,
    reactions: pd.DataFrame,
    calendar_index: dict[pd.Timestamp, int],
    benchmark: pd.Series,
    windows: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, dict[int, dict[str, Any]]]]:
    summaries: dict[str, dict[int, dict[str, Any]]] = {BASELINE: {}, OVERLAY: {}}
    holdings: list[pd.DataFrame] = []
    for architecture in (BASELINE, OVERLAY):
        summary20, holding20 = evaluate_leave_one(
            ledger,
            reactions,
            calendar_index,
            benchmark,
            architecture,
            windows,
            20,
        )
        summaries[architecture][20] = summary20
        holdings.append(holding20)
        data = snapshots(ledger, reactions, calendar_index, windows)
        for cost in (10, 40):
            result, _, _ = run_portfolio(
                data, benchmark, architecture, windows, cost
            )
            summaries[architecture][cost] = result
    rows: list[dict[str, Any]] = []
    for architecture in (BASELINE, OVERLAY):
        row = compact(summaries[architecture][20])
        row["relative_excess_10bps"] = summaries[architecture][10]["relative_excess"]
        row["relative_excess_40bps"] = summaries[architecture][40]["relative_excess"]
        rows.append(row)
    summary_frame = pd.DataFrame(rows)
    increments = window_increment(
        summaries[BASELINE][20], summaries[OVERLAY][20]
    )
    holding_frame = pd.concat(holdings, ignore_index=True)
    return summary_frame, increments, holding_frame, summaries


def run(
    provider_dir: Path,
    calibration_dir: Path,
    frozen_dir: Path,
    events_path: Path,
    output_dir: Path,
) -> None:
    calibration = load_score_ledgers(calibration_dir, CALIBRATION)
    validation = load_score_ledgers(frozen_dir, VALIDATION)
    reporting = load_score_ledgers(frozen_dir, REPORTING)
    symbols = sorted(
        set(calibration["instrument"])
        | set(validation["instrument"])
        | set(reporting["instrument"])
    )
    panel = load_provider_panel(
        provider_dir, [*symbols, BENCHMARK], fields=("open", "close", "amount")
    )
    reactions = reaction_table(disclosures(events_path), panel, symbols)
    calendar_index = {date: index for index, date in enumerate(panel.calendar)}
    benchmark = forward_returns(
        panel.fields["close"][[BENCHMARK]], horizon=10, delay=1
    )[BENCHMARK]

    calibration_summary, calibration_increments, calibration_holdings, cal = evaluate_pair(
        calibration, reactions, calendar_index, benchmark, CALIBRATION
    )
    calibration_pass = calibration_gate(
        cal[BASELINE][20],
        cal[OVERLAY][20],
        cal[BASELINE][40],
        cal[OVERLAY][40],
        calibration_increments,
    )

    validation_summary = pd.DataFrame()
    validation_increments = pd.DataFrame()
    validation_holdings = pd.DataFrame()
    reporting_summary = pd.DataFrame()
    validation_pass = False
    if calibration_pass:
        validation_summary, validation_increments, validation_holdings, val = evaluate_pair(
            validation, reactions, calendar_index, benchmark, VALIDATION
        )
        validation_pass = validation_gate(
            val[BASELINE][20],
            val[OVERLAY][20],
            val[BASELINE][40],
            val[OVERLAY][40],
            validation_increments,
        )
        reporting_summary, _, _, _ = evaluate_pair(
            reporting, reactions, calendar_index, benchmark, REPORTING
        )

    if not calibration_pass:
        decision = "disclosure_gap_overlay_calibration_not_reproduced"
    elif validation_pass:
        decision = "pit_disclosure_gap_overlay_research_candidate"
    else:
        decision = "disclosure_gap_overlay_validation_not_supported"

    output_dir.mkdir(parents=True, exist_ok=True)
    decision_payload = {
        "decision": decision,
        "component": COMPONENT,
        "architecture": OVERLAY,
        "calibration_gate_pass": calibration_pass,
        "validation_gate_pass": validation_pass,
        "creates_cn_x1_1_candidate": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output_dir / "decision.json", decision_payload)
    write_json(
        output_dir / "execution_identity.json",
        {
            "price_provider_manifest_sha256": sha256(
                provider_dir / "provider_manifest.json"
            ),
            "fundamental_events_sha256": sha256(events_path),
            "component": COMPONENT,
            "architecture": OVERLAY,
            "calibration_windows": list(CALIBRATION),
            "validation_windows": list(VALIDATION),
            "reporting_windows": list(REPORTING),
            "research_only": True,
            "trade_ready": False,
        },
    )
    write_csv(output_dir / "calibration_summary.csv", calibration_summary)
    write_csv(output_dir / "calibration_window_increment.csv", calibration_increments)
    write_csv(output_dir / "calibration_holdings.csv", calibration_holdings)
    write_csv(output_dir / "validation_summary.csv", validation_summary)
    write_csv(output_dir / "validation_window_increment.csv", validation_increments)
    write_csv(output_dir / "validation_holdings.csv", validation_holdings)
    write_csv(output_dir / "reporting_summary.csv", reporting_summary)

    lines = [
        "# CN130 disclosure-gap R0 overlay one-shot validation",
        "",
        f"- Decision: `{decision}`",
        f"- Calibration gate: {calibration_pass}",
        f"- Validation gate: {validation_pass}",
        "- Frozen component: `abnormal_gap_1`",
        "- Frozen architecture: `E1_recent_event_rerank`",
        "- `research_only=true`; no automatic CN x1.1 promotion.",
        "",
        "Validation was opened only after reproducing the inherited incremental calibration gate.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = [path for path in output_dir.iterdir() if path.is_file()]
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "experiment_id": "cn130_pit_disclosure_overlay_validation_v1",
            "decision": decision_payload,
            "files": [
                {
                    "path": path.name,
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(files)
            ],
        },
    )
    print(json.dumps(clean(decision_payload), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--calibration-ledger-dir", type=Path, required=True)
    parser.add_argument("--frozen-ledger-dir", type=Path, required=True)
    parser.add_argument("--events-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.provider_dir.resolve(),
        args.calibration_ledger_dir.resolve(),
        args.frozen_ledger_dir.resolve(),
        args.events_path.resolve(),
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
