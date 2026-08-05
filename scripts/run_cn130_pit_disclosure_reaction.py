"""Calibrate PIT periodic-report reaction conditioning for the CN130 R0 tail."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from scripts.run_cn130_pit_fundamental_model import (
    clean,
    load_score_ledgers,
    sector_selection,
    sha256,
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

CALIBRATION = ("2022H2", "2023H1", "2023H2")
VALIDATION = ("2024H1", "2024H2", "2025H1", "2025H2")
REPORTING = ("2026H1", "2026H2_PARTIAL")
COMPONENTS = (
    "abnormal_return_1",
    "abnormal_return_3",
    "abnormal_gap_1",
    "amount_ratio_1",
    "amount_ratio_3",
)
ARCHITECTURES = (
    "E0_r0_sector_4x1",
    "E1_recent_event_rerank",
    "E2_negative_reaction_switch",
    "E3_negative_reaction_cash",
)
BENCHMARK = "000300"


def disclosures(path: Path) -> pd.DataFrame:
    frame = pd.DataFrame(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    frame = frame.loc[frame["filing_type"] == "PERIODIC_REPORT"].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    frame["available_date"] = (
        available.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
    )
    return (
        frame.dropna(subset=["available_date"])
        .sort_values(
            ["symbol", "available_date", "fiscal_period", "event_id"],
            kind="mergesort",
        )
        .drop_duplicates(["symbol", "available_date", "fiscal_period"], keep="last")
        .reset_index(drop=True)
    )


def reaction_table(
    events: pd.DataFrame,
    panel: Any,
    symbols: Sequence[str],
) -> pd.DataFrame:
    close = panel.fields["close"]
    open_price = panel.fields["open"]
    amount = panel.fields["amount"]
    calendar = panel.calendar
    allowed = set(symbols)
    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        symbol = str(event.symbol).zfill(6)
        if symbol not in allowed:
            continue
        start = int(calendar.searchsorted(pd.Timestamp(event.available_date), side="right"))
        if start < 20 or start + 2 >= len(calendar):
            continue
        previous = start - 1
        prior_amount = float(amount[symbol].iloc[start - 20 : start].mean())
        values = {
            "abnormal_return_1": (
                close[symbol].iloc[start] / close[symbol].iloc[previous] - 1.0
            )
            - (
                close[BENCHMARK].iloc[start] / close[BENCHMARK].iloc[previous] - 1.0
            ),
            "abnormal_return_3": (
                close[symbol].iloc[start + 2] / close[symbol].iloc[previous] - 1.0
            )
            - (
                close[BENCHMARK].iloc[start + 2]
                / close[BENCHMARK].iloc[previous]
                - 1.0
            ),
            "abnormal_gap_1": (
                open_price[symbol].iloc[start] / close[symbol].iloc[previous] - 1.0
            )
            - (
                open_price[BENCHMARK].iloc[start]
                / close[BENCHMARK].iloc[previous]
                - 1.0
            ),
            "amount_ratio_1": amount[symbol].iloc[start] / prior_amount - 1.0,
            "amount_ratio_3": (
                amount[symbol].iloc[start : start + 3].mean() / prior_amount - 1.0
            ),
        }
        if not all(np.isfinite(value) for value in values.values()):
            continue
        rows.append(
            {
                "symbol": symbol,
                "available_date": event.available_date,
                "reaction_start": calendar[start],
                "reaction_complete": calendar[start + 2],
                "start_index": start,
                "complete_index": start + 2,
                "fiscal_period": str(event.fiscal_period),
                **values,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["symbol", "reaction_complete", "available_date"], kind="mergesort"
    )


def attach_reaction(
    day: pd.DataFrame,
    event_groups: dict[str, pd.DataFrame],
    calendar_index: dict[pd.Timestamp, int],
    date: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    ranked, sectors = sector_selection(day)
    ranked["r0_sector_rank"] = ranked.groupby("sector")["score"].rank(
        method="average", pct=True
    )
    ranked["r0_top3"] = (
        ranked.groupby("sector")["score"].rank(method="first", ascending=False) <= 3
    )
    date_index = calendar_index[pd.Timestamp(date)]
    rows: list[dict[str, Any]] = []
    for row in ranked.itertuples(index=False):
        payload = row._asdict()
        eligible = event_groups.get(str(row.instrument), pd.DataFrame())
        if not eligible.empty:
            eligible = eligible.loc[
                (eligible["complete_index"] <= date_index)
                & ((date_index - eligible["start_index"]) <= 20)
            ]
        event = eligible.iloc[-1] if not eligible.empty else None
        for component in COMPONENTS:
            payload[component] = float(event[component]) if event is not None else np.nan
        payload["event_age_sessions"] = (
            int(date_index - event["start_index"]) if event is not None else np.nan
        )
        payload["event_fiscal_period"] = (
            str(event["fiscal_period"]) if event is not None else None
        )
        rows.append(payload)
    return pd.DataFrame(rows), sectors


def snapshots(
    ledger: pd.DataFrame,
    reactions: pd.DataFrame,
    calendar_index: dict[pd.Timestamp, int],
    windows: Sequence[str],
    *,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> pd.DataFrame:
    event_groups = {
        symbol: group for symbol, group in reactions.groupby("symbol", sort=False)
    }
    frames: list[pd.DataFrame] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window]
        for date in sorted(part["datetime"].unique())[::10]:
            day = part.loc[part["datetime"] == date].copy()
            if excluded_name:
                day = day.loc[day["instrument"] != excluded_name]
            if excluded_sector:
                day = day.loc[day["sector"] != excluded_sector]
            snap, selected = attach_reaction(
                day, event_groups, calendar_index, pd.Timestamp(date)
            )
            snap = snap.loc[snap["sector"].isin(selected)].copy()
            snap["window"] = window
            snap["datetime"] = pd.Timestamp(date)
            frames.append(snap)
    return pd.concat(frames, ignore_index=True)


def corr(left: pd.Series, right: pd.Series) -> float:
    frame = pd.concat([left, right], axis=1).dropna()
    if len(frame) < 6 or frame.iloc[:, 0].nunique() < 2:
        return float("nan")
    return float(frame.iloc[:, 0].corr(frame.iloc[:, 1], method="spearman"))


def partial_corr(component: pd.Series, target: pd.Series, control: pd.Series) -> float:
    frame = pd.concat([component, target, control], axis=1).dropna().rank(pct=True)
    if len(frame) < 8:
        return float("nan")
    x = np.column_stack([np.ones(len(frame)), frame.iloc[:, 2].to_numpy(float)])
    left = frame.iloc[:, 0].to_numpy(dtype=float, copy=True)
    right = frame.iloc[:, 1].to_numpy(dtype=float, copy=True)
    left -= x @ np.linalg.lstsq(x, left, rcond=None)[0]
    right -= x @ np.linalg.lstsq(x, right, rcond=None)[0]
    return (
        float(np.corrcoef(left, right)[0, 1])
        if np.std(left) > 1e-12 and np.std(right) > 1e-12
        else float("nan")
    )


def diagnose_components(
    calibration: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str | None]:
    top3 = calibration.loc[calibration["r0_top3"]]
    coverage = float(top3["event_age_sessions"].notna().mean())
    daily_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    for (window, date), day in top3.groupby(["window", "datetime"]):
        for component in COMPONENTS:
            frame = day.dropna(subset=[component, "execution_forward_return"])
            if len(frame) < 6:
                continue
            low = frame[component].quantile(1 / 3)
            high = frame[component].quantile(2 / 3)
            daily_rows.append(
                {
                    "window": window,
                    "datetime": date,
                    "component": component,
                    "n_names": len(frame),
                    "rank_ic": corr(frame[component], frame["execution_forward_return"]),
                    "incremental_rank_ic": partial_corr(
                        frame[component],
                        frame["execution_forward_return"],
                        frame["r0_sector_rank"],
                    ),
                    "spread": float(
                        frame.loc[
                            frame[component] >= high, "execution_forward_return"
                        ].mean()
                        - frame.loc[
                            frame[component] <= low, "execution_forward_return"
                        ].mean()
                    ),
                }
            )
            for sector, group in frame.groupby("sector"):
                if len(group) >= 3 and group[component].nunique() >= 2:
                    median = group[component].median()
                    sector_rows.append(
                        {
                            "window": window,
                            "datetime": date,
                            "component": component,
                            "sector": sector,
                            "spread": float(
                                group.loc[
                                    group[component] >= median,
                                    "execution_forward_return",
                                ].mean()
                                - group.loc[
                                    group[component] < median,
                                    "execution_forward_return",
                                ].mean()
                            ),
                        }
                    )
    daily = pd.DataFrame(daily_rows)
    sector = pd.DataFrame(sector_rows)
    window_summary = (
        daily.groupby(["component", "window"], as_index=False)
        .agg(
            mean_rank_ic=("rank_ic", "mean"),
            mean_incremental_rank_ic=("incremental_rank_ic", "mean"),
            mean_spread=("spread", "mean"),
            n_dates=("datetime", "nunique"),
            mean_names=("n_names", "mean"),
        )
        .sort_values(["component", "window"], kind="mergesort")
    )
    summaries: list[dict[str, Any]] = []
    for component in COMPONENTS:
        windows = window_summary.loc[window_summary["component"] == component]
        by_sector = (
            sector.loc[sector["component"] == component]
            .groupby("sector")["spread"]
            .sum()
            .abs()
        )
        sector_share = (
            float(by_sector.max() / by_sector.sum())
            if len(by_sector) and by_sector.sum() > 0
            else 1.0
        )
        row = {
            "component": component,
            "recent_event_coverage": coverage,
            "mean_rank_ic": float(windows["mean_rank_ic"].mean()),
            "positive_half_years": int((windows["mean_rank_ic"] > 0).sum()),
            "worst_half_year_rank_ic": float(windows["mean_rank_ic"].min()),
            "mean_incremental_rank_ic": float(
                windows["mean_incremental_rank_ic"].mean()
            ),
            "mean_spread": float(windows["mean_spread"].mean()),
            "maximum_sector_absolute_spread_share": sector_share,
        }
        row["support_gate_pass"] = bool(
            coverage >= 0.15
            and row["mean_rank_ic"] >= 0.05
            and row["positive_half_years"] == 3
            and row["worst_half_year_rank_ic"] > 0
            and row["mean_incremental_rank_ic"] >= 0.02
            and row["mean_spread"] > 0
            and sector_share <= 0.60
        )
        summaries.append(row)
    summary = pd.DataFrame(summaries)
    supported = summary.loc[summary["support_gate_pass"]].sort_values(
        ["mean_incremental_rank_ic", "mean_rank_ic", "component"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    selected = str(supported.iloc[0]["component"]) if not supported.empty else None
    summary["selected"] = summary["component"] == selected
    return summary, window_summary, sector, selected


def choose(day: pd.DataFrame, architecture: str, component: str) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for _, group in day.groupby("sector"):
        ranked = group.sort_values(
            ["score", "instrument"], ascending=[False, True], kind="mergesort"
        ).head(3)
        baseline = ranked.head(1)
        recent = ranked.dropna(subset=[component])
        if architecture == ARCHITECTURES[0]:
            selected = baseline
        elif architecture == ARCHITECTURES[1]:
            selected = (
                recent.sort_values(
                    [component, "score", "instrument"],
                    ascending=[False, False, True],
                    kind="mergesort",
                ).head(1)
                if len(recent) >= 2
                else baseline
            )
        elif architecture == ARCHITECTURES[2]:
            base = baseline.iloc[0]
            qualifying = recent.loc[recent[component] >= 0].sort_values(
                ["score", "instrument"], ascending=[False, True], kind="mergesort"
            )
            selected = (
                qualifying.head(1)
                if pd.notna(base[component])
                and float(base[component]) < 0
                and not qualifying.empty
                else baseline
            )
        elif architecture == ARCHITECTURES[3]:
            base = baseline.iloc[0]
            selected = (
                baseline.iloc[0:0]
                if pd.notna(base[component]) and float(base[component]) < 0
                else baseline
            )
        else:
            raise ValueError(architecture)
        pieces.append(selected)
    return pd.concat(pieces, ignore_index=True)


def evaluate(
    data: pd.DataFrame,
    benchmark: pd.Series,
    architecture: str,
    component: str,
    windows: Sequence[str],
    cost_bps: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    previous: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for window in windows:
        part = data.loc[data["window"] == window]
        for date, day in part.groupby("datetime", sort=True):
            selected = choose(day, architecture, component)
            exposure = len(selected) / 4.0
            weights = (
                {str(symbol): exposure / len(selected) for symbol in selected["instrument"]}
                if len(selected)
                else {}
            )
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000
            gross = float(
                sum(
                    weights[str(row.instrument)] * float(row.execution_forward_return)
                    for row in selected.itertuples(index=False)
                )
            ) if len(selected) else 0.0
            periods.append(
                {
                    "window": window,
                    "datetime": date,
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
                        "instrument": str(row.instrument),
                        "sector": str(row.sector),
                        "contribution": weight * float(row.execution_forward_return)
                        - cost / max(len(selected), 1),
                    }
                )
            previous = weights
    period_frame = pd.DataFrame(periods)
    holding_frame = pd.DataFrame(holdings)
    windows_out: list[dict[str, Any]] = []
    for window, group in period_frame.groupby("window"):
        total = compound(group["net_return"])
        bench = compound(group["benchmark_return"])
        windows_out.append(
            {
                "window": window,
                "relative_excess": (1 + total) / (1 + bench) - 1,
            }
        )
    total = compound(period_frame["net_return"])
    bench = compound(period_frame["benchmark_return"])
    by_name = holding_frame.groupby("instrument")["contribution"].sum()
    by_sector = holding_frame.groupby("sector")["contribution"].sum()
    return {
        "architecture": architecture,
        "cost_bps": cost_bps,
        "relative_excess": (1 + total) / (1 + bench) - 1,
        "max_drawdown": max_drawdown(period_frame["net_return"]),
        "positive_windows": int(sum(row["relative_excess"] > 0 for row in windows_out)),
        "worst_window_relative_excess": float(
            min(row["relative_excess"] for row in windows_out)
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
        "window_results": json.dumps(clean(windows_out), sort_keys=True),
    }, period_frame


def evaluate_leave_one(
    ledger: pd.DataFrame,
    reactions: pd.DataFrame,
    calendar_index: dict[pd.Timestamp, int],
    benchmark: pd.Series,
    architecture: str,
    component: str,
    windows: Sequence[str],
) -> dict[str, Any]:
    base_data = snapshots(ledger, reactions, calendar_index, windows)
    result, _ = evaluate(base_data, benchmark, architecture, component, windows, 20)
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
    name_result, _ = evaluate(
        without_name, benchmark, architecture, component, windows, 20
    )
    sector_result, _ = evaluate(
        without_sector, benchmark, architecture, component, windows, 20
    )
    result["leave_one_name_relative_excess"] = name_result["relative_excess"]
    result["leave_one_sector_relative_excess"] = sector_result["relative_excess"]
    return result


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
    symbols = sorted(set(calibration["instrument"]) | set(validation["instrument"]))
    panel = load_provider_panel(
        provider_dir, [*symbols, BENCHMARK], fields=("open", "close", "amount")
    )
    reactions = reaction_table(disclosures(events_path), panel, symbols)
    calendar_index = {date: index for index, date in enumerate(panel.calendar)}
    benchmark = forward_returns(
        panel.fields["close"][[BENCHMARK]], horizon=10, delay=1
    )[BENCHMARK]

    calibration_data = snapshots(
        calibration, reactions, calendar_index, CALIBRATION
    )
    component_summary, component_windows, component_sectors, selected_component = (
        diagnose_components(calibration_data)
    )
    architecture_summary = pd.DataFrame()
    validation_summary = pd.DataFrame()
    reporting_summary = pd.DataFrame()
    selected_architecture: str | None = None

    if selected_component:
        rows = [
            evaluate_leave_one(
                calibration,
                reactions,
                calendar_index,
                benchmark,
                architecture,
                selected_component,
                CALIBRATION,
            )
            for architecture in ARCHITECTURES
        ]
        architecture_summary = pd.DataFrame(rows)
        baseline = architecture_summary.iloc[0]
        architecture_summary["incremental_relative_excess_vs_e0"] = (
            architecture_summary["relative_excess"] - baseline["relative_excess"]
        )
        architecture_summary["calibration_gate_pass"] = (
            (architecture_summary["architecture"] != ARCHITECTURES[0])
            & (architecture_summary["incremental_relative_excess_vs_e0"] > 0)
            & (architecture_summary["positive_windows"] == 3)
            & (
                architecture_summary["worst_window_relative_excess"]
                >= baseline["worst_window_relative_excess"]
            )
            & (architecture_summary["leave_one_name_relative_excess"] > 0)
            & (architecture_summary["leave_one_sector_relative_excess"] > 0)
            & (
                architecture_summary["maximum_sector_absolute_contribution_share"]
                <= 0.60
            )
            & (architecture_summary["mean_exposure"] >= 0.75)
        )
        winners = architecture_summary.loc[
            architecture_summary["calibration_gate_pass"]
        ].sort_values(
            ["incremental_relative_excess_vs_e0", "architecture"],
            ascending=[False, True],
            kind="mergesort",
        )
        if not winners.empty:
            selected_architecture = str(winners.iloc[0]["architecture"])
            validation_data = snapshots(
                validation, reactions, calendar_index, VALIDATION
            )
            rows = []
            for architecture in (ARCHITECTURES[0], selected_architecture):
                result = evaluate_leave_one(
                    validation,
                    reactions,
                    calendar_index,
                    benchmark,
                    architecture,
                    selected_component,
                    VALIDATION,
                )
                for cost in (10, 40):
                    cost_result, _ = evaluate(
                        validation_data,
                        benchmark,
                        architecture,
                        selected_component,
                        VALIDATION,
                        cost,
                    )
                    result[f"relative_excess_{cost}bps"] = cost_result[
                        "relative_excess"
                    ]
                rows.append(result)
            validation_summary = pd.DataFrame(rows)
            baseline_v = validation_summary.iloc[0]
            validation_summary["incremental_relative_excess_vs_e0"] = (
                validation_summary["relative_excess"] - baseline_v["relative_excess"]
            )
            validation_summary["incremental_40bps_vs_e0"] = (
                validation_summary["relative_excess_40bps"]
                - baseline_v["relative_excess_40bps"]
            )
            validation_summary["validation_gate_pass"] = (
                (validation_summary["architecture"] == selected_architecture)
                & (validation_summary["incremental_relative_excess_vs_e0"] > 0)
                & (validation_summary["incremental_40bps_vs_e0"] > 0)
                & (validation_summary["positive_windows"] >= 3)
                & (
                    validation_summary["worst_window_relative_excess"]
                    >= baseline_v["worst_window_relative_excess"]
                )
                & (validation_summary["leave_one_name_relative_excess"] > 0)
                & (validation_summary["leave_one_sector_relative_excess"] > 0)
                & (
                    validation_summary["maximum_sector_absolute_contribution_share"]
                    <= 0.55
                )
            )
            report_rows: list[dict[str, Any]] = []
            for window in REPORTING:
                report_data = snapshots(
                    reporting, reactions, calendar_index, (window,)
                )
                for architecture in (ARCHITECTURES[0], selected_architecture):
                    result, _ = evaluate(
                        report_data,
                        benchmark,
                        architecture,
                        selected_component,
                        (window,),
                        20,
                    )
                    report_rows.append({"window": window, **result})
            reporting_summary = pd.DataFrame(report_rows)

    if selected_component is None:
        decision = "disclosure_reaction_component_not_supported"
    elif selected_architecture is None:
        decision = "disclosure_reaction_architecture_not_supported"
    elif validation_summary.loc[validation_summary["validation_gate_pass"]].empty:
        decision = "disclosure_reaction_validation_not_supported"
    else:
        decision = "pit_disclosure_reaction_research_candidate"

    output_dir.mkdir(parents=True, exist_ok=True)
    decision_payload = {
        "decision": decision,
        "selected_component": selected_component,
        "selected_architecture": selected_architecture,
        "validation_opened": selected_architecture is not None,
        "creates_cn_x1_1_candidate": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output_dir / "decision.json", decision_payload)
    write_json(
        output_dir / "execution_identity.json",
        {
            "fundamental_events_sha256": sha256(events_path),
            "provider_manifest_sha256": sha256(
                provider_dir / "provider_manifest.json"
            ),
            "calibration_windows": list(CALIBRATION),
            "validation_windows": list(VALIDATION),
            "reporting_windows": list(REPORTING),
            "recent_event_sessions": 20,
            "research_only": True,
            "trade_ready": False,
        },
    )
    write_csv(output_dir / "event_reaction_features.csv", reactions)
    write_csv(output_dir / "component_summary.csv", component_summary)
    write_csv(output_dir / "component_window_summary.csv", component_windows)
    write_csv(output_dir / "component_sector_summary.csv", component_sectors)
    write_csv(output_dir / "architecture_calibration.csv", architecture_summary)
    write_csv(output_dir / "validation_summary.csv", validation_summary)
    write_csv(output_dir / "reporting_summary.csv", reporting_summary)
    report = [
        "# CN130 PIT财报披露反应条件化实验",
        "",
        f"- Decision: `{decision}`",
        f"- Selected component: {selected_component or 'none'}",
        f"- Selected architecture: {selected_architecture or 'none'}",
        f"- Validation opened: {selected_architecture is not None}",
        "- `research_only=true`; no automatic CN x1.1 promotion.",
        "",
        "## Calibration boundary",
        "",
        "The first reaction session is strictly after the disclosure date. A three-session reaction is unavailable until all three sessions are complete. Validation remains closed unless both calibration gates pass.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "experiment_id": "cn130_pit_disclosure_reaction_v1",
            "decision": decision_payload,
            "files": [
                {
                    "path": str(path.relative_to(output_dir)),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(output_dir.iterdir())
                if path.is_file()
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
