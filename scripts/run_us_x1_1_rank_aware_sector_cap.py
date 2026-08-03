"""Validate the rank-aware US87 sector cap as a bounded portfolio control.

The experiment consumes the frozen deterministic US x1.1 revision-provider
score ledgers. It never refits or changes the model. The only challenger change
is a rank-aware selection constraint: scan the complete eligible cross-section
in score order, select exactly 15 names, and admit no more than four names from
one governed sector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import scripts.run_us_x1_1_drawdown_attribution_phase_a as phase_a
import scripts.run_us_x1_1_sector_style_attribution as attribution
from src.research.us87_sector_style import (
    STYLE_DIMENSIONS,
    compute_style_snapshot,
    load_pool_symbols,
    load_sector_classification,
    sha256_file,
    style_coverage,
)
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
COST_STRESS_BPS = (20, 40, 60)
TOP_N = 15
MAX_NAMES_PER_SECTOR = 4
EXPERIMENT_ID = "us_x1_1_rank_aware_sector_cap_v1"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    for column in output.columns:
        if "date" in column:
            output[column] = pd.to_datetime(output[column]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _file_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "evidence_manifest.json"
    }


def _write_manifest(root: Path) -> dict[str, Any]:
    files = []
    for relative, digest in _file_manifest(root).items():
        path = root / relative
        files.append(
            {"path": relative, "sha256": digest, "bytes": path.stat().st_size}
        )
    payload = {"schema_version": "1.0", "files": files}
    _write_json(root / "evidence_manifest.json", payload)
    return payload


def _ranked_day(scores: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    daily = scores.loc[scores["datetime"] == date, ["instrument", "score"]].copy()
    if daily.empty:
        raise ValueError(f"no scores for {date.date()}")
    return phase_a._rank_day(daily)


def _select_names(
    ranked: pd.DataFrame,
    sector_by_symbol: dict[str, str],
    *,
    sector_cap: bool,
    excluded_names: frozenset[str] = frozenset(),
    excluded_sectors: frozenset[str] = frozenset(),
) -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    """Return selected names, complete rank audit and replacement pairs."""

    baseline = ranked.head(TOP_N)["instrument"].astype(str).tolist()
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    audit_rows: list[dict[str, Any]] = []

    for row in ranked.itertuples(index=False):
        instrument = str(row.instrument)
        sector = sector_by_symbol.get(instrument, "")
        if not sector:
            raise ValueError(f"missing governed sector for {instrument}")
        reason = "not_reached"
        admitted = False
        if instrument in excluded_names:
            reason = "excluded_name"
        elif sector in excluded_sectors:
            reason = "excluded_sector"
        elif len(selected) >= TOP_N:
            reason = "after_portfolio_filled"
        elif sector_cap and sector_counts.get(sector, 0) >= MAX_NAMES_PER_SECTOR:
            reason = "sector_cap"
        else:
            selected.append(instrument)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            admitted = True
            reason = "selected"
        audit_rows.append(
            {
                "instrument": instrument,
                "rank": int(row.rank),
                "score": float(row.score),
                "sector": sector,
                "baseline_selected": instrument in baseline,
                "challenger_selected": admitted,
                "selection_reason": reason,
            }
        )

    if len(selected) != TOP_N:
        raise ValueError(
            f"selection contract filled {len(selected)} names, expected {TOP_N}"
        )
    if sector_cap and max(sector_counts.values()) > MAX_NAMES_PER_SECTOR:
        raise ValueError("sector-cap selection exceeds maximum names per sector")

    rejected = [
        row
        for row in audit_rows
        if row["baseline_selected"] and not row["challenger_selected"]
    ]
    incoming = [
        row
        for row in audit_rows
        if row["challenger_selected"] and not row["baseline_selected"]
    ]
    if len(rejected) != len(incoming):
        raise ValueError("replacement ledger does not balance")
    replacement_rows = []
    for replacement_index, (out_row, in_row) in enumerate(
        zip(rejected, incoming, strict=True), start=1
    ):
        replacement_rows.append(
            {
                "replacement_index": replacement_index,
                "out_instrument": out_row["instrument"],
                "out_rank": out_row["rank"],
                "out_sector": out_row["sector"],
                "out_reason": out_row["selection_reason"],
                "in_instrument": in_row["instrument"],
                "in_rank": in_row["rank"],
                "in_sector": in_row["sector"],
                "rank_displacement": int(in_row["rank"] - out_row["rank"]),
            }
        )
    return selected, pd.DataFrame(audit_rows), pd.DataFrame(replacement_rows)


def _evaluate(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    sector_by_symbol: dict[str, str],
    *,
    cost_bps: int,
    sector_cap: bool,
    excluded_names: frozenset[str] = frozenset(),
    excluded_sectors: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, Any],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = [
        pd.Timestamp(value)
        for value in sorted(scores["datetime"].unique())
    ][:: phase_a.REBALANCE_DAYS]
    holdings: dict[str, float] = {}
    nav = [1.0]
    benchmark_nav = [1.0]
    period_rows: list[dict[str, Any]] = []
    contribution_rows: list[dict[str, Any]] = []
    selection_rows: list[pd.DataFrame] = []
    replacement_rows: list[pd.DataFrame] = []
    total_turnover = 0.0
    total_cost = 0.0

    for period_index, date in enumerate(dates):
        ranked = _ranked_day(scores, date)
        selected, selection, replacements = _select_names(
            ranked,
            sector_by_symbol,
            sector_cap=sector_cap,
            excluded_names=excluded_names,
            excluded_sectors=excluded_sectors,
        )
        selection.insert(0, "period_index", period_index)
        selection.insert(1, "rebalance_date", date)
        selection_rows.append(selection)
        if not replacements.empty:
            replacements.insert(0, "period_index", period_index)
            replacements.insert(1, "rebalance_date", date)
            replacement_rows.append(replacements)

        target = {name: 1 / TOP_N for name in selected}
        union = sorted(set(holdings) | set(target))
        deltas = {
            name: target.get(name, 0.0) - holdings.get(name, 0.0)
            for name in union
        }
        abs_delta = float(sum(abs(value) for value in deltas.values()))
        turnover = abs_delta / 2
        cost = turnover * cost_bps / 10_000
        date_returns = returns.get(date, {})
        effective = phase_a._effective_return_weights(target, date_returns)
        gross_return = float(
            sum(weight * date_returns[name] for name, weight in effective.items())
        )
        net_return = gross_return - cost
        benchmark_return = float(benchmark.get(date, 0.0))
        nav.append(nav[-1] * (1 + net_return))
        benchmark_nav.append(benchmark_nav[-1] * (1 + benchmark_return))
        total_turnover += turnover
        total_cost += cost

        ranked_index = ranked.set_index("instrument")
        for name in union:
            target_weight = target.get(name, 0.0)
            effective_weight = effective.get(name, 0.0)
            forward_return = date_returns.get(name)
            has_return = forward_return is not None and np.isfinite(forward_return)
            gross_contribution = (
                effective_weight * float(forward_return) if has_return else 0.0
            )
            allocated_cost = (
                cost * abs(deltas[name]) / abs_delta if abs_delta > 0 else 0.0
            )
            contribution_rows.append(
                {
                    "period_index": period_index,
                    "rebalance_date": date,
                    "instrument": name,
                    "sector": sector_by_symbol[name],
                    "rank": (
                        int(ranked_index.loc[name, "rank"])
                        if name in ranked_index.index
                        else None
                    ),
                    "score": (
                        float(ranked_index.loc[name, "score"])
                        if name in ranked_index.index
                        else None
                    ),
                    "target_weight": target_weight,
                    "effective_return_weight": effective_weight,
                    "trade_delta": deltas[name],
                    "forward_10d_return": forward_return,
                    "gross_contribution": gross_contribution,
                    "allocated_cost": allocated_cost,
                    "net_contribution": gross_contribution - allocated_cost,
                    "position_role": (
                        "exit_cost_only"
                        if target_weight <= 0
                        else (
                            "held_valid_return"
                            if has_return
                            else "held_missing_return"
                        )
                    ),
                }
            )

        sector_weights = (
            pd.Series(target, dtype=float)
            .groupby(pd.Series({name: sector_by_symbol[name] for name in target}))
            .sum()
        )
        period_rows.append(
            {
                "period_index": period_index,
                "rebalance_date": date,
                "cost_bps": cost_bps,
                "turnover": turnover,
                "cost": cost,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "nav": nav[-1],
                "benchmark_nav": benchmark_nav[-1],
                "qqq_regime": "QQQ_UP" if benchmark_return >= 0 else "QQQ_DOWN",
                "max_sector_weight": float(sector_weights.max()),
                "sector_hhi": float(np.square(sector_weights).sum()),
                "active_sector_count": int(len(sector_weights)),
            }
        )
        holdings = target

    periods = pd.DataFrame(period_rows)
    contributions = pd.DataFrame(contribution_rows)
    selections = pd.concat(selection_rows, ignore_index=True)
    replacements = (
        pd.concat(replacement_rows, ignore_index=True)
        if replacement_rows
        else pd.DataFrame(
            columns=[
                "period_index",
                "rebalance_date",
                "replacement_index",
                "out_instrument",
                "out_rank",
                "out_sector",
                "out_reason",
                "in_instrument",
                "in_rank",
                "in_sector",
                "rank_displacement",
            ]
        )
    )
    reconciled = contributions.groupby("period_index")["net_contribution"].sum()
    expected = periods.set_index("period_index")["net_return"]
    if not np.allclose(
        reconciled.reindex(expected.index).to_numpy(dtype=float),
        expected.to_numpy(dtype=float),
        atol=1e-12,
        rtol=0,
    ):
        raise ValueError("contribution ledger does not reconcile")

    selected_audit = selections.loc[selections["challenger_selected"]]
    if sector_cap:
        counts = selected_audit.groupby(["period_index", "sector"]).size()
        if int(counts.max()) > MAX_NAMES_PER_SECTOR:
            raise ValueError("selection audit violates sector cap")
    if not selected_audit.groupby("period_index").size().eq(TOP_N).all():
        raise ValueError("selection audit does not retain exactly 15 names")

    result = {
        "strategy_id": (
            "top15_equal_rank_aware_sector_cap"
            if sector_cap
            else "baseline_top15_equal"
        ),
        "cost_bps": cost_bps,
        "total_return": float(nav[-1] - 1),
        "benchmark_return": float(benchmark_nav[-1] - 1),
        "excess_return": float((nav[-1] - 1) - (benchmark_nav[-1] - 1)),
        "max_drawdown": phase_a._max_drawdown(nav),
        "turnover": total_turnover,
        "costs": total_cost,
        "n_periods": int(len(periods)),
        "positive_excess_periods": int((periods["excess_return"] > 0).sum()),
    }
    return result, periods, contributions, selections, replacements


def _enrich_styles(
    frame: pd.DataFrame,
    styles: pd.DataFrame,
    classification: pd.DataFrame,
    window: str,
) -> pd.DataFrame:
    mapping = classification[
        ["symbol", "canonical_entity_name", "industry"]
    ].rename(columns={"symbol": "instrument"})
    result = frame.merge(
        mapping, on="instrument", how="left", validate="many_to_one"
    )
    result = result.merge(
        styles,
        on=["rebalance_date", "instrument"],
        how="left",
        validate="many_to_one",
    )
    if result["industry"].isna().any():
        raise ValueError(f"{window} has unclassified contribution rows")
    result.insert(0, "window", window)
    return result


def _overlap_summary(
    baseline_selections: pd.DataFrame,
    challenger_selections: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    periods = sorted(baseline_selections["period_index"].unique())
    for period in periods:
        base = baseline_selections.loc[
            (baseline_selections["period_index"] == period)
            & baseline_selections["challenger_selected"]
        ]
        candidate = challenger_selections.loc[
            (challenger_selections["period_index"] == period)
            & challenger_selections["challenger_selected"]
        ]
        base_names = set(base["instrument"].astype(str))
        candidate_names = set(candidate["instrument"].astype(str))
        candidate_ranks = candidate.set_index("instrument")["rank"]
        shared = sorted(base_names & candidate_names)
        displacement = [
            int(candidate_ranks.loc[name])
            - int(base.set_index("instrument").loc[name, "rank"])
            for name in shared
        ]
        rows.append(
            {
                "period_index": int(period),
                "rebalance_date": pd.Timestamp(base["rebalance_date"].iloc[0]),
                "overlap_count": len(shared),
                "overlap_ratio": len(shared) / TOP_N,
                "replacement_count": TOP_N - len(shared),
                "mean_shared_rank_displacement": (
                    float(np.mean(np.abs(displacement))) if displacement else 0.0
                ),
                "max_selected_rank": int(candidate["rank"].max()),
                "mean_selected_rank": float(candidate["rank"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _sector_exposure(frame: pd.DataFrame) -> pd.DataFrame:
    held = frame.loc[frame["target_weight"] > 0].copy()
    exposure = (
        held.groupby(
            ["window", "strategy_id", "period_index", "rebalance_date", "sector"],
            as_index=False,
        )["target_weight"]
        .sum()
        .rename(columns={"target_weight": "sector_weight"})
    )
    diagnostics = (
        exposure.groupby(
            ["window", "strategy_id", "period_index", "rebalance_date"]
        )
        .agg(
            max_sector_weight=("sector_weight", "max"),
            sector_hhi=(
                "sector_weight",
                lambda values: float(np.square(values).sum()),
            ),
            active_sector_count=("sector", "nunique"),
        )
        .reset_index()
    )
    return exposure.merge(
        diagnostics,
        on=["window", "strategy_id", "period_index", "rebalance_date"],
        how="left",
        validate="many_to_one",
    )


def _group_contribution(
    frame: pd.DataFrame, dimensions: Iterable[str]
) -> pd.DataFrame:
    dims = list(dimensions)
    return (
        frame.groupby(dims, dropna=False, as_index=False)[
            ["gross_contribution", "allocated_cost", "net_contribution"]
        ]
        .sum()
        .sort_values(dims)
    )


def _aggregate_windows(
    rows: list[dict[str, Any]],
    *,
    strategy_id: str,
    cost_bps: int,
) -> dict[str, Any]:
    chosen = [
        row
        for row in rows
        if row["strategy_id"] == strategy_id and row["cost_bps"] == cost_bps
    ]
    if len(chosen) != len(WINDOWS):
        raise ValueError("aggregate does not contain all four windows")
    strategy_nav = float(np.prod([1 + float(row["total_return"]) for row in chosen]))
    benchmark_nav = float(
        np.prod([1 + float(row["benchmark_return"]) for row in chosen])
    )
    positive_excess = [
        float(row["excess_return"])
        for row in chosen
        if float(row["excess_return"]) > 0
    ]
    return {
        "strategy_id": strategy_id,
        "cost_bps": cost_bps,
        "compounded_total_return": strategy_nav - 1,
        "compounded_benchmark_return": benchmark_nav - 1,
        "compounded_relative_excess": strategy_nav - benchmark_nav,
        "worst_window_drawdown": min(float(row["max_drawdown"]) for row in chosen),
        "total_turnover": float(sum(float(row["turnover"]) for row in chosen)),
        "positive_windows": int(
            sum(float(row["excess_return"]) > 0 for row in chosen)
        ),
        "strongest_positive_window_share": (
            max(positive_excess) / sum(positive_excess) if positive_excess else 0.0
        ),
    }


def _phase_comparison(
    baseline_periods: pd.DataFrame,
    challenger_periods: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    drawdown = phase_a._drawdown_path(baseline_periods)
    indices = [int(value) for value in drawdown["drawdown_period_indices"]]
    subset = baseline_periods.loc[baseline_periods["period_index"].isin(indices)]
    shock_index = int(subset.sort_values("net_return").iloc[0]["period_index"])
    rows = []
    for strategy, periods in (
        ("baseline", baseline_periods),
        ("sector_cap", challenger_periods),
    ):
        selected = periods.loc[periods["period_index"].isin(indices)].copy()
        selected["phase"] = np.where(
            selected["period_index"] < shock_index,
            "lead_in",
            np.where(
                selected["period_index"] == shock_index,
                "initial_shock",
                "continuation",
            ),
        )
        for phase, group in selected.groupby("phase", sort=False):
            rows.append(
                {
                    "strategy": strategy,
                    "phase": phase,
                    "period_count": int(len(group)),
                    "compounded_return": float(
                        np.prod(1 + group["net_return"].to_numpy(dtype=float)) - 1
                    ),
                    "compounded_benchmark_return": float(
                        np.prod(1 + group["benchmark_return"].to_numpy(dtype=float))
                        - 1
                    ),
                    "arithmetic_excess": float(group["excess_return"].sum()),
                }
            )
    return pd.DataFrame(rows), {
        "baseline_drawdown": drawdown,
        "initial_shock_period_index": shock_index,
        "initial_shock_date": pd.Timestamp(
            subset.loc[
                subset["period_index"] == shock_index, "rebalance_date"
            ].iloc[0]
        )
        .date()
        .isoformat(),
    }


def _replacement_impact(
    replacements: pd.DataFrame,
    baseline_contributions: pd.DataFrame,
    challenger_contributions: pd.DataFrame,
) -> pd.DataFrame:
    if replacements.empty:
        return replacements.copy()
    base = baseline_contributions[
        [
            "period_index",
            "instrument",
            "gross_contribution",
            "net_contribution",
            "forward_10d_return",
        ]
    ].rename(
        columns={
            "instrument": "out_instrument",
            "gross_contribution": "out_gross_contribution",
            "net_contribution": "out_net_contribution",
            "forward_10d_return": "out_forward_10d_return",
        }
    )
    challenger = challenger_contributions[
        [
            "period_index",
            "instrument",
            "gross_contribution",
            "net_contribution",
            "forward_10d_return",
        ]
    ].rename(
        columns={
            "instrument": "in_instrument",
            "gross_contribution": "in_gross_contribution",
            "net_contribution": "in_net_contribution",
            "forward_10d_return": "in_forward_10d_return",
        }
    )
    result = replacements.merge(
        base,
        on=["period_index", "out_instrument"],
        how="left",
        validate="many_to_one",
    ).merge(
        challenger,
        on=["period_index", "in_instrument"],
        how="left",
        validate="many_to_one",
    )
    result["gross_return_impact"] = (
        result["in_gross_contribution"].fillna(0)
        - result["out_gross_contribution"].fillna(0)
    )
    result["net_return_impact"] = (
        result["in_net_contribution"].fillna(0)
        - result["out_net_contribution"].fillna(0)
    )
    return result


def _sensitivity(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    sectors: dict[str, str],
    candidate_result: dict[str, Any],
    replacements: pd.DataFrame,
    *,
    window: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sector_rows = []
    for sector in sorted(set(sectors.values())):
        try:
            result, _, _, _, _ = _evaluate(
                scores,
                returns,
                benchmark,
                sectors,
                cost_bps=20,
                sector_cap=True,
                excluded_sectors=frozenset({sector}),
            )
        except ValueError as exc:
            sector_rows.append(
                {
                    "window": window,
                    "excluded_sector": sector,
                    "status": "unfillable",
                    "error": str(exc),
                }
            )
            continue
        sector_rows.append(
            {
                "window": window,
                "excluded_sector": sector,
                "status": "evaluated",
                "total_return": result["total_return"],
                "excess_return": result["excess_return"],
                "max_drawdown": result["max_drawdown"],
                "return_change": result["total_return"]
                - candidate_result["total_return"],
                "excess_change": result["excess_return"]
                - candidate_result["excess_return"],
                "drawdown_change": result["max_drawdown"]
                - candidate_result["max_drawdown"],
            }
        )

    replacement_rows = []
    incoming = sorted(
        set(replacements.get("in_instrument", pd.Series(dtype=str)))
    )
    for name in incoming:
        result, _, _, _, _ = _evaluate(
            scores,
            returns,
            benchmark,
            sectors,
            cost_bps=20,
            sector_cap=True,
            excluded_names=frozenset({str(name)}),
        )
        replacement_rows.append(
            {
                "window": window,
                "excluded_replacement": str(name),
                "total_return": result["total_return"],
                "excess_return": result["excess_return"],
                "max_drawdown": result["max_drawdown"],
                "return_change": result["total_return"]
                - candidate_result["total_return"],
                "excess_change": result["excess_return"]
                - candidate_result["excess_return"],
                "drawdown_change": result["max_drawdown"]
                - candidate_result["max_drawdown"],
            }
        )
    return pd.DataFrame(sector_rows), pd.DataFrame(replacement_rows)


def _decision(
    aggregates: list[dict[str, Any]],
    window_results: list[dict[str, Any]],
    *,
    deterministic: bool,
) -> dict[str, Any]:
    baseline20 = next(
        row
        for row in aggregates
        if row["strategy_id"] == "baseline_top15_equal" and row["cost_bps"] == 20
    )
    candidate20 = next(
        row
        for row in aggregates
        if row["strategy_id"] == "top15_equal_rank_aware_sector_cap"
        and row["cost_bps"] == 20
    )
    candidate60 = next(
        row
        for row in aggregates
        if row["strategy_id"] == "top15_equal_rank_aware_sector_cap"
        and row["cost_bps"] == 60
    )
    candidate_windows20 = [
        row
        for row in window_results
        if row["strategy_id"] == "top15_equal_rank_aware_sector_cap"
        and row["cost_bps"] == 20
    ]
    retained = (
        candidate20["compounded_relative_excess"]
        / baseline20["compounded_relative_excess"]
        if baseline20["compounded_relative_excess"] > 0
        else 0.0
    )
    drawdown_improvement = (
        candidate20["worst_window_drawdown"]
        - baseline20["worst_window_drawdown"]
    )
    turnover_ratio = (
        candidate20["total_turnover"] / baseline20["total_turnover"]
        if baseline20["total_turnover"] > 0
        else float("inf")
    )
    gates = {
        "all_four_positive_excess": all(
            float(row["excess_return"]) > 0 for row in candidate_windows20
        ),
        "positive_60bps_compounded_excess": (
            candidate60["compounded_relative_excess"] > 0
        ),
        "retains_at_least_90pct_baseline_excess": retained >= 0.90,
        "worst_drawdown_improves_at_least_4pp": drawdown_improvement >= 0.04,
        "turnover_within_115pct_baseline": turnover_ratio <= 1.15,
        "strongest_window_share_below_55pct": (
            candidate20["strongest_positive_window_share"] < 0.55
        ),
        "deterministic_repeated_materialization": deterministic,
    }
    supported = all(gates.values())
    if supported:
        decision = "rank_aware_sector_cap_supported_for_shadow"
    elif (
        drawdown_improvement >= 0.04
        and not gates["retains_at_least_90pct_baseline_excess"]
    ):
        decision = "sector_cap_reduces_risk_but_costs_too_much_alpha"
    elif drawdown_improvement >= 0.04 and (
        not gates["all_four_positive_excess"]
        or not gates["strongest_window_share_below_55pct"]
    ):
        decision = "sector_cap_improvement_is_window_specific"
    else:
        decision = "sector_cap_adds_no_value"
    return {
        "decision": decision,
        "gates": gates,
        "retained_excess_ratio": retained,
        "worst_drawdown_improvement": drawdown_improvement,
        "turnover_ratio": turnover_ratio,
        "automatic_model_update": False,
        "creates_us_x1_2_candidate": False,
        "shadow_eligible": supported,
    }


def _run_once(
    root: Path,
    *,
    provider_uri: Path,
    score_ledger_root: Path,
    reproduction_result: Path,
    universe_path: Path,
    classification_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pool = load_pool_symbols(universe_path)
    classification, classification_manifest = load_sector_classification(
        classification_path, pool
    )
    sectors = classification.set_index("symbol")["sector"].to_dict()
    reproduction = json.loads(reproduction_result.read_text(encoding="utf-8"))
    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if provider != phase_a.EXPECTED_PROVIDER:
        raise ValueError(f"unexpected provider identity: {provider}")

    window_results: list[dict[str, Any]] = []
    baseline_periods_all: list[pd.DataFrame] = []
    candidate_periods_all: list[pd.DataFrame] = []
    baseline_contrib_all: list[pd.DataFrame] = []
    candidate_contrib_all: list[pd.DataFrame] = []
    selection_all: list[pd.DataFrame] = []
    replacement_all: list[pd.DataFrame] = []
    overlap_all: list[pd.DataFrame] = []
    style_all: list[pd.DataFrame] = []
    sector_sensitivity_all: list[pd.DataFrame] = []
    replacement_sensitivity_all: list[pd.DataFrame] = []
    identity_rows: list[dict[str, Any]] = []
    phase_2025h1: dict[str, Any] | None = None
    phase_2025h1_frame = pd.DataFrame()
    degradation_2025h2: dict[str, Any] | None = None

    for window in WINDOWS:
        source = attribution._load_scores(
            score_ledger_root / window / "scores.csv", window
        )
        scores, alignment = attribution._align_scores(
            runtime,
            source,
            window,
            output_dir / "aligned_inputs" / window / "economic_scores.csv",
        )
        start = pd.Timestamp(scores["datetime"].min())
        end = pd.Timestamp(scores["datetime"].max())
        returns, benchmark, closes, volumes = attribution._market_data(
            runtime, pool, start, end
        )
        expected = attribution._expected(reproduction, window)
        dates = [
            pd.Timestamp(value)
            for value in sorted(scores["datetime"].unique())
        ][:: phase_a.REBALANCE_DAYS]
        styles = pd.concat(
            [compute_style_snapshot(closes, volumes, date, pool) for date in dates],
            ignore_index=True,
        )
        coverage = style_coverage(styles)
        if min(coverage.values()) < 0.75:
            raise ValueError(f"{window} style coverage below 75%")

        window_state: dict[str, Any] = {}
        for strategy_id, sector_cap in (
            ("baseline_top15_equal", False),
            ("top15_equal_rank_aware_sector_cap", True),
        ):
            for cost_bps in COST_STRESS_BPS:
                result, periods, contributions, selections, replacements = _evaluate(
                    scores,
                    returns,
                    benchmark,
                    sectors,
                    cost_bps=cost_bps,
                    sector_cap=sector_cap,
                )
                result["window"] = window
                result["strategy_id"] = strategy_id
                window_results.append(result)
                if cost_bps == 20:
                    periods.insert(0, "window", window)
                    periods.insert(1, "strategy_id", strategy_id)
                    contributions = _enrich_styles(
                        contributions, styles, classification, window
                    )
                    contributions.insert(1, "strategy_id", strategy_id)
                    selections.insert(0, "window", window)
                    selections.insert(1, "strategy_id", strategy_id)
                    if not replacements.empty:
                        replacements.insert(0, "window", window)
                    window_state[strategy_id] = {
                        "result": result,
                        "periods": periods,
                        "contributions": contributions,
                        "selections": selections,
                        "replacements": replacements,
                    }

        baseline = window_state["baseline_top15_equal"]
        candidate = window_state["top15_equal_rank_aware_sector_cap"]
        attribution._validate_baseline(baseline["result"], expected, window)
        identity_rows.append(
            {
                "window": window,
                "source_score_sha256": alignment["source_score_sha256"],
                "economic_score_sha256": alignment["economic_score_sha256"],
                "baseline_status": "exact_within_1e-6",
                "style_coverage_minimum": min(coverage.values()),
            }
        )
        overlap = _overlap_summary(
            baseline["selections"], candidate["selections"]
        )
        overlap.insert(0, "window", window)
        impact = _replacement_impact(
            candidate["replacements"],
            baseline["contributions"],
            candidate["contributions"],
        )
        if not impact.empty:
            impact.insert(0, "window", window)
        sector_sensitivity, replacement_sensitivity = _sensitivity(
            scores,
            returns,
            benchmark,
            sectors,
            candidate["result"],
            candidate["replacements"],
            window=window,
        )

        baseline_periods_all.append(baseline["periods"])
        candidate_periods_all.append(candidate["periods"])
        baseline_contrib_all.append(baseline["contributions"])
        candidate_contrib_all.append(candidate["contributions"])
        selection_all.extend([baseline["selections"], candidate["selections"]])
        if not impact.empty:
            replacement_all.append(impact)
        overlap_all.append(overlap)
        styles_window = styles.copy()
        styles_window.insert(0, "window", window)
        style_all.append(styles_window)
        sector_sensitivity_all.append(sector_sensitivity)
        replacement_sensitivity_all.append(replacement_sensitivity)

        if window == "2025H1":
            phase_2025h1_frame, phase_meta = _phase_comparison(
                baseline["periods"].drop(columns=["window", "strategy_id"]),
                candidate["periods"].drop(columns=["window", "strategy_id"]),
            )
            phase_2025h1 = phase_meta
        if window == "2025H2":
            pair_impact = impact.copy()
            worst_pairs = (
                pair_impact.sort_values("net_return_impact")
                .head(10)
                .to_dict(orient="records")
                if not pair_impact.empty
                else []
            )
            period_compare = baseline["periods"][
                ["period_index", "rebalance_date", "net_return"]
            ].merge(
                candidate["periods"][["period_index", "net_return"]],
                on="period_index",
                suffixes=("_baseline", "_sector_cap"),
            )
            period_compare["return_difference"] = (
                period_compare["net_return_sector_cap"]
                - period_compare["net_return_baseline"]
            )
            sector_shift = (
                candidate["contributions"]
                .loc[candidate["contributions"]["target_weight"] > 0]
                .groupby("sector")["target_weight"]
                .mean()
                .sub(
                    baseline["contributions"]
                    .loc[baseline["contributions"]["target_weight"] > 0]
                    .groupby("sector")["target_weight"]
                    .mean(),
                    fill_value=0,
                )
                .sort_values()
            )
            degradation_2025h2 = {
                "candidate_minus_baseline_total_return": float(
                    candidate["result"]["total_return"]
                    - baseline["result"]["total_return"]
                ),
                "candidate_minus_baseline_excess": float(
                    candidate["result"]["excess_return"]
                    - baseline["result"]["excess_return"]
                ),
                "candidate_minus_baseline_drawdown": float(
                    candidate["result"]["max_drawdown"]
                    - baseline["result"]["max_drawdown"]
                ),
                "worst_replacement_pairs": worst_pairs,
                "worst_periods": period_compare.sort_values("return_difference")
                .head(5)
                .to_dict(orient="records"),
                "sector_weight_shift": {
                    str(key): float(value) for key, value in sector_shift.items()
                },
            }
            _write_csv(
                output_dir / "summaries" / "2025H2_period_degradation.csv",
                period_compare,
            )

    aggregates = [
        _aggregate_windows(
            window_results, strategy_id=strategy_id, cost_bps=cost
        )
        for strategy_id in (
            "baseline_top15_equal",
            "top15_equal_rank_aware_sector_cap",
        )
        for cost in COST_STRESS_BPS
    ]

    baseline_periods = pd.concat(baseline_periods_all, ignore_index=True)
    candidate_periods = pd.concat(candidate_periods_all, ignore_index=True)
    baseline_contributions = pd.concat(baseline_contrib_all, ignore_index=True)
    candidate_contributions = pd.concat(candidate_contrib_all, ignore_index=True)
    selections = pd.concat(selection_all, ignore_index=True)
    replacements = (
        pd.concat(replacement_all, ignore_index=True)
        if replacement_all
        else pd.DataFrame()
    )
    overlap = pd.concat(overlap_all, ignore_index=True)
    styles = pd.concat(style_all, ignore_index=True)
    sector_sensitivity = pd.concat(sector_sensitivity_all, ignore_index=True)
    replacement_sensitivity = (
        pd.concat(replacement_sensitivity_all, ignore_index=True)
        if any(not frame.empty for frame in replacement_sensitivity_all)
        else pd.DataFrame()
    )

    _write_csv(output_dir / "ledgers" / "baseline_periods.csv", baseline_periods)
    _write_csv(output_dir / "ledgers" / "candidate_periods.csv", candidate_periods)
    _write_csv(
        output_dir / "ledgers" / "baseline_contributions.csv",
        baseline_contributions,
    )
    _write_csv(
        output_dir / "ledgers" / "candidate_contributions.csv",
        candidate_contributions,
    )
    _write_csv(output_dir / "ledgers" / "selection_audit.csv", selections)
    _write_csv(output_dir / "ledgers" / "replacement_impact.csv", replacements)
    _write_csv(output_dir / "ledgers" / "style_snapshots.csv", styles)
    _write_csv(output_dir / "summaries" / "overlap.csv", overlap)
    _write_csv(
        output_dir / "summaries" / "sector_sensitivity.csv",
        sector_sensitivity,
    )
    _write_csv(
        output_dir / "summaries" / "replacement_sensitivity.csv",
        replacement_sensitivity,
    )
    _write_csv(
        output_dir / "summaries" / "2025H1_phase_comparison.csv",
        phase_2025h1_frame,
    )

    all_contributions = pd.concat(
        [baseline_contributions, candidate_contributions], ignore_index=True
    )
    all_periods = pd.concat([baseline_periods, candidate_periods], ignore_index=True)
    _write_csv(
        output_dir / "ledgers" / "sector_exposure.csv",
        _sector_exposure(all_contributions),
    )
    _write_csv(
        output_dir / "summaries" / "sector_contribution.csv",
        _group_contribution(
            all_contributions, ["window", "strategy_id", "sector"]
        ),
    )
    for dimension in STYLE_DIMENSIONS:
        _write_csv(
            output_dir / "summaries" / f"{dimension}_contribution.csv",
            _group_contribution(
                all_contributions, ["window", "strategy_id", dimension]
            ),
        )
    _write_csv(
        output_dir / "summaries" / "qqq_regime_contribution.csv",
        _group_contribution(
            all_contributions.merge(
                all_periods[
                    ["window", "strategy_id", "period_index", "qqq_regime"]
                ],
                on=["window", "strategy_id", "period_index"],
                how="left",
                validate="many_to_one",
            ),
            ["window", "strategy_id", "qqq_regime"],
        ),
    )

    payload = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "issue": 432,
        "parent_model_id": "us_x1_1",
        "pool_id": "us_selected_equities_v2",
        "pool_count": len(pool),
        "research_only": True,
        "trade_ready": False,
        "provider_identity_sha256": provider,
        "source_reproduction_artifact": 8831960659,
        "classification_identity_sha256": sha256_file(classification_path),
        "classification_manifest": classification_manifest,
        "contract": {
            "top_n": TOP_N,
            "equal_weight": True,
            "maximum_names_per_sector": MAX_NAMES_PER_SECTOR,
            "effective_maximum_sector_weight": MAX_NAMES_PER_SECTOR / TOP_N,
            "rebalance_sessions": phase_a.REBALANCE_DAYS,
            "cost_stress_bps": list(COST_STRESS_BPS),
        },
        "identity_checks": identity_rows,
        "window_results": window_results,
        "aggregates": aggregates,
        "overlap_summary": {
            "mean_overlap_ratio": float(overlap["overlap_ratio"].mean()),
            "minimum_overlap_ratio": float(overlap["overlap_ratio"].min()),
            "mean_replacement_count": float(overlap["replacement_count"].mean()),
            "maximum_selected_rank": int(overlap["max_selected_rank"].max()),
            "mean_selected_rank": float(overlap["mean_selected_rank"].mean()),
            "mean_replacement_rank_displacement": (
                float(replacements["rank_displacement"].mean())
                if not replacements.empty
                else 0.0
            ),
            "maximum_replacement_rank_displacement": (
                int(replacements["rank_displacement"].max())
                if not replacements.empty
                else 0
            ),
        },
        "phase_2025H1": phase_2025h1,
        "degradation_2025H2": degradation_2025h2,
        "governance": {
            "pool_changed": False,
            "scores_changed": False,
            "features_changed": False,
            "label_changed": False,
            "model_parameters_changed": False,
            "uses_2026H1_for_selection": False,
            "development_windows_consumed": True,
            "automatic_model_update": False,
            "creates_us_x1_2_candidate": False,
        },
    }
    _write_json(output_dir / "rank_aware_sector_cap.json", payload)
    _write_manifest(output_dir)
    return payload


def run(
    root: Path,
    *,
    provider_uri: Path,
    score_ledger_root: Path,
    reproduction_result: Path,
    universe_path: Path,
    classification_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    run_a = output_dir / "run_a"
    run_b = output_dir / "run_b"
    payload_a = _run_once(
        root,
        provider_uri=provider_uri.resolve(),
        score_ledger_root=score_ledger_root.resolve(),
        reproduction_result=reproduction_result.resolve(),
        universe_path=universe_path.resolve(),
        classification_path=classification_path.resolve(),
        output_dir=run_a,
    )
    _run_once(
        root,
        provider_uri=provider_uri.resolve(),
        score_ledger_root=score_ledger_root.resolve(),
        reproduction_result=reproduction_result.resolve(),
        universe_path=universe_path.resolve(),
        classification_path=classification_path.resolve(),
        output_dir=run_b,
    )
    manifest_a = _file_manifest(run_a)
    manifest_b = _file_manifest(run_b)
    deterministic = manifest_a == manifest_b
    if not deterministic:
        differing = sorted(
            key
            for key in set(manifest_a) | set(manifest_b)
            if manifest_a.get(key) != manifest_b.get(key)
        )
        raise ValueError(f"repeated materializations differ: {differing}")

    decision = _decision(
        payload_a["aggregates"],
        payload_a["window_results"],
        deterministic=deterministic,
    )
    final = {
        **payload_a,
        "repeated_materialization": {
            "status": "exact",
            "run_a_file_count": len(manifest_a),
            "run_b_file_count": len(manifest_b),
            "run_a_tree_sha256": hashlib.sha256(
                json.dumps(
                    manifest_a, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
            "run_b_tree_sha256": hashlib.sha256(
                json.dumps(
                    manifest_b, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
        },
        "decision": decision,
    }
    _write_json(output_dir / "rank_aware_sector_cap_result.json", final)
    _write_json(
        output_dir / "evidence_manifest.json",
        {
            "schema_version": "1.0",
            "run_a": manifest_a,
            "run_b": manifest_b,
            "result_sha256": sha256_file(
                output_dir / "rank_aware_sector_cap_result.json"
            ),
        },
    )
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--score-ledger-root", type=Path, required=True)
    parser.add_argument("--reproduction-result", type=Path, required=True)
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=Path("configs/research_universes/us_selected_equities_v2.yaml"),
    )
    parser.add_argument(
        "--classification-path",
        type=Path,
        default=Path(
            "configs/research_classifications/us87_sector_industry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_rank_aware_sector_cap_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        score_ledger_root=args.score_ledger_root,
        reproduction_result=args.reproduction_result,
        universe_path=args.universe_path,
        classification_path=args.classification_path,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
