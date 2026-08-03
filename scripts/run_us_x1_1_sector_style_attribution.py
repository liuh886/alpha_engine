"""Attribute US x1.1 sector, market-style and 2025H1 drawdown mechanisms."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import scripts.run_us_x1_1_drawdown_attribution_phase_a as phase_a
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.us87_sector_style import (
    STYLE_DIMENSIONS,
    cap_sector_weights,
    compute_style_snapshot,
    load_pool_symbols,
    load_sector_classification,
    sha256_file,
    style_coverage,
)
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
SCORE_SHA = {
    "2024H1": "e90b7d301d6487f8f5c858006b4e5dfc2bb837c63f8b6cd7dba4faf7556aed89",
    "2024H2": "f0af377afa17d8c55e4f7dee8770e7f24794a77c9dcaf91a322b9b1ebef7c061",
    "2025H1": "3e4390f38615118ab3ae0218e0d4df7855a82654b829584db47520685b7b0301",
    "2025H2": "121bcd1fdd8a59f1f51df5bb60dfbb021ea88b1176b66611018b1779b2150ec2",
}
SECTOR_CAP = 0.30


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    for column in output.columns:
        if "date" in column:
            output[column] = pd.to_datetime(output[column]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _load_scores(path: Path, window: str) -> pd.DataFrame:
    if sha256_file(path) != SCORE_SHA[window]:
        raise ValueError(f"{window} score identity does not match Experiment 007")
    frame = pd.read_csv(path)
    if list(frame.columns) != ["datetime", "instrument", "score"]:
        raise ValueError("score ledger columns are not canonical")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if frame.duplicated(["datetime", "instrument"]).any():
        raise ValueError(f"{window} score ledger contains duplicates")
    return frame.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)


def _align_scores(
    runtime: QlibUSExecutionRuntime,
    scores: pd.DataFrame,
    window: str,
    output_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    symbols = sorted(scores["instrument"].unique())
    start = scores["datetime"].min().strftime("%Y-%m-%d")
    end = scores["datetime"].max().strftime("%Y-%m-%d")
    returns = normalize_qlib_frame_index(
        runtime.features(symbols, [phase_a.RETURN_EXPRESSION], start, end)
    )
    returns.columns = ["return"]
    valid = returns.loc[np.isfinite(returns["return"].to_numpy(dtype=float))]
    valid = valid.reset_index()[["datetime", "instrument"]]
    valid["datetime"] = pd.to_datetime(valid["datetime"]).dt.normalize()
    economic = scores.merge(
        valid,
        on=["datetime", "instrument"],
        how="inner",
        validate="one_to_one",
    ).sort_values(["datetime", "instrument"], kind="mergesort")
    economic = economic.reset_index(drop=True)
    if economic.empty:
        raise ValueError(f"{window} aligned score ledger is empty")
    _write_csv(output_path, economic)
    return economic, {
        "window": window,
        "source_score_sha256": SCORE_SHA[window],
        "economic_score_sha256": sha256_file(output_path),
        "source_rows": int(len(scores)),
        "economic_rows": int(len(economic)),
        "excluded_rows": int(len(scores) - len(economic)),
    }


def _market_data(
    runtime: QlibUSExecutionRuntime,
    symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[
    dict[pd.Timestamp, dict[str, float]],
    dict[pd.Timestamp, float],
    pd.DataFrame,
    pd.DataFrame,
]:
    start_text = start.strftime("%Y-%m-%d")
    end_text = end.strftime("%Y-%m-%d")
    returns = normalize_qlib_frame_index(
        runtime.features(symbols, [phase_a.RETURN_EXPRESSION], start_text, end_text)
    )
    returns.columns = ["return"]
    qqq = normalize_qlib_frame_index(
        runtime.features(["QQQ"], [phase_a.RETURN_EXPRESSION], start_text, end_text)
    )
    qqq.columns = ["return"]
    benchmark = {
        pd.Timestamp(date): float(group["return"].iloc[0])
        for date, group in qqq.reset_index().groupby("datetime")
    }
    history_start = (start - pd.Timedelta(days=180)).strftime("%Y-%m-%d")
    close = normalize_qlib_frame_index(
        runtime.features([*symbols, "QQQ"], ["$close"], history_start, end_text)
    )
    volume = normalize_qlib_frame_index(
        runtime.features([*symbols, "QQQ"], ["$volume"], history_start, end_text)
    )
    close.columns = ["close"]
    volume.columns = ["volume"]
    closes = close["close"].unstack(level="instrument").sort_index()
    volumes = volume["volume"].unstack(level="instrument").sort_index()
    return phase_a._return_lookup(returns), benchmark, closes, volumes


def _expected(reproduction: dict[str, Any], window: str) -> dict[str, Any]:
    row = next(item for item in reproduction["run_a"]["windows"] if item["window"] == window)
    return row["cost_stress"]["20"]


def _validate_baseline(observed: dict[str, Any], expected: dict[str, Any], window: str) -> None:
    for key in ("total_return", "benchmark_return", "excess_return", "max_drawdown", "turnover"):
        if not math.isclose(float(observed[key]), float(expected[key]), rel_tol=0, abs_tol=1e-6):
            raise ValueError(f"{window} baseline mismatch for {key}")


def _style_ledger(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    dates: list[pd.Timestamp],
    symbols: list[str],
) -> pd.DataFrame:
    return pd.concat(
        [compute_style_snapshot(closes, volumes, date, symbols) for date in dates],
        ignore_index=True,
    )


def _enrich(
    contributions: pd.DataFrame,
    classification: pd.DataFrame,
    styles: pd.DataFrame,
    window: str,
) -> pd.DataFrame:
    mapping = classification[
        ["symbol", "canonical_entity_name", "sector", "industry"]
    ].rename(columns={"symbol": "instrument"})
    frame = contributions.merge(mapping, on="instrument", how="left", validate="many_to_one")
    frame = frame.merge(
        styles,
        on=["rebalance_date", "instrument"],
        how="left",
        validate="many_to_one",
    )
    if frame["sector"].isna().any():
        raise ValueError(f"{window} contribution ledger has unclassified names")
    frame.insert(0, "window", window)
    return frame


def _sector_exposure(frame: pd.DataFrame) -> pd.DataFrame:
    held = frame.loc[frame["target_weight"] > 0]
    result = held.groupby(
        ["window", "period_index", "rebalance_date", "sector"], as_index=False
    )["target_weight"].sum()
    result = result.rename(columns={"target_weight": "sector_weight"})
    diagnostics = result.groupby(["window", "period_index", "rebalance_date"]).agg(
        max_sector_weight=("sector_weight", "max"),
        sector_hhi=("sector_weight", lambda values: float(np.square(values).sum())),
        active_sector_count=("sector", "nunique"),
    ).reset_index()
    return result.merge(diagnostics, on=["window", "period_index", "rebalance_date"])


def _group_contribution(frame: pd.DataFrame, dimension: str, scope: str) -> pd.DataFrame:
    result = frame.groupby(["window", dimension], dropna=False, as_index=False)[
        ["gross_contribution", "allocated_cost", "net_contribution"]
    ].sum()
    result.insert(0, "scope", scope)
    return result.sort_values(["window", "net_contribution", dimension])


def _style_contribution(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    rows = []
    for dimension in STYLE_DIMENSIONS:
        grouped = frame.groupby(["window", dimension], dropna=False, as_index=False)[
            ["gross_contribution", "allocated_cost", "net_contribution"]
        ].sum()
        grouped.insert(1, "style_dimension", dimension)
        grouped = grouped.rename(columns={dimension: "style_bucket"})
        rows.append(grouped)
    result = pd.concat(rows, ignore_index=True)
    result.insert(0, "scope", scope)
    return result


def _negative_loss_share(frame: pd.DataFrame, dimension: str) -> dict[str, Any]:
    negative = frame.loc[frame["net_contribution"] < 0].copy()
    if negative.empty:
        return {"dimension": dimension, "top_bucket": None, "top_loss_share": 0.0}
    grouped = -negative.groupby(dimension, dropna=False)["net_contribution"].sum()
    grouped = grouped.sort_values(ascending=False)
    total = float(grouped.sum())
    return {
        "dimension": dimension,
        "top_bucket": str(grouped.index[0]),
        "top_loss": float(grouped.iloc[0]),
        "total_negative_loss": total,
        "top_loss_share": float(grouped.iloc[0] / total) if total else 0.0,
    }


def _brinson(
    frame: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    classification: pd.DataFrame,
    pool_symbols: list[str],
) -> pd.DataFrame:
    sector_members = classification.groupby("sector")["symbol"].apply(list).to_dict()
    rows: list[dict[str, Any]] = []
    for (window, period, date), group in frame.groupby(
        ["window", "period_index", "rebalance_date"], sort=True
    ):
        date = pd.Timestamp(date)
        available = returns.get(date, {})
        reference_names = [name for name in pool_symbols if name in available]
        if not reference_names:
            continue
        reference_return = float(np.mean([available[name] for name in reference_names]))
        for sector in sorted(sector_members):
            selected = group.loc[
                (group["sector"] == sector) & (group["effective_return_weight"] > 0)
            ]
            wp = float(selected["effective_return_weight"].sum())
            rp = float(selected["gross_contribution"].sum() / wp) if wp > 0 else 0.0
            reference_sector = [name for name in sector_members[sector] if name in available]
            wb = len(reference_sector) / len(reference_names)
            rb = (
                float(np.mean([available[name] for name in reference_sector]))
                if reference_sector
                else reference_return
            )
            allocation = (wp - wb) * (rb - reference_return)
            selection = wb * (rp - rb)
            interaction = (wp - wb) * (rp - rb)
            rows.append(
                {
                    "window": window,
                    "period_index": int(period),
                    "rebalance_date": date,
                    "sector": sector,
                    "portfolio_weight": wp,
                    "reference_weight": wb,
                    "portfolio_sector_return": rp,
                    "reference_sector_return": rb,
                    "reference_pool_return": reference_return,
                    "allocation_effect": allocation,
                    "selection_effect": selection,
                    "interaction_effect": interaction,
                    "total_effect": allocation + selection + interaction,
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        total = result.groupby(["window", "period_index"])["total_effect"].sum()
        expected = frame.groupby(["window", "period_index"])["gross_contribution"].sum()
        reference = result.groupby(["window", "period_index"])["reference_pool_return"].first()
        if not np.allclose(total, expected - reference, atol=1e-10, rtol=0):
            raise ValueError("Brinson attribution does not reconcile")
    return result


def _sector_cap_evaluate(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    sectors: dict[str, str],
    cost_bps: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())]
    holdings: dict[str, float] = {}
    nav = [1.0]
    qqq_nav = [1.0]
    rows = []
    turnover_total = 0.0
    for index, date in enumerate(dates[:: phase_a.REBALANCE_DAYS]):
        ranked = phase_a._rank_day(scores.loc[scores["datetime"] == date])
        base = pd.Series(0.0, index=ranked["instrument"].astype(str))
        base.loc[ranked.head(15)["instrument"].astype(str)] = 1 / 15
        target_series = cap_sector_weights(base, sectors, SECTOR_CAP)
        target = {str(name): float(weight) for name, weight in target_series.items() if weight > 0}
        names = sorted(set(holdings) | set(target))
        turnover = sum(abs(target.get(name, 0) - holdings.get(name, 0)) for name in names) / 2
        cost = turnover * cost_bps / 10_000
        effective = phase_a._effective_return_weights(target, returns.get(date, {}))
        gross = sum(weight * returns[date][name] for name, weight in effective.items())
        net = gross - cost
        qqq_return = float(benchmark.get(date, 0.0))
        nav.append(nav[-1] * (1 + net))
        qqq_nav.append(qqq_nav[-1] * (1 + qqq_return))
        turnover_total += turnover
        rows.append(
            {
                "period_index": index,
                "rebalance_date": date,
                "turnover": turnover,
                "cost": cost,
                "net_return": net,
                "benchmark_return": qqq_return,
                "nav": nav[-1],
            }
        )
        holdings = target
    result = {
        "strategy_id": "top15_equal_sector_cap_30pct",
        "cost_bps": cost_bps,
        "total_return": nav[-1] - 1,
        "benchmark_return": qqq_nav[-1] - 1,
        "excess_return": (nav[-1] - 1) - (qqq_nav[-1] - 1),
        "max_drawdown": phase_a._max_drawdown(nav),
        "turnover": turnover_total,
    }
    return result, pd.DataFrame(rows)


def _leave_one_sector_out(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    closes: pd.DataFrame,
    classification: pd.DataFrame,
    baseline: dict[str, Any],
    drawdown_rows: pd.DataFrame,
) -> pd.DataFrame:
    sectors = sorted(drawdown_rows["sector"].unique())
    rows = []
    for sector in sectors:
        excluded = set(classification.loc[classification["sector"] == sector, "symbol"])
        filtered = scores.loc[~scores["instrument"].isin(excluded)]
        result, _, _ = phase_a._evaluate(
            filtered,
            returns,
            benchmark,
            closes,
            phase_a.STRATEGIES[0],
            20,
        )
        rows.append(
            {
                "excluded_sector": sector,
                "total_return": result["total_return"],
                "excess_return": result["excess_return"],
                "max_drawdown": result["max_drawdown"],
                "drawdown_improvement": result["max_drawdown"] - baseline["max_drawdown"],
                "excess_change": result["excess_return"] - baseline["excess_return"],
            }
        )
    return pd.DataFrame(rows).sort_values("drawdown_improvement", ascending=False)


def _drawdown_phases(
    contributions: pd.DataFrame,
    periods: pd.DataFrame,
    drawdown: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    indices = [int(value) for value in drawdown["drawdown_period_indices"]]
    drawdown_periods = periods.loc[periods["period_index"].isin(indices)]
    shock_index = int(drawdown_periods.sort_values("net_return").iloc[0]["period_index"])
    tagged = contributions.loc[contributions["period_index"].isin(indices)].copy()
    tagged["phase"] = np.where(
        tagged["period_index"] < shock_index,
        "lead_in",
        np.where(tagged["period_index"] == shock_index, "initial_shock", "continuation"),
    )
    grouped = tagged.groupby(["window", "phase", "sector"], as_index=False)[
        "net_contribution"
    ].sum()
    shock_period = periods.loc[periods["period_index"] == shock_index].iloc[0]
    return grouped, {
        "initial_shock_period_index": shock_index,
        "initial_shock_date": pd.Timestamp(shock_period["rebalance_date"]).date().isoformat(),
        "initial_shock_return": float(shock_period["net_return"]),
    }


def _decision(
    drawdown_rows: pd.DataFrame,
    leave_one_sector: pd.DataFrame,
    sector_cap: dict[str, Any],
    baseline: dict[str, Any],
    coverage: dict[str, float] | None = None,
) -> dict[str, Any]:
    if coverage and min(coverage.values()) < 0.75:
        return {
            "decision": "data_blocked",
            "coverage_gate": False,
            "automatic_model_update": False,
            "creates_us_x1_2_candidate": False,
        }
    sector_loss = _negative_loss_share(drawdown_rows, "sector")
    style_losses = {
        dimension: _negative_loss_share(drawdown_rows, dimension)
        for dimension in STYLE_DIMENSIONS
    }
    best_leave_out = (
        float(leave_one_sector.iloc[0]["drawdown_improvement"])
        if not leave_one_sector.empty
        else 0.0
    )
    cap_improvement = float(sector_cap["max_drawdown"] - baseline["max_drawdown"])
    retained = (
        float(sector_cap["excess_return"] / baseline["excess_return"])
        if baseline["excess_return"] > 0
        else 0.0
    )
    sector_signal = (
        sector_loss["top_loss_share"] >= 0.50
        and (best_leave_out >= 0.04 or (cap_improvement >= 0.04 and retained >= 0.80))
    )
    style_signal = max(row["top_loss_share"] for row in style_losses.values()) >= 0.60
    regime_share = _negative_loss_share(drawdown_rows, "qqq_trend_state")["top_loss_share"]
    regime_signal = regime_share >= 0.60
    if sum((sector_signal, style_signal, regime_signal)) >= 2:
        decision = "mixed_sector_style_regime"
    elif sector_signal:
        decision = "sector_concentration_dominated"
    elif style_signal:
        decision = "market_style_exposure_dominated"
    else:
        decision = "broad_cross_sector_style_shock"
    return {
        "decision": decision,
        "coverage_gate": True,
        "sector_signal": sector_signal,
        "style_signal": style_signal,
        "regime_signal": regime_signal,
        "sector_loss": sector_loss,
        "style_losses": style_losses,
        "negative_regime_top_loss_share": regime_share,
        "best_leave_one_sector_drawdown_improvement": best_leave_out,
        "sector_cap_drawdown_improvement": cap_improvement,
        "sector_cap_retained_excess_ratio": retained,
        "automatic_model_update": False,
        "creates_us_x1_2_candidate": False,
    }


def _manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "evidence_manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {"schema_version": "1.0", "files": files}


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
    pool = load_pool_symbols(universe_path.resolve())
    classification, classification_manifest = load_sector_classification(
        classification_path.resolve(), pool
    )
    sector_by_symbol = classification.set_index("symbol")["sector"].to_dict()
    reproduction = json.loads(reproduction_result.read_text(encoding="utf-8"))
    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri.resolve())
    runtime.initialize(root)
    provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if provider != phase_a.EXPECTED_PROVIDER:
        raise ValueError(f"unexpected provider identity: {provider}")

    all_periods = []
    all_contributions = []
    all_styles = []
    all_exposure = []
    all_brinson = []
    alignment = []
    checks = []
    summaries = []
    cap_rows = []
    state: dict[str, dict[str, Any]] = {}

    for window in WINDOWS:
        source_path = score_ledger_root / window / "scores.csv"
        source = _load_scores(source_path, window)
        scores, score_check = _align_scores(
            runtime,
            source,
            window,
            output_dir / "aligned_inputs" / window / "economic_scores.csv",
        )
        alignment.append(score_check)
        start = pd.Timestamp(scores["datetime"].min())
        end = pd.Timestamp(scores["datetime"].max())
        returns, benchmark, closes, volumes = _market_data(runtime, pool, start, end)
        baseline, periods, contributions = phase_a._evaluate(
            scores, returns, benchmark, closes, phase_a.STRATEGIES[0], 20
        )
        expected = _expected(reproduction, window)
        _validate_baseline(baseline, expected, window)
        checks.append({"window": window, "status": "exact_within_1e-6"})
        periods.insert(0, "window", window)
        dates = [pd.Timestamp(value) for value in periods["rebalance_date"]]
        styles = _style_ledger(closes, volumes, dates, pool)
        styles.insert(0, "window", window)
        enriched = _enrich(contributions, classification, styles.drop(columns="window"), window)
        exposure = _sector_exposure(enriched)
        brinson = _brinson(enriched, returns, classification, pool)
        coverage = style_coverage(styles)
        summaries.append(
            {
                "window": window,
                "baseline": baseline,
                "style_coverage": coverage,
                "maximum_sector_weight": float(exposure["max_sector_weight"].max()),
                "mean_sector_hhi": float(
                    exposure.drop_duplicates(["window", "period_index"])["sector_hhi"].mean()
                ),
            }
        )
        for cost in phase_a.COST_STRESS_BPS:
            cap_result, cap_periods = _sector_cap_evaluate(
                scores, returns, benchmark, sector_by_symbol, cost
            )
            cap_result["window"] = window
            cap_rows.append(cap_result)
            if cost == 20:
                _write_csv(
                    output_dir / "ledgers" / window / "sector_cap_periods.csv",
                    cap_periods,
                )
        all_periods.append(periods)
        all_contributions.append(enriched)
        all_styles.append(styles)
        all_exposure.append(exposure)
        all_brinson.append(brinson)
        state[window] = {
            "scores": scores,
            "returns": returns,
            "benchmark": benchmark,
            "closes": closes,
            "baseline": baseline,
            "periods": periods.drop(columns="window"),
            "contributions": enriched,
            "coverage": coverage,
        }

    periods_all = pd.concat(all_periods, ignore_index=True)
    contributions_all = pd.concat(all_contributions, ignore_index=True)
    styles_all = pd.concat(all_styles, ignore_index=True)
    exposure_all = pd.concat(all_exposure, ignore_index=True)
    brinson_all = pd.concat(all_brinson, ignore_index=True)
    cap_frame = pd.DataFrame(cap_rows)

    h1 = state["2025H1"]
    drawdown = phase_a._drawdown_path(h1["periods"])
    indices = set(int(value) for value in drawdown["drawdown_period_indices"])
    drawdown_rows = h1["contributions"].loc[
        h1["contributions"]["period_index"].isin(indices)
    ].copy()
    phase_rows, shock = _drawdown_phases(h1["contributions"], h1["periods"], drawdown)
    leave_one = _leave_one_sector_out(
        h1["scores"],
        h1["returns"],
        h1["benchmark"],
        h1["closes"],
        classification,
        h1["baseline"],
        drawdown_rows,
    )
    cap_h1 = next(
        row
        for row in cap_rows
        if row["window"] == "2025H1" and row["cost_bps"] == 20
    )
    decision = _decision(
        drawdown_rows,
        leave_one,
        cap_h1,
        h1["baseline"],
        h1["coverage"],
    )
    exposure_h1 = exposure_all.loc[
        (exposure_all["window"] == "2025H1")
        & exposure_all["period_index"].isin(indices)
    ]
    mechanism = {
        "drawdown_path": drawdown,
        "shock_split": shock,
        "sector_loss": _negative_loss_share(drawdown_rows, "sector"),
        "industry_loss": _negative_loss_share(drawdown_rows, "industry"),
        "style_losses": {
            dimension: _negative_loss_share(drawdown_rows, dimension)
            for dimension in STYLE_DIMENSIONS
        },
        "mean_sector_hhi": float(
            exposure_h1.drop_duplicates(["window", "period_index"])["sector_hhi"].mean()
        ),
        "maximum_sector_weight": float(exposure_h1["max_sector_weight"].max()),
        "decision": decision,
    }

    _write_csv(output_dir / "ledgers" / "periods.csv", periods_all)
    _write_csv(output_dir / "ledgers" / "contributions_enriched.csv", contributions_all)
    _write_csv(output_dir / "ledgers" / "style_snapshots.csv", styles_all)
    _write_csv(output_dir / "ledgers" / "sector_exposure.csv", exposure_all)
    _write_csv(output_dir / "ledgers" / "brinson_attribution.csv", brinson_all)
    _write_csv(
        output_dir / "summaries" / "sector_contribution.csv",
        _group_contribution(contributions_all, "sector", "all_periods"),
    )
    _write_csv(
        output_dir / "summaries" / "industry_contribution.csv",
        _group_contribution(contributions_all, "industry", "all_periods"),
    )
    _write_csv(
        output_dir / "summaries" / "style_contribution.csv",
        _style_contribution(contributions_all, "all_periods"),
    )
    _write_csv(
        output_dir / "summaries" / "drawdown_sector_contribution.csv",
        _group_contribution(drawdown_rows, "sector", "2025H1_drawdown"),
    )
    _write_csv(
        output_dir / "summaries" / "drawdown_industry_contribution.csv",
        _group_contribution(drawdown_rows, "industry", "2025H1_drawdown"),
    )
    _write_csv(
        output_dir / "summaries" / "drawdown_style_contribution.csv",
        _style_contribution(drawdown_rows, "2025H1_drawdown"),
    )
    _write_csv(output_dir / "summaries" / "drawdown_phase_attribution.csv", phase_rows)
    _write_csv(output_dir / "summaries" / "leave_one_sector_out.csv", leave_one)
    _write_csv(output_dir / "summaries" / "sector_cap_sensitivity.csv", cap_frame)

    payload = {
        "schema_version": "1.0",
        "experiment_id": "us_x1_1_sector_style_attribution_v1",
        "issues": [366, 381],
        "parent_model_id": "us_x1_1",
        "pool_id": "us_selected_equities_v2",
        "pool_count": len(pool),
        "research_only": True,
        "trade_ready": False,
        "provider_identity_sha256": provider,
        "source_reproduction_artifact": 8831960659,
        "classification": {
            "manifest": classification_manifest,
            "data_identity_sha256": sha256_file(classification_path.resolve()),
        },
        "style_scope": {
            "kind": "point_in_time_market_derived",
            "dimensions": list(STYLE_DIMENSIONS),
            "excluded_claims": ["value", "growth", "quality", "fundamental_size"],
        },
        "score_alignment": alignment,
        "baseline_reproduction_checks": checks,
        "window_summaries": summaries,
        "sector_cap_sensitivity": cap_rows,
        "mechanism_2025H1": mechanism,
        "governance": {
            "pool_changed": False,
            "scores_changed": False,
            "features_changed": False,
            "label_changed": False,
            "model_parameters_changed": False,
            "uses_2026H1": False,
            "automatic_model_update": False,
            "creates_us_x1_2_candidate": False,
        },
    }
    _write_json(output_dir / "sector_style_attribution.json", payload)
    _write_json(output_dir / "evidence_manifest.json", _manifest(output_dir))
    return payload


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
        default=Path("configs/research_classifications/us87_sector_industry_v1.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_sector_style_attribution_v1"),
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
