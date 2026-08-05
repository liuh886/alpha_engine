"""Evaluate a PIT fundamental within-sector CN130 candidate model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

import src.research.cn130_ranking_pipeline as rank_core
from src.research.cn130_cross_sectional_ranking import (
    compound,
    forward_returns,
    load_provider_panel,
    max_drawdown,
)

VALIDATION_WINDOWS = (
    "2024H1",
    "2024H2",
    "2025H1",
    "2025H2",
)
REPORTING_WINDOWS = ("2026H1", "2026H2_PARTIAL")
COMPONENTS = (
    "revenue_yoy",
    "net_income_yoy_robust",
    "net_margin",
    "roe_proxy",
    "asset_turnover",
    "inverse_leverage",
)
GROWTH_COMPONENTS = {"revenue_yoy", "net_income_yoy_robust"}
CANDIDATES = ("F0_r0_sector_4x1", "F1_fundamental_top1", "F2_half_blend", "F3_half_blend_fallback")


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_score_ledgers(ledger_dir: Path, windows: Sequence[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for window in windows:
        path = (
            ledger_dir
            / "score_ledgers"
            / f"{window}__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz"
        )
        frame = pd.read_csv(
            path,
            compression="gzip",
            dtype={"instrument": str},
            parse_dates=["datetime"],
        )
        frame["instrument"] = frame["instrument"].str.zfill(6)
        frame["window"] = window
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_fundamental_events(path: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    frame = pd.DataFrame(rows)
    required = {
        "symbol",
        "fiscal_period_end",
        "fiscal_year",
        "fiscal_period",
        "available_at",
        "field",
        "value",
        "revision_sequence",
        "event_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"fundamental event store missing columns: {missing}")
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["fiscal_period_end"] = pd.to_datetime(frame["fiscal_period_end"], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce", utc=True).dt.tz_convert(None)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["revision_sequence"] = pd.to_numeric(frame["revision_sequence"], errors="coerce")
    frame = frame.dropna(
        subset=["fiscal_period_end", "available_at", "value", "revision_sequence"]
    )
    frame = frame.sort_values(
        [
            "symbol",
            "fiscal_period_end",
            "field",
            "revision_sequence",
            "available_at",
            "event_id",
        ],
        kind="mergesort",
    ).drop_duplicates(["symbol", "fiscal_period_end", "field"], keep="last")
    return frame.reset_index(drop=True)


def robust_growth(current: pd.Series, previous: pd.Series, scale: pd.Series) -> pd.Series:
    denominator = previous.abs().combine(scale.abs() * 0.05, max).clip(lower=1e-9)
    return ((current - previous) / denominator).clip(-5.0, 5.0)


def build_period_facts(events: pd.DataFrame) -> pd.DataFrame:
    index_cols = ["symbol", "fiscal_period_end", "fiscal_year", "fiscal_period"]
    values = events.pivot_table(
        index=index_cols,
        columns="field",
        values="value",
        aggfunc="last",
    ).reset_index()
    available = (
        events.groupby(index_cols, as_index=False)["available_at"]
        .max()
        .rename(columns={"available_at": "period_available_at"})
    )
    frame = values.merge(available, on=index_cols, how="inner", validate="one_to_one")
    field_aliases = {
        "revenue": "revenue",
        "net_income": "net_income",
        "total_assets": "total_assets",
        "total_liabilities": "total_liabilities",
        "stockholders_equity": "stockholders_equity",
        "basic_eps": "basic_eps",
    }
    for field in field_aliases:
        if field not in frame:
            frame[field] = np.nan

    previous = frame[
        [
            "symbol",
            "fiscal_year",
            "fiscal_period",
            "revenue",
            "net_income",
            "total_assets",
            "stockholders_equity",
        ]
    ].copy()
    previous["fiscal_year"] = previous["fiscal_year"] + 1
    previous = previous.rename(
        columns={
            "revenue": "revenue_prev",
            "net_income": "net_income_prev",
            "total_assets": "total_assets_prev",
            "stockholders_equity": "stockholders_equity_prev",
        }
    )
    frame = frame.merge(
        previous,
        on=["symbol", "fiscal_year", "fiscal_period"],
        how="left",
        validate="many_to_one",
    )
    frame["revenue_yoy"] = np.where(
        (frame["revenue"] > 0) & (frame["revenue_prev"] > 0),
        frame["revenue"] / frame["revenue_prev"] - 1.0,
        np.nan,
    )
    frame["net_income_yoy_robust"] = robust_growth(
        frame["net_income"], frame["net_income_prev"], frame["revenue_prev"]
    )
    frame["net_margin"] = frame["net_income"] / frame["revenue"].replace(0.0, np.nan)
    average_equity = (
        frame["stockholders_equity"].abs() + frame["stockholders_equity_prev"].abs()
    ) / 2.0
    average_assets = (frame["total_assets"].abs() + frame["total_assets_prev"].abs()) / 2.0
    frame["roe_proxy"] = frame["net_income"] / average_equity.replace(0.0, np.nan)
    frame["asset_turnover"] = frame["revenue"] / average_assets.replace(0.0, np.nan)
    frame["inverse_leverage"] = 1.0 - (
        frame["total_liabilities"] / frame["total_assets"].replace(0.0, np.nan)
    )
    for component in COMPONENTS:
        frame[component] = pd.to_numeric(frame[component], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
    frame["available_component_count"] = frame[list(COMPONENTS)].notna().sum(axis=1)
    return frame.sort_values(
        ["symbol", "period_available_at", "fiscal_period_end"], kind="mergesort"
    ).reset_index(drop=True)


def latest_pit_snapshot(period_facts: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    available = period_facts.loc[period_facts["period_available_at"] <= date].copy()
    if available.empty:
        return available
    latest = (
        available.sort_values(
            ["symbol", "period_available_at", "fiscal_period_end"], kind="mergesort"
        )
        .drop_duplicates("symbol", keep="last")
        .copy()
    )
    latest["staleness_days"] = (date - latest["period_available_at"]).dt.days
    latest["usable_fundamental"] = (
        (latest["available_component_count"] >= 4)
        & (latest["staleness_days"] >= 0)
        & (latest["staleness_days"] <= 540)
    )
    return latest


def _winsorized_rank(values: pd.Series) -> pd.Series:
    valid = pd.to_numeric(values, errors="coerce")
    if valid.notna().sum() < 2:
        return pd.Series(np.nan, index=values.index)
    lower, upper = valid.quantile([0.05, 0.95])
    return valid.clip(lower, upper).rank(method="average", pct=True)


def score_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    scored = snapshot.copy()
    scored["freshness_score"] = 1.0 - scored["staleness_days"].clip(0, 365) / 365.0
    percentile_columns: list[str] = []
    for component in COMPONENTS:
        output = f"{component}_pct"
        percentile_columns.append(output)
        scored[output] = np.nan
        if component in GROWTH_COMPONENTS:
            groups = scored.groupby(["sector", "fiscal_period"], sort=True, dropna=False)
            for _, group in groups:
                if len(group) >= 3:
                    scored.loc[group.index, output] = _winsorized_rank(group[component])
            missing = scored[output].isna() & scored[component].notna()
            for _, group in scored.loc[missing].groupby("sector", sort=True):
                scored.loc[group.index, output] = _winsorized_rank(group[component])
        else:
            for _, group in scored.groupby("sector", sort=True):
                scored.loc[group.index, output] = _winsorized_rank(group[component])
    scored["freshness_pct"] = np.nan
    for _, group in scored.groupby("sector", sort=True):
        scored.loc[group.index, "freshness_pct"] = _winsorized_rank(group["freshness_score"])
    percentile_columns.append("freshness_pct")
    scored["fundamental_composite"] = scored[percentile_columns].mean(axis=1, skipna=True)
    scored.loc[~scored["usable_fundamental"], "fundamental_composite"] = np.nan
    return scored


def sector_selection(day: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    ranked = day.dropna(subset=["score", "execution_forward_return"]).copy()
    ranked["global_score_pct"] = ranked["score"].rank(method="average", pct=True)
    ranked["sector_score_pct"] = ranked.groupby("sector", sort=True)["score"].rank(
        method="average", pct=True
    )
    sector_scores = (
        ranked.groupby("sector", sort=True)["global_score_pct"]
        .apply(lambda values: float(values.nlargest(min(3, len(values))).mean()))
        .sort_values(ascending=False, kind="mergesort")
    )
    return ranked, list(sector_scores.head(4).index)


def prepare_rebalance_snapshot(
    day: pd.DataFrame,
    period_facts: pd.DataFrame,
    date: pd.Timestamp,
    sector_members: Mapping[str, int],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
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
        merged["usable_fundamental"] = merged["usable_fundamental"].fillna(False)
    merged = score_snapshot(merged)
    overall_coverage = float(merged["usable_fundamental"].sum() / len(merged)) if len(merged) else 0.0
    selected_sector_coverage: dict[str, float] = {}
    for sector in selected_sectors:
        usable = int(
            merged.loc[
                (merged["sector"] == sector) & merged["usable_fundamental"]
            ].shape[0]
        )
        selected_sector_coverage[sector] = usable / max(int(sector_members[sector]), 1)
    date_gate_pass = bool(
        overall_coverage >= 0.80
        and selected_sector_coverage
        and min(selected_sector_coverage.values()) >= 0.70
    )
    diagnostics = {
        "overall_coverage": overall_coverage,
        "selected_sector_coverage": selected_sector_coverage,
        "date_gate_pass": date_gate_pass,
    }
    return merged, selected_sectors, diagnostics


def choose_holdings(
    snapshot: pd.DataFrame,
    selected_sectors: Sequence[str],
    candidate_id: str,
    sector_coverage: Mapping[str, float],
) -> tuple[pd.DataFrame, int]:
    pieces: list[pd.DataFrame] = []
    fallback_count = 0
    for sector in selected_sectors:
        group = snapshot.loc[snapshot["sector"] == sector].copy()
        group = group.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        if candidate_id == "F0_r0_sector_4x1":
            chosen = group.head(1)
        else:
            usable = group.dropna(subset=["fundamental_composite"]).copy()
            if not usable.empty:
                usable["fundamental_rank"] = usable["fundamental_composite"].rank(
                    method="average", pct=True
                )
                usable["r0_rank"] = usable["score"].rank(method="average", pct=True)
                usable["blend_rank"] = 0.5 * usable["fundamental_rank"] + 0.5 * usable["r0_rank"]
            if candidate_id == "F1_fundamental_top1":
                chosen = usable.sort_values(
                    ["fundamental_composite", "instrument"],
                    ascending=[False, True],
                    kind="mergesort",
                ).head(1)
            elif candidate_id == "F2_half_blend":
                chosen = usable.sort_values(
                    ["blend_rank", "instrument"],
                    ascending=[False, True],
                    kind="mergesort",
                ).head(1)
            elif candidate_id == "F3_half_blend_fallback":
                if float(sector_coverage.get(sector, 0.0)) >= 0.70 and not usable.empty:
                    chosen = usable.sort_values(
                        ["blend_rank", "instrument"],
                        ascending=[False, True],
                        kind="mergesort",
                    ).head(1)
                else:
                    chosen = group.head(1)
                    fallback_count += 1
            else:
                raise ValueError(f"unknown candidate: {candidate_id}")
        if not chosen.empty:
            pieces.append(chosen)
    return (pd.concat(pieces, ignore_index=True) if pieces else snapshot.head(0), fallback_count)


def run_portfolio(
    ledger: pd.DataFrame,
    period_facts: pd.DataFrame,
    benchmark_execution: pd.Series,
    sector_members: Mapping[str, int],
    candidate_id: str,
    cost_bps: int,
    windows: Sequence[str],
    *,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    previous: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window].copy()
        dates = sorted(pd.to_datetime(part["datetime"].unique()))[::10]
        for date in dates:
            if date not in benchmark_execution.index:
                continue
            day = part.loc[pd.to_datetime(part["datetime"]) == date].copy()
            if excluded_name:
                day = day.loc[day["instrument"] != excluded_name]
            if excluded_sector:
                day = day.loc[day["sector"] != excluded_sector]
            snapshot, sectors, diagnostics = prepare_rebalance_snapshot(
                day, period_facts, date, sector_members
            )
            chosen, fallback_count = choose_holdings(
                snapshot,
                sectors,
                candidate_id,
                diagnostics["selected_sector_coverage"],
            )
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
                    "candidate_id": candidate_id,
                    "gross_return": gross,
                    "net_return": net,
                    "benchmark_return": benchmark,
                    "turnover": turnover,
                    "cost": cost,
                    "exposure": exposure,
                    "n_holdings": len(chosen),
                    "fallback_count": fallback_count,
                    "date_gate_pass": diagnostics["date_gate_pass"],
                    "overall_coverage": diagnostics["overall_coverage"],
                }
            )
            for row in chosen.itertuples(index=False):
                weight = exposure / len(chosen)
                holdings.append(
                    {
                        "window": window,
                        "datetime": date,
                        "candidate_id": candidate_id,
                        "instrument": str(row.instrument),
                        "sector": str(row.sector),
                        "fiscal_period": str(row.fiscal_period),
                        "weight": weight,
                        "net_contribution": weight * float(row.execution_forward_return)
                        - cost / len(chosen),
                        "beat_benchmark": bool(float(row.execution_forward_return) > benchmark),
                        "fundamental_composite": (
                            None
                            if pd.isna(row.fundamental_composite)
                            else float(row.fundamental_composite)
                        ),
                    }
                )
            coverage_rows.append(
                {
                    "window": window,
                    "datetime": date,
                    "candidate_id": candidate_id,
                    "overall_coverage": diagnostics["overall_coverage"],
                    "minimum_selected_sector_coverage": (
                        min(diagnostics["selected_sector_coverage"].values())
                        if diagnostics["selected_sector_coverage"]
                        else 0.0
                    ),
                    "date_gate_pass": diagnostics["date_gate_pass"],
                    "fallback_count": fallback_count,
                }
            )
            previous = weights
    period_frame = pd.DataFrame(periods)
    holding_frame = pd.DataFrame(holdings)
    coverage_frame = pd.DataFrame(coverage_rows)
    window_results: list[dict[str, Any]] = []
    for window, group in period_frame.groupby("window", sort=False):
        total = compound(group["net_return"])
        benchmark = compound(group["benchmark_return"])
        window_results.append(
            {
                "window": window,
                "relative_excess": (1.0 + total) / (1.0 + benchmark) - 1.0,
                "total_return": total,
                "benchmark_return": benchmark,
                "max_drawdown": max_drawdown(group["net_return"]),
            }
        )
    total = compound(period_frame["net_return"])
    benchmark = compound(period_frame["benchmark_return"])
    if holding_frame.empty:
        name_share = sector_share = fiscal_share = 1.0
        top_name = top_sector = "none"
        precision = 0.0
    else:
        by_name = holding_frame.groupby("instrument")["net_contribution"].sum()
        by_sector = holding_frame.groupby("sector")["net_contribution"].sum()
        by_fiscal = holding_frame.groupby("fiscal_period")["net_contribution"].sum()
        name_share = float(by_name.abs().max() / by_name.abs().sum()) if by_name.abs().sum() else 1.0
        sector_share = float(by_sector.abs().max() / by_sector.abs().sum()) if by_sector.abs().sum() else 1.0
        fiscal_share = float(by_fiscal.abs().max() / by_fiscal.abs().sum()) if by_fiscal.abs().sum() else 1.0
        top_name = str(by_name.abs().idxmax())
        top_sector = str(by_sector.abs().idxmax())
        precision = float(holding_frame["beat_benchmark"].mean())
    summary = {
        "candidate_id": candidate_id,
        "cost_bps": cost_bps,
        "total_return": total,
        "benchmark_return": benchmark,
        "relative_excess": (1.0 + total) / (1.0 + benchmark) - 1.0,
        "max_drawdown": max_drawdown(period_frame["net_return"]),
        "turnover": float(period_frame["turnover"].sum()),
        "positive_excess_windows": int(sum(row["relative_excess"] > 0 for row in window_results)),
        "worst_window_relative_excess": float(min(row["relative_excess"] for row in window_results)),
        "precision_at_4": precision,
        "average_period_excess": float(
            (period_frame["gross_return"] - period_frame["benchmark_return"]).mean()
        ),
        "mean_exposure": float(period_frame["exposure"].mean()),
        "fallback_sector_ratio": float(period_frame["fallback_count"].sum() / (4 * len(period_frame))),
        "coverage_gate_date_ratio": float(coverage_frame["date_gate_pass"].mean()),
        "maximum_name_absolute_contribution_share": name_share,
        "maximum_sector_absolute_contribution_share": sector_share,
        "maximum_fiscal_period_absolute_contribution_share": fiscal_share,
        "top_name": top_name,
        "top_sector": top_sector,
        "window_results": window_results,
    }
    return summary, period_frame, holding_frame, coverage_frame


def run(
    root: Path,
    provider_dir: Path,
    ledger_dir: Path,
    events_path: Path,
    output_dir: Path,
) -> None:
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    class_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    symbols = [str(value).zfill(6) for value in yaml.safe_load(universe_path.read_text())["symbols"]]
    classification = yaml.safe_load(class_path.read_text())["symbols"]
    sector_map = {str(symbol).zfill(6): str(meta["sector"]) for symbol, meta in classification.items()}
    sector_members = pd.Series(sector_map).value_counts().to_dict()

    events = load_fundamental_events(events_path)
    period_facts = build_period_facts(events)
    panel = load_provider_panel(provider_dir, [*symbols, "000300"])
    benchmark_execution = forward_returns(
        panel.fields["close"][["000300"]], horizon=10, delay=1
    )["000300"]
    validation = load_score_ledgers(ledger_dir, VALIDATION_WINDOWS)
    reporting = load_score_ledgers(ledger_dir, REPORTING_WINDOWS)

    summaries: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    reporting_rows: list[dict[str, Any]] = []
    baseline_by_cost: dict[int, dict[str, Any]] = {}
    by_candidate_cost: dict[tuple[str, int], dict[str, Any]] = {}
    coverage_reference: pd.DataFrame | None = None

    for candidate in CANDIDATES:
        for cost in (10, 20, 40):
            summary, periods, holdings, coverage = run_portfolio(
                validation,
                period_facts,
                benchmark_execution,
                sector_members,
                candidate,
                cost,
                VALIDATION_WINDOWS,
            )
            by_candidate_cost[(candidate, cost)] = summary
            if candidate == CANDIDATES[0]:
                baseline_by_cost[cost] = summary
            if cost == 20:
                leave_name, _, _, _ = run_portfolio(
                    validation,
                    period_facts,
                    benchmark_execution,
                    sector_members,
                    candidate,
                    cost,
                    VALIDATION_WINDOWS,
                    excluded_name=summary["top_name"],
                )
                leave_sector, _, _, _ = run_portfolio(
                    validation,
                    period_facts,
                    benchmark_execution,
                    sector_members,
                    candidate,
                    cost,
                    VALIDATION_WINDOWS,
                    excluded_sector=summary["top_sector"],
                )
                compact = {key: value for key, value in summary.items() if key != "window_results"}
                compact["leave_one_name_relative_excess"] = leave_name["relative_excess"]
                compact["leave_one_sector_relative_excess"] = leave_sector["relative_excess"]
                summaries.append(compact)
                details.append(
                    {
                        "candidate_id": candidate,
                        "window_results": summary["window_results"],
                        "periods": periods.to_dict("records"),
                        "holdings": holdings.to_dict("records"),
                    }
                )
                if coverage_reference is None:
                    coverage_reference = coverage.copy()
        for window in REPORTING_WINDOWS:
            result, _, _, _ = run_portfolio(
                reporting,
                period_facts,
                benchmark_execution,
                sector_members,
                candidate,
                20,
                (window,),
            )
            reporting_rows.append(
                {"window": window, **{key: value for key, value in result.items() if key != "window_results"}}
            )

    summary_frame = pd.DataFrame(summaries)
    summary_frame["relative_excess_10bps"] = summary_frame["candidate_id"].map(
        lambda candidate: by_candidate_cost[(candidate, 10)]["relative_excess"]
    )
    summary_frame["relative_excess_40bps"] = summary_frame["candidate_id"].map(
        lambda candidate: by_candidate_cost[(candidate, 40)]["relative_excess"]
    )
    baseline20 = baseline_by_cost[20]
    baseline40 = baseline_by_cost[40]
    summary_frame["incremental_relative_excess_vs_f0"] = summary_frame["relative_excess"] - baseline20["relative_excess"]
    summary_frame["incremental_40bps_vs_f0"] = summary_frame["relative_excess_40bps"] - baseline40["relative_excess"]
    stage0_pass = bool(
        coverage_reference is not None
        and float(coverage_reference["date_gate_pass"].mean()) >= 0.75
    )
    summary_frame["support_gate_pass"] = (
        stage0_pass
        & (summary_frame["candidate_id"] != CANDIDATES[0])
        & (summary_frame["incremental_relative_excess_vs_f0"] > 0)
        & (summary_frame["incremental_40bps_vs_f0"] > 0)
        & (summary_frame["worst_window_relative_excess"] >= baseline20["worst_window_relative_excess"])
        & (summary_frame["positive_excess_windows"] >= 3)
        & (summary_frame["leave_one_name_relative_excess"] > 0)
        & (summary_frame["leave_one_sector_relative_excess"] > 0)
        & (summary_frame["maximum_sector_absolute_contribution_share"] <= 0.55)
        & (summary_frame["maximum_fiscal_period_absolute_contribution_share"] <= 0.70)
    )
    supported = summary_frame.loc[summary_frame["support_gate_pass"], "candidate_id"].tolist()
    if not stage0_pass:
        decision = "data_blocked"
    elif "F1_fundamental_top1" in supported:
        decision = "pit_fundamental_model_supported_research_candidate"
    elif supported:
        decision = "pit_fundamental_blend_supported_research_candidate"
    else:
        decision = "pit_fundamental_model_not_supported"

    decision_payload = {
        "decision": decision,
        "stage0_coverage_gate_pass": stage0_pass,
        "coverage_gate_date_ratio": (
            float(coverage_reference["date_gate_pass"].mean())
            if coverage_reference is not None
            else 0.0
        ),
        "supported_candidates": supported,
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
        "candidate_weights": {"F2": {"r0": 0.5, "fundamental": 0.5}, "F3": {"r0": 0.5, "fundamental": 0.5}},
        "coverage_thresholds": {"overall": 0.80, "selected_sector": 0.70, "date_ratio": 0.75},
        "research_only": True,
        "trade_ready": False,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "decision.json", decision_payload)
    write_json(output_dir / "execution_identity.json", identity)
    write_json(output_dir / "portfolio_details.json", details)
    write_csv(
        output_dir / "model_summary.csv",
        summary_frame.sort_values(
            ["support_gate_pass", "relative_excess"], ascending=[False, False], kind="mergesort"
        ),
    )
    write_csv(output_dir / "reporting_summary.csv", pd.DataFrame(reporting_rows))
    if coverage_reference is not None:
        write_csv(output_dir / "coverage_by_rebalance.csv", coverage_reference)
    write_csv(
        output_dir / "period_fundamental_coverage.csv",
        period_facts.groupby(["fiscal_period", "fiscal_year"], as_index=False).agg(
            symbols=("symbol", "nunique"),
            rows=("symbol", "size"),
            median_components=("available_component_count", "median"),
        ),
    )

    lines = [
        "# CN130 PIT基本面行业内选股实验",
        "",
        "> R0只选择4个行业；PIT基本面只负责行业内Top1。2024–2025冻结验证，2026仅报告。",
        "",
        "## 最终裁决",
        "",
        f"- Decision: `{decision}`",
        f"- Stage 0 coverage gate: {stage0_pass}",
        f"- Coverage-qualified rebalance ratio: {decision_payload['coverage_gate_date_ratio']:.1%}",
        f"- Supported candidates: {', '.join(supported) if supported else 'none'}",
        "- 不自动创建CN x1.1；`research_only=true`。",
        "",
        "## 候选结果（20bps）",
        "",
        "| 候选 | 相对超额 | 对F0增量 | 40bps超额 | 最大回撤 | 最差窗口 | 正窗口 | Precision@4 | 覆盖合格期 | 回退行业 | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary_frame.sort_values(
        ["support_gate_pass", "relative_excess"], ascending=[False, False], kind="mergesort"
    ).itertuples(index=False):
        lines.append(
            f"| {row.candidate_id} | {row.relative_excess:.2%} | {row.incremental_relative_excess_vs_f0:.2%} | "
            f"{row.relative_excess_40bps:.2%} | {row.max_drawdown:.2%} | {row.worst_window_relative_excess:.2%} | "
            f"{row.positive_excess_windows}/4 | {row.precision_at_4:.1%} | {row.coverage_gate_date_ratio:.1%} | "
            f"{row.fallback_sector_ratio:.1%} | {'PASS' if row.support_gate_pass else 'FAIL'} |"
        )
    lines += [
        "",
        "## 解释边界",
        "",
        "- 基本面事实只在`available_at`之后进入模型。",
        "- 组件方向、0.5/0.5权重和覆盖门槛均在验证前固定。",
        "- 不根据2024–2025收益重新选择字段、权重或回退规则。",
        "- 当前CN130为静态研究池，生存者偏差仍存在。",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = [path for path in output_dir.rglob("*") if path.is_file() and path.name != "evidence_manifest.json"]
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "experiment_id": "cn130_pit_fundamental_within_sector_v1",
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
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--events-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.root.resolve(),
        args.provider_dir.resolve(),
        args.ledger_dir.resolve(),
        args.events_path.resolve(),
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
