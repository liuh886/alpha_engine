"""Calibrate PIT fundamental components and test a bounded R0 quality filter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yaml

import src.research.cn130_ranking_pipeline as rank_core
from scripts.run_cn130_pit_fundamental_model import (
    COMPONENTS,
    build_period_facts,
    clean,
    load_fundamental_events,
    load_score_ledgers,
    latest_pit_snapshot,
    score_snapshot,
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

CALIBRATION_WINDOWS = ("2022H2", "2023H1", "2023H2")
VALIDATION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
REPORTING_WINDOWS = ("2026H1", "2026H2_PARTIAL")
FAMILIES = {
    "growth": ("revenue_yoy", "net_income_yoy_robust"),
    "profitability": ("net_margin", "roe_proxy"),
    "efficiency_balance": ("asset_turnover", "inverse_leverage"),
}
ARCHITECTURES = (
    "S0_r0_sector_4x1",
    "S1_r0_top3_fundamental_rerank",
    "S2_fundamental_bottom_tercile_veto",
    "S3_fundamental_median_gate",
)


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    frame = pd.concat(
        [pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")],
        axis=1,
    ).dropna()
    if len(frame) < 6 or frame.iloc[:, 0].nunique() < 2 or frame.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(frame.iloc[:, 0].corr(frame.iloc[:, 1], method="spearman"))


def _partial_corr(component: pd.Series, target: pd.Series, control: pd.Series) -> float:
    frame = pd.concat(
        [
            pd.to_numeric(component, errors="coerce"),
            pd.to_numeric(target, errors="coerce"),
            pd.to_numeric(control, errors="coerce"),
        ],
        axis=1,
    ).dropna()
    if len(frame) < 8:
        return float("nan")
    x = np.column_stack([np.ones(len(frame)), frame.iloc[:, 2].to_numpy(float)])
    component_residual = frame.iloc[:, 0].to_numpy(float) - x @ np.linalg.lstsq(
        x, frame.iloc[:, 0].to_numpy(float), rcond=None
    )[0]
    target_residual = frame.iloc[:, 1].to_numpy(float) - x @ np.linalg.lstsq(
        x, frame.iloc[:, 1].to_numpy(float), rcond=None
    )[0]
    if np.std(component_residual) <= 1e-12 or np.std(target_residual) <= 1e-12:
        return float("nan")
    return float(np.corrcoef(component_residual, target_residual)[0, 1])


def _merge_pit(day: pd.DataFrame, period_facts: pd.DataFrame, date: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
    ranked, selected_sectors = sector_selection(day)
    pit = latest_pit_snapshot(period_facts, date)
    columns = [
        "symbol",
        "fiscal_period",
        "fiscal_period_end",
        "period_available_at",
        "staleness_days",
        "usable_fundamental",
        *COMPONENTS,
    ]
    if pit.empty:
        merged = ranked.copy()
        for column in columns[1:]:
            merged[column] = np.nan
        merged["usable_fundamental"] = False
    else:
        merged = ranked.merge(
            pit[columns],
            left_on="instrument",
            right_on="symbol",
            how="left",
            validate="one_to_one",
        )
        merged["usable_fundamental"] = merged["usable_fundamental"].fillna(False).astype(bool)
    merged = score_snapshot(merged)
    merged["selected_sector"] = merged["sector"].isin(selected_sectors)
    merged["r0_sector_rank"] = merged.groupby("sector", sort=True)["score"].rank(
        method="average", pct=True
    )
    merged["target_sector_rank"] = merged.groupby("sector", sort=True)[
        "execution_forward_return"
    ].rank(method="average", pct=True)
    return merged, selected_sectors


def build_snapshot_ledger(
    ledger: pd.DataFrame,
    period_facts: pd.DataFrame,
    windows: Sequence[str],
    *,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window].copy()
        dates = sorted(pd.to_datetime(part["datetime"].unique()))[::10]
        for date in dates:
            day = part.loc[pd.to_datetime(part["datetime"]) == date].copy()
            if excluded_name:
                day = day.loc[day["instrument"] != excluded_name]
            if excluded_sector:
                day = day.loc[day["sector"] != excluded_sector]
            merged, selected_sectors = _merge_pit(day, period_facts, date)
            merged = merged.loc[merged["sector"].isin(selected_sectors)].copy()
            merged["window"] = window
            merged["datetime"] = date
            frames.append(merged)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def component_diagnostics(snapshots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    daily_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    fiscal_rows: list[dict[str, Any]] = []
    for (window, date), day in snapshots.groupby(["window", "datetime"], sort=True):
        usable = day.loc[day["usable_fundamental"]].copy()
        for component in COMPONENTS:
            column = f"{component}_pct"
            frame = usable.dropna(
                subset=[column, "execution_forward_return", "r0_sector_rank", "target_sector_rank"]
            ).copy()
            rank_ic = _safe_corr(frame[column], frame["target_sector_rank"])
            incremental_ic = _partial_corr(
                frame[column], frame["target_sector_rank"], frame["r0_sector_rank"]
            )
            spreads: list[float] = []
            for sector, group in frame.groupby("sector", sort=True):
                if len(group) < 6 or group[column].nunique() < 3:
                    continue
                low = group[column].quantile(1 / 3)
                high = group[column].quantile(2 / 3)
                spread = float(
                    group.loc[group[column] >= high, "execution_forward_return"].mean()
                    - group.loc[group[column] <= low, "execution_forward_return"].mean()
                )
                spreads.append(spread)
                sector_rows.append(
                    {
                        "window": window,
                        "datetime": date,
                        "component": component,
                        "sector": sector,
                        "spread": spread,
                    }
                )
            daily_rows.append(
                {
                    "window": window,
                    "datetime": date,
                    "component": component,
                    "n_names": len(frame),
                    "rank_ic": rank_ic,
                    "incremental_rank_ic": incremental_ic,
                    "spread": float(np.nanmean(spreads)) if spreads else float("nan"),
                }
            )
            for fiscal_period, group in frame.groupby("fiscal_period", sort=True, dropna=False):
                if len(group) < 6:
                    continue
                fiscal_rows.append(
                    {
                        "window": window,
                        "datetime": date,
                        "component": component,
                        "fiscal_period": str(fiscal_period),
                        "rank_ic": _safe_corr(group[column], group["target_sector_rank"]),
                        "n_names": len(group),
                    }
                )
    daily = pd.DataFrame(daily_rows)
    sectors = pd.DataFrame(sector_rows)
    fiscal = pd.DataFrame(fiscal_rows)
    window_summary = (
        daily.groupby(["component", "window"], as_index=False)
        .agg(
            mean_rank_ic=("rank_ic", "mean"),
            mean_incremental_rank_ic=("incremental_rank_ic", "mean"),
            mean_spread=("spread", "mean"),
            n_dates=("datetime", "nunique"),
        )
        .sort_values(["component", "window"], kind="mergesort")
    )
    summaries: list[dict[str, Any]] = []
    selected: list[str] = []
    for component in COMPONENTS:
        windows = window_summary.loc[window_summary["component"] == component]
        sector = sectors.loc[sectors["component"] == component]
        fiscal_component = fiscal.loc[fiscal["component"] == component]
        sector_totals = sector.groupby("sector")["spread"].sum().abs()
        sector_share = (
            float(sector_totals.max() / sector_totals.sum()) if sector_totals.sum() > 0 else 1.0
        )
        fiscal_summary = (
            fiscal_component.groupby("fiscal_period", as_index=False)
            .agg(mean_rank_ic=("rank_ic", "mean"), n_dates=("datetime", "nunique"))
        )
        adequate = fiscal_summary.loc[fiscal_summary["n_dates"] >= 5]
        positive_fiscal = int((adequate["mean_rank_ic"] > 0).sum())
        summary = {
            "component": component,
            "mean_rank_ic": float(windows["mean_rank_ic"].mean()),
            "positive_half_years": int((windows["mean_rank_ic"] > 0).sum()),
            "worst_half_year_rank_ic": float(windows["mean_rank_ic"].min()),
            "mean_incremental_rank_ic": float(windows["mean_incremental_rank_ic"].mean()),
            "mean_spread": float(windows["mean_spread"].mean()),
            "maximum_sector_absolute_spread_share": sector_share,
            "positive_fiscal_period_classes": positive_fiscal,
            "adequate_fiscal_period_classes": int(len(adequate)),
        }
        summary["support_gate_pass"] = bool(
            summary["mean_rank_ic"] >= 0.015
            and summary["positive_half_years"] >= 3
            and summary["worst_half_year_rank_ic"] > -0.025
            and summary["mean_incremental_rank_ic"] >= 0.005
            and summary["mean_spread"] > 0
            and summary["maximum_sector_absolute_spread_share"] <= 0.55
            and summary["positive_fiscal_period_classes"] >= 3
        )
        summaries.append(summary)
    summary_frame = pd.DataFrame(summaries)
    for family, components in FAMILIES.items():
        candidates = summary_frame.loc[
            summary_frame["component"].isin(components) & summary_frame["support_gate_pass"]
        ].sort_values(
            ["mean_incremental_rank_ic", "mean_rank_ic", "component"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        if not candidates.empty:
            selected.append(str(candidates.iloc[0]["component"]))
            summary_frame.loc[
                summary_frame["component"] == candidates.iloc[0]["component"], "selected_family"
            ] = family
    summary_frame["selected"] = summary_frame["component"].isin(selected)
    return summary_frame, window_summary, fiscal, selected


def attach_selected_composite(snapshots: pd.DataFrame, selected_components: Sequence[str]) -> pd.DataFrame:
    result = snapshots.copy()
    columns = [f"{component}_pct" for component in selected_components]
    result["selected_fundamental_composite"] = (
        result[columns].mean(axis=1, skipna=False) if columns else np.nan
    )
    return result


def choose_architecture(day: pd.DataFrame, architecture: str) -> tuple[pd.DataFrame, int]:
    pieces: list[pd.DataFrame] = []
    fallback = 0
    for _, group in day.groupby("sector", sort=True):
        ranked = group.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        usable = ranked.dropna(subset=["selected_fundamental_composite"]).copy()
        if architecture == "S0_r0_sector_4x1":
            chosen = ranked.head(1)
        elif architecture == "S1_r0_top3_fundamental_rerank":
            chosen = ranked.head(3).dropna(subset=["selected_fundamental_composite"]).sort_values(
                ["selected_fundamental_composite", "score", "instrument"],
                ascending=[False, False, True],
                kind="mergesort",
            ).head(1)
        elif architecture == "S2_fundamental_bottom_tercile_veto":
            threshold = usable["selected_fundamental_composite"].quantile(1 / 3)
            chosen = usable.loc[usable["selected_fundamental_composite"] >= threshold].sort_values(
                ["score", "instrument"], ascending=[False, True], kind="mergesort"
            ).head(1)
        elif architecture == "S3_fundamental_median_gate":
            threshold = usable["selected_fundamental_composite"].median()
            chosen = usable.loc[usable["selected_fundamental_composite"] >= threshold].sort_values(
                ["score", "instrument"], ascending=[False, True], kind="mergesort"
            ).head(1)
            if chosen.empty:
                chosen = ranked.head(1)
                fallback += 1
        else:
            raise ValueError(f"unknown architecture: {architecture}")
        if not chosen.empty:
            pieces.append(chosen)
    return (pd.concat(pieces, ignore_index=True) if pieces else day.head(0), fallback)


def run_architecture(
    snapshots: pd.DataFrame,
    benchmark_execution: pd.Series,
    architecture: str,
    cost_bps: int,
    windows: Sequence[str],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    previous: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for window in windows:
        part = snapshots.loc[snapshots["window"] == window]
        for date, day in part.groupby("datetime", sort=True):
            if date not in benchmark_execution.index:
                continue
            chosen, fallback = choose_architecture(day, architecture)
            exposure = len(chosen) / 4.0
            weights = (
                {str(symbol): exposure / len(chosen) for symbol in chosen["instrument"]}
                if len(chosen)
                else {}
            )
            gross = (
                float((chosen["execution_forward_return"] * (exposure / len(chosen))).sum())
                if len(chosen)
                else 0.0
            )
            turnover = rank_core.turnover(previous, weights)
            cost = turnover * cost_bps / 10000.0
            net = gross - cost
            benchmark = float(benchmark_execution.loc[date])
            periods.append(
                {
                    "window": window,
                    "datetime": date,
                    "architecture": architecture,
                    "net_return": net,
                    "gross_return": gross,
                    "benchmark_return": benchmark,
                    "turnover": turnover,
                    "exposure": exposure,
                    "fallback_count": fallback,
                }
            )
            for row in chosen.itertuples(index=False):
                weight = exposure / len(chosen)
                holdings.append(
                    {
                        "window": window,
                        "datetime": date,
                        "architecture": architecture,
                        "instrument": str(row.instrument),
                        "sector": str(row.sector),
                        "fiscal_period": str(row.fiscal_period),
                        "weight": weight,
                        "net_contribution": weight * float(row.execution_forward_return) - cost / len(chosen),
                    }
                )
            previous = weights
    period_frame = pd.DataFrame(periods)
    holding_frame = pd.DataFrame(holdings)
    window_results: list[dict[str, Any]] = []
    for window, group in period_frame.groupby("window", sort=False):
        total = compound(group["net_return"])
        benchmark = compound(group["benchmark_return"])
        window_results.append(
            {
                "window": window,
                "relative_excess": (1 + total) / (1 + benchmark) - 1,
                "total_return": total,
                "benchmark_return": benchmark,
            }
        )
    total = compound(period_frame["net_return"])
    benchmark = compound(period_frame["benchmark_return"])
    by_name = holding_frame.groupby("instrument")["net_contribution"].sum()
    by_sector = holding_frame.groupby("sector")["net_contribution"].sum()
    by_fiscal = holding_frame.groupby("fiscal_period")["net_contribution"].sum()
    summary = {
        "architecture": architecture,
        "cost_bps": cost_bps,
        "relative_excess": (1 + total) / (1 + benchmark) - 1,
        "total_return": total,
        "benchmark_return": benchmark,
        "max_drawdown": max_drawdown(period_frame["net_return"]),
        "positive_windows": int(sum(row["relative_excess"] > 0 for row in window_results)),
        "worst_window_relative_excess": float(min(row["relative_excess"] for row in window_results)),
        "turnover": float(period_frame["turnover"].sum()),
        "mean_exposure": float(period_frame["exposure"].mean()),
        "fallback_ratio": float(period_frame["fallback_count"].sum() / max(4 * len(period_frame), 1)),
        "maximum_name_absolute_contribution_share": float(by_name.abs().max() / by_name.abs().sum()),
        "maximum_sector_absolute_contribution_share": float(by_sector.abs().max() / by_sector.abs().sum()),
        "maximum_fiscal_period_absolute_contribution_share": float(by_fiscal.abs().max() / by_fiscal.abs().sum()),
        "top_name": str(by_name.abs().idxmax()),
        "top_sector": str(by_sector.abs().idxmax()),
        "window_results": window_results,
    }
    return summary, period_frame, holding_frame


def evaluate_with_leave_one(
    ledger: pd.DataFrame,
    period_facts: pd.DataFrame,
    benchmark_execution: pd.Series,
    selected_components: Sequence[str],
    architecture: str,
    windows: Sequence[str],
    cost_bps: int,
) -> dict[str, Any]:
    snapshots = attach_selected_composite(
        build_snapshot_ledger(ledger, period_facts, windows), selected_components
    )
    summary, _, _ = run_architecture(snapshots, benchmark_execution, architecture, cost_bps, windows)
    name_snapshots = attach_selected_composite(
        build_snapshot_ledger(
            ledger, period_facts, windows, excluded_name=summary["top_name"]
        ),
        selected_components,
    )
    sector_snapshots = attach_selected_composite(
        build_snapshot_ledger(
            ledger, period_facts, windows, excluded_sector=summary["top_sector"]
        ),
        selected_components,
    )
    leave_name, _, _ = run_architecture(
        name_snapshots, benchmark_execution, architecture, cost_bps, windows
    )
    leave_sector, _, _ = run_architecture(
        sector_snapshots, benchmark_execution, architecture, cost_bps, windows
    )
    summary["leave_one_name_relative_excess"] = leave_name["relative_excess"]
    summary["leave_one_sector_relative_excess"] = leave_sector["relative_excess"]
    return summary


def run(
    root: Path,
    provider_dir: Path,
    calibration_ledger_dir: Path,
    frozen_ledger_dir: Path,
    events_path: Path,
    output_dir: Path,
) -> None:
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    class_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    symbols = [str(value).zfill(6) for value in yaml.safe_load(universe_path.read_text())["symbols"]]
    events = load_fundamental_events(events_path)
    period_facts = build_period_facts(events)
    panel = load_provider_panel(provider_dir, [*symbols, "000300"])
    benchmark_execution = forward_returns(
        panel.fields["close"][["000300"]], horizon=10, delay=1
    )["000300"]
    calibration = load_score_ledgers(calibration_ledger_dir, CALIBRATION_WINDOWS)
    validation = load_score_ledgers(frozen_ledger_dir, VALIDATION_WINDOWS)
    reporting = load_score_ledgers(frozen_ledger_dir, REPORTING_WINDOWS)

    calibration_snapshots = build_snapshot_ledger(
        calibration, period_facts, CALIBRATION_WINDOWS
    )
    component_summary, component_windows, fiscal_summary, selected_components = component_diagnostics(
        calibration_snapshots
    )

    architecture_calibration = pd.DataFrame()
    selected_architecture: str | None = None
    validation_summary = pd.DataFrame()
    reporting_summary = pd.DataFrame()
    if selected_components:
        calibration_snapshots = attach_selected_composite(
            calibration_snapshots, selected_components
        )
        rows: list[dict[str, Any]] = []
        for architecture in ARCHITECTURES:
            summary = evaluate_with_leave_one(
                calibration,
                period_facts,
                benchmark_execution,
                selected_components,
                architecture,
                CALIBRATION_WINDOWS,
                20,
            )
            rows.append({key: value for key, value in summary.items() if key != "window_results"})
        architecture_calibration = pd.DataFrame(rows)
        baseline = architecture_calibration.loc[
            architecture_calibration["architecture"] == ARCHITECTURES[0]
        ].iloc[0]
        architecture_calibration["incremental_relative_excess_vs_s0"] = (
            architecture_calibration["relative_excess"] - baseline["relative_excess"]
        )
        architecture_calibration["calibration_gate_pass"] = (
            (architecture_calibration["architecture"] != ARCHITECTURES[0])
            & (architecture_calibration["incremental_relative_excess_vs_s0"] > 0)
            & (architecture_calibration["positive_windows"] >= 3)
            & (
                architecture_calibration["worst_window_relative_excess"]
                >= baseline["worst_window_relative_excess"] - 0.02
            )
            & (architecture_calibration["leave_one_name_relative_excess"] > 0)
            & (architecture_calibration["leave_one_sector_relative_excess"] > 0)
            & (
                architecture_calibration["maximum_fiscal_period_absolute_contribution_share"]
                <= 0.70
            )
        )
        winners = architecture_calibration.loc[
            architecture_calibration["calibration_gate_pass"]
        ].sort_values(
            ["incremental_relative_excess_vs_s0", "architecture"],
            ascending=[False, True],
            kind="mergesort",
        )
        if not winners.empty:
            selected_architecture = str(winners.iloc[0]["architecture"])
            validation_rows: list[dict[str, Any]] = []
            for architecture in (ARCHITECTURES[0], selected_architecture):
                summary20 = evaluate_with_leave_one(
                    validation,
                    period_facts,
                    benchmark_execution,
                    selected_components,
                    architecture,
                    VALIDATION_WINDOWS,
                    20,
                )
                compact = {key: value for key, value in summary20.items() if key != "window_results"}
                for cost in (10, 40):
                    snapshots = attach_selected_composite(
                        build_snapshot_ledger(validation, period_facts, VALIDATION_WINDOWS),
                        selected_components,
                    )
                    cost_summary, _, _ = run_architecture(
                        snapshots,
                        benchmark_execution,
                        architecture,
                        cost,
                        VALIDATION_WINDOWS,
                    )
                    compact[f"relative_excess_{cost}bps"] = cost_summary["relative_excess"]
                compact["window_results"] = json.dumps(
                    clean(summary20["window_results"]), ensure_ascii=False, sort_keys=True
                )
                validation_rows.append(compact)
            validation_summary = pd.DataFrame(validation_rows)
            baseline_v = validation_summary.loc[
                validation_summary["architecture"] == ARCHITECTURES[0]
            ].iloc[0]
            validation_summary["incremental_relative_excess_vs_s0"] = (
                validation_summary["relative_excess"] - baseline_v["relative_excess"]
            )
            validation_summary["incremental_40bps_vs_s0"] = (
                validation_summary["relative_excess_40bps"]
                - baseline_v["relative_excess_40bps"]
            )
            validation_summary["validation_gate_pass"] = (
                (validation_summary["architecture"] == selected_architecture)
                & (validation_summary["incremental_relative_excess_vs_s0"] > 0)
                & (validation_summary["incremental_40bps_vs_s0"] > 0)
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
                & (
                    validation_summary["maximum_fiscal_period_absolute_contribution_share"]
                    <= 0.70
                )
            )
            reporting_rows: list[dict[str, Any]] = []
            for window in REPORTING_WINDOWS:
                for architecture in (ARCHITECTURES[0], selected_architecture):
                    snapshots = attach_selected_composite(
                        build_snapshot_ledger(reporting, period_facts, (window,)),
                        selected_components,
                    )
                    summary, _, _ = run_architecture(
                        snapshots, benchmark_execution, architecture, 20, (window,)
                    )
                    reporting_rows.append(
                        {
                            "window": window,
                            **{key: value for key, value in summary.items() if key != "window_results"},
                        }
                    )
            reporting_summary = pd.DataFrame(reporting_rows)

    if not selected_components:
        decision = "fundamental_component_not_supported"
    elif selected_architecture is None:
        decision = "fundamental_filter_architecture_not_supported"
    else:
        validated = validation_summary.loc[validation_summary["validation_gate_pass"]]
        if validated.empty:
            decision = "fundamental_filter_validation_not_supported"
        elif selected_architecture == "S1_r0_top3_fundamental_rerank":
            decision = "pit_fundamental_shortlist_research_candidate"
        else:
            decision = "pit_fundamental_veto_research_candidate"

    decision_payload = {
        "decision": decision,
        "selected_components": selected_components,
        "selected_architecture": selected_architecture,
        "creates_cn_x1_1_candidate": False,
        "research_only": True,
        "trade_ready": False,
    }
    identity = {
        "provider_identity_sha256": json.loads(
            (provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
        )["provider_identity_sha256"],
        "fundamental_events_sha256": sha256(events_path),
        "universe_sha256": sha256(universe_path),
        "classification_sha256": sha256(class_path),
        "calibration_windows": list(CALIBRATION_WINDOWS),
        "validation_windows": list(VALIDATION_WINDOWS),
        "reporting_windows": list(REPORTING_WINDOWS),
        "research_only": True,
        "trade_ready": False,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "decision.json", decision_payload)
    write_json(output_dir / "execution_identity.json", identity)
    write_csv(output_dir / "component_summary.csv", component_summary)
    write_csv(output_dir / "component_window_summary.csv", component_windows)
    write_csv(output_dir / "component_fiscal_summary.csv", fiscal_summary)
    write_csv(output_dir / "architecture_calibration.csv", architecture_calibration)
    write_csv(output_dir / "validation_summary.csv", validation_summary)
    write_csv(output_dir / "reporting_summary.csv", reporting_summary)

    lines = [
        "# CN130 PIT基本面质量过滤与R0短名单实验",
        "",
        "> 2022H2–2023H2只校准组件与架构；2024–2025只允许一次冻结验证。",
        "",
        "## 最终裁决",
        "",
        f"- Decision: `{decision}`",
        f"- Selected components: {', '.join(selected_components) if selected_components else 'none'}",
        f"- Selected architecture: {selected_architecture or 'none'}",
        "- 不自动创建CN x1.1；`research_only=true`。",
        "",
        "## 组件校准",
        "",
        "| Component | Mean IC | Incremental IC | Positive windows | Worst window | Spread | Sector share | Fiscal positive | Gate | Selected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in component_summary.sort_values(
        ["support_gate_pass", "mean_incremental_rank_ic", "component"],
        ascending=[False, False, True],
        kind="mergesort",
    ).itertuples(index=False):
        lines.append(
            f"| {row.component} | {row.mean_rank_ic:.4f} | {row.mean_incremental_rank_ic:.4f} | "
            f"{row.positive_half_years}/{len(CALIBRATION_WINDOWS)} | {row.worst_half_year_rank_ic:.4f} | {row.mean_spread:.2%} | "
            f"{row.maximum_sector_absolute_spread_share:.1%} | {row.positive_fiscal_period_classes} | "
            f"{'PASS' if row.support_gate_pass else 'FAIL'} | {'YES' if row.selected else 'NO'} |"
        )
    if not architecture_calibration.empty:
        lines += [
            "",
            "## 架构校准（20bps）",
            "",
            "| Architecture | Relative excess | Increment vs S0 | Worst window | Positive windows | Leave name | Leave sector | Gate |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for row in architecture_calibration.itertuples(index=False):
            lines.append(
                f"| {row.architecture} | {row.relative_excess:.2%} | {row.incremental_relative_excess_vs_s0:.2%} | "
                f"{row.worst_window_relative_excess:.2%} | {row.positive_windows}/{len(CALIBRATION_WINDOWS)} | "
                f"{row.leave_one_name_relative_excess:.2%} | {row.leave_one_sector_relative_excess:.2%} | "
                f"{'PASS' if row.calibration_gate_pass else 'FAIL'} |"
            )
    if not validation_summary.empty:
        lines += [
            "",
            "## 冻结验证（20bps）",
            "",
            "| Architecture | Relative excess | Increment vs S0 | 40bps increment | Worst window | Positive windows | Gate |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for row in validation_summary.itertuples(index=False):
            lines.append(
                f"| {row.architecture} | {row.relative_excess:.2%} | {row.incremental_relative_excess_vs_s0:.2%} | "
                f"{row.incremental_40bps_vs_s0:.2%} | {row.worst_window_relative_excess:.2%} | "
                f"{row.positive_windows}/4 | {'PASS' if row.validation_gate_pass else 'FAIL'} |"
            )
    lines += [
        "",
        "## 解释边界",
        "",
        "- 组件和架构只从2022–2023校准。",
        "- 若组件或架构校准失败，2024–2025不会用于选择。",
        "- 2026只报告，不改变裁决。",
        "- 当前池为静态研究池，仍存在生存者偏差。",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "experiment_id": "cn130_pit_fundamental_veto_v1",
            "decision": decision_payload,
            "files": [
                {
                    "path": str(path.relative_to(output_dir)),
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
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--calibration-ledger-dir", type=Path, required=True)
    parser.add_argument("--frozen-ledger-dir", type=Path, required=True)
    parser.add_argument("--events-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.root.resolve(),
        args.provider_dir.resolve(),
        args.calibration_ledger_dir.resolve(),
        args.frozen_ledger_dir.resolve(),
        args.events_path.resolve(),
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
