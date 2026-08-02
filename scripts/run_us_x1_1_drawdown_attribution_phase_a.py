"""Attribute the deterministic US x1.1 2025H1 drawdown without model search.

Phase A consumes the frozen provider and Experiment 007 score ledger. It first
reproduces canonical non-overlapping 10-session economics, then attributes
name, volatility, beta and QQQ-regime contribution. Only independently
pre-registered portfolio controls are evaluated. Sector analysis is deferred to
Issue #366 and no online classification is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
EXPECTED_PROVIDER = "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
EXPECTED_SCORE_SHA256 = "3e4390f38615118ab3ae0218e0d4df7855a82654b829584db47520685b7b0301"
WINDOW = "2025H1"
REBALANCE_DAYS = 10
COST_STRESS_BPS = (20, 40, 60)
RECURRING_NAMES = ("AAOI", "AEHR", "BE", "IREN", "TYGO")


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    top_n: int
    weighting: str
    max_weight: float | None = None
    qqq_negative_trend_gross: float = 1.0


STRATEGIES = (
    StrategySpec("baseline_top15_equal", 15, "equal"),
    StrategySpec("top20_equal_weight", 20, "equal"),
    StrategySpec("top15_inverse_vol20_capped", 15, "inverse_volatility", 0.10),
    StrategySpec("top15_equal_weight_name_cap", 15, "equal", 0.08),
    StrategySpec(
        "top15_qqq_trend_overlay",
        15,
        "equal",
        qqq_negative_trend_gross=0.50,
    ),
)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return payload


def load_scores(path: Path) -> pd.DataFrame:
    if _sha256_file(path) != EXPECTED_SCORE_SHA256:
        raise ValueError("2025H1 score identity does not match Experiment 007")
    frame = pd.read_csv(path)
    required = ["datetime", "instrument", "score"]
    if list(frame.columns) != required:
        raise ValueError(f"score columns must be {required}")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if frame.duplicated(["datetime", "instrument"]).any():
        raise ValueError("score ledger contains duplicate rows")
    if not np.isfinite(frame["score"].to_numpy(dtype=float)).all():
        raise ValueError("score ledger contains non-finite values")
    return frame.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(
        drop=True
    )


def _rank_day(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.sort_values(
        ["score", "instrument"],
        ascending=[False, True],
        kind="mergesort",
    ).copy()
    ranked["rank"] = np.arange(1, len(ranked) + 1, dtype=int)
    return ranked


def _cap_weights(weights: pd.Series, cap: float) -> pd.Series:
    if not 0 < cap <= 1:
        raise ValueError("cap must be in (0, 1]")
    result = weights.astype(float).copy()
    for _ in range(len(result) + 2):
        over = result > cap + 1e-15
        if not over.any():
            break
        excess = float((result.loc[over] - cap).sum())
        result.loc[over] = cap
        under = result < cap - 1e-15
        capacity = cap - result.loc[under]
        if not under.any() or float(capacity.sum()) <= 0:
            break
        result.loc[under] += capacity / float(capacity.sum()) * excess
    if not math.isclose(float(result.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        result /= float(result.sum())
    if (result > cap + 1e-12).any():
        raise ValueError("weight cap could not be satisfied")
    return result


def _stats(
    closes: pd.DataFrame,
    date: pd.Timestamp,
    instruments: list[str],
) -> tuple[dict[str, float], dict[str, float], float]:
    history = closes.loc[closes.index < date].tail(61)
    if "QQQ" not in history or len(history) < 21:
        raise ValueError(f"insufficient QQQ history before {date.date()}")
    returns = history.pct_change(fill_method=None).dropna(how="all")
    qqq = returns["QQQ"].dropna().tail(20)
    qqq_var = float(qqq.var(ddof=1))
    volatility: dict[str, float] = {}
    beta: dict[str, float] = {}
    for instrument in instruments:
        series = returns[instrument].dropna().tail(20)
        volatility[instrument] = (
            float(series.std(ddof=1)) if len(series) >= 10 else float("nan")
        )
        aligned = pd.concat([series, qqq], axis=1, join="inner").dropna()
        beta[instrument] = (
            float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / qqq_var)
            if len(aligned) >= 10 and qqq_var > 1e-15
            else float("nan")
        )
    qqq_close = history["QQQ"].dropna()
    trend = float(qqq_close.iloc[-1] / qqq_close.iloc[-21] - 1.0)
    return volatility, beta, trend


def _buckets(values: pd.Series, prefix: str) -> pd.Series:
    ranks = values.rank(method="first", pct=True)
    result = pd.Series(index=values.index, dtype=object)
    result.loc[ranks <= 1 / 3] = f"low_{prefix}"
    result.loc[(ranks > 1 / 3) & (ranks <= 2 / 3)] = f"mid_{prefix}"
    result.loc[ranks > 2 / 3] = f"high_{prefix}"
    result.loc[values.isna()] = f"unknown_{prefix}"
    return result


def _weights(
    ranked: pd.DataFrame,
    spec: StrategySpec,
    volatility: dict[str, float],
    qqq_trend: float,
) -> pd.Series:
    names = ranked.head(spec.top_n)["instrument"].astype(str).tolist()
    if spec.weighting == "equal":
        result = pd.Series(1 / len(names), index=names, dtype=float)
    elif spec.weighting == "inverse_volatility":
        raw = pd.Series(
            {
                name: (
                    0.0
                    if not np.isfinite(volatility.get(name, float("nan")))
                    or volatility[name] <= 1e-12
                    else 1 / volatility[name]
                )
                for name in names
            },
            dtype=float,
        )
        result = (
            raw / float(raw.sum())
            if float(raw.sum()) > 0
            else pd.Series(1 / len(names), index=names, dtype=float)
        )
    else:
        raise ValueError(f"unsupported weighting: {spec.weighting}")
    if spec.max_weight is not None:
        result = _cap_weights(result, spec.max_weight)
    if qqq_trend < 0:
        result *= spec.qqq_negative_trend_gross
    return result


def _return_lookup(frame: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    rows: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in frame.reset_index().groupby("datetime", sort=True):
        rows[pd.Timestamp(date)] = {
            str(row["instrument"]): float(row["return"])
            for _, row in group.iterrows()
            if np.isfinite(float(row["return"]))
        }
    return rows


def _max_drawdown(nav: list[float]) -> float:
    values = np.asarray(nav, dtype=float)
    return float((values / np.maximum.accumulate(values) - 1).min())


def _effective_return_weights(
    target: dict[str, float],
    available_returns: dict[str, float],
) -> dict[str, float]:
    """Match canonical PortfolioIntent handling of missing forward returns.

    The target gross exposure is preserved, while names without a valid return
    are excluded and the remaining target weights are proportionally
    re-normalized. For the ordinary fully invested baseline this is exactly the
    legacy `valid_weight / total_valid_weight` rule.
    """

    gross_target = float(sum(target.values()))
    valid = {
        name: weight
        for name, weight in target.items()
        if name in available_returns and np.isfinite(available_returns[name])
    }
    valid_total = float(sum(valid.values()))
    if gross_target <= 0 or valid_total <= 0:
        return {}
    return {
        name: weight / valid_total * gross_target for name, weight in valid.items()
    }


def _evaluate(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    closes: pd.DataFrame,
    spec: StrategySpec,
    cost_bps: int,
    *,
    excluded_name: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())]
    rebalance_dates = dates[::REBALANCE_DAYS]
    holdings: dict[str, float] = {}
    nav = [1.0]
    benchmark_nav = [1.0]
    period_rows: list[dict[str, Any]] = []
    contribution_rows: list[dict[str, Any]] = []
    total_turnover = 0.0
    total_cost = 0.0

    for period_index, date in enumerate(rebalance_dates):
        daily = scores.loc[scores["datetime"] == date].copy()
        if excluded_name is not None:
            daily = daily.loc[daily["instrument"] != excluded_name]
        ranked = _rank_day(daily)
        initial_names = ranked.head(spec.top_n)["instrument"].astype(str).tolist()
        initial_vol, _, qqq_trend = _stats(closes, date, initial_names)
        target_series = _weights(ranked, spec, initial_vol, qqq_trend)
        target = {str(name): float(weight) for name, weight in target_series.items()}
        names = sorted(set(holdings) | set(target))
        deltas = {name: target.get(name, 0.0) - holdings.get(name, 0.0) for name in names}
        abs_delta = sum(abs(value) for value in deltas.values())
        turnover = abs_delta / 2
        cost = turnover * cost_bps / 10_000
        date_returns = returns.get(date, {})
        effective_weights = _effective_return_weights(target, date_returns)
        gross_return = sum(
            weight * date_returns[name] for name, weight in effective_weights.items()
        )
        net_return = gross_return - cost
        benchmark_return = float(benchmark.get(date, 0.0))
        nav.append(nav[-1] * (1 + net_return))
        benchmark_nav.append(benchmark_nav[-1] * (1 + benchmark_return))
        total_turnover += turnover
        total_cost += cost

        vol, beta, _ = _stats(closes, date, names)
        vol_bucket = _buckets(pd.Series(vol, dtype=float), "vol")
        beta_bucket = _buckets(pd.Series(beta, dtype=float), "beta")
        indexed_rank = ranked.set_index("instrument")
        for name in names:
            target_weight = target.get(name, 0.0)
            effective_weight = effective_weights.get(name, 0.0)
            has_valid_return = name in date_returns and np.isfinite(date_returns[name])
            forward_return = date_returns.get(name)
            gross_contribution = (
                effective_weight * float(forward_return)
                if has_valid_return and forward_return is not None
                else 0.0
            )
            allocated_cost = cost * abs(deltas[name]) / abs_delta if abs_delta > 0 else 0.0
            if target_weight <= 0:
                position_role = "exit_cost_only"
            elif not has_valid_return:
                position_role = "held_missing_return"
            else:
                position_role = "held_valid_return"
            contribution_rows.append(
                {
                    "period_index": period_index,
                    "rebalance_date": date,
                    "instrument": name,
                    "position_role": position_role,
                    "rank": (
                        int(indexed_rank.loc[name, "rank"])
                        if name in indexed_rank.index
                        else None
                    ),
                    "score": (
                        float(indexed_rank.loc[name, "score"])
                        if name in indexed_rank.index
                        else None
                    ),
                    "target_weight": target_weight,
                    "effective_return_weight": effective_weight,
                    "trade_delta": deltas[name],
                    "forward_10d_return": forward_return,
                    "gross_contribution": gross_contribution,
                    "allocated_cost": allocated_cost,
                    "net_contribution": gross_contribution - allocated_cost,
                    "vol20": vol.get(name),
                    "beta20_qqq": beta.get(name),
                    "vol_bucket": vol_bucket.get(name),
                    "beta_bucket": beta_bucket.get(name),
                    "qqq_trend20": qqq_trend,
                    "qqq_trend_state": "negative" if qqq_trend < 0 else "non_negative",
                    "benchmark_forward_10d_return": benchmark_return,
                }
            )
        period_rows.append(
            {
                "period_index": period_index,
                "rebalance_date": date,
                "gross_exposure": float(target_series.sum()),
                "valid_return_exposure_before_rescale": float(
                    sum(target.get(name, 0.0) for name in effective_weights)
                ),
                "missing_return_name_count": int(
                    sum(name not in effective_weights for name in target)
                ),
                "turnover": turnover,
                "cost": cost,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "nav": nav[-1],
                "benchmark_nav": benchmark_nav[-1],
                "qqq_trend20": qqq_trend,
                "qqq_trend_state": "negative" if qqq_trend < 0 else "non_negative",
            }
        )
        holdings = target

    periods = pd.DataFrame(period_rows)
    contributions = pd.DataFrame(contribution_rows)
    reconciliation = contributions.groupby("period_index")["net_contribution"].sum()
    expected = periods.set_index("period_index")["net_return"]
    if not np.allclose(
        reconciliation.reindex(expected.index).to_numpy(dtype=float),
        expected.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("name contribution ledger does not reconcile to period returns")
    total_return = nav[-1] - 1
    benchmark_return = benchmark_nav[-1] - 1
    return (
        {
            "strategy_id": spec.strategy_id,
            "cost_bps": cost_bps,
            "total_return": total_return,
            "benchmark_return": benchmark_return,
            "excess_return": total_return - benchmark_return,
            "max_drawdown": _max_drawdown(nav),
            "turnover": total_turnover,
            "costs": total_cost,
            "n_periods": len(periods),
            "positive_excess_periods": int((periods["excess_return"] > 0).sum()),
        },
        periods,
        contributions,
    )


def _drawdown_path(periods: pd.DataFrame) -> dict[str, Any]:
    nav = np.concatenate([[1.0], periods["nav"].to_numpy(dtype=float)])
    drawdowns = nav / np.maximum.accumulate(nav) - 1
    trough = int(np.argmin(drawdowns))
    peak = int(np.argmax(nav[: trough + 1]))
    recovery: int | None = None
    for index in range(trough + 1, len(nav)):
        if nav[index] >= nav[peak]:
            recovery = index
            break
    dates = [pd.Timestamp(value) for value in periods["rebalance_date"]]
    return {
        "peak_nav_position": peak,
        "trough_nav_position": trough,
        "peak_date": None if peak == 0 else dates[peak - 1].date().isoformat(),
        "trough_date": None if trough == 0 else dates[trough - 1].date().isoformat(),
        "recovery_date": (
            None if recovery is None or recovery == 0 else dates[recovery - 1].date().isoformat()
        ),
        "peak_nav": float(nav[peak]),
        "trough_nav": float(nav[trough]),
        "max_drawdown": float(drawdowns[trough]),
        "drawdown_period_indices": list(range(peak, trough)),
        "recovered_within_window": recovery is not None,
    }


def _attribution(contributions: pd.DataFrame, drawdown: dict[str, Any]) -> dict[str, Any]:
    subset = contributions.loc[
        contributions["period_index"].isin(drawdown["drawdown_period_indices"])
    ].copy()
    by_name = (
        subset.groupby("instrument", as_index=False)[
            ["gross_contribution", "allocated_cost", "net_contribution"]
        ]
        .sum()
        .sort_values("net_contribution")
    )
    losses = by_name.loc[by_name["net_contribution"] < 0]
    total_loss = float(-losses["net_contribution"].sum())
    top3_loss = float(-losses.head(3)["net_contribution"].sum())
    bucket_rows: dict[str, dict[str, float]] = {}
    for column in ("vol_bucket", "beta_bucket", "qqq_trend_state"):
        grouped = subset.groupby(column, dropna=False)["net_contribution"].sum()
        bucket_rows[column] = {str(key): float(value) for key, value in grouped.items()}
    negative_rows = subset.loc[subset["net_contribution"] < 0]
    all_negative = float(-negative_rows["net_contribution"].sum())
    negative_trend = float(
        -negative_rows.loc[
            negative_rows["qqq_trend_state"] == "negative", "net_contribution"
        ].sum()
    )
    return {
        "drawdown_selected_rows": len(subset),
        "top_negative_names": by_name.head(10).to_dict(orient="records"),
        "top_positive_names": by_name.tail(10)
        .sort_values("net_contribution", ascending=False)
        .to_dict(orient="records"),
        "all_name_contributions": by_name.to_dict(orient="records"),
        "top3_negative_name_loss_share": top3_loss / total_loss if total_loss else 0.0,
        "recurring_name_contribution": by_name.loc[
            by_name["instrument"].isin(RECURRING_NAMES)
        ].to_dict(orient="records"),
        "bucket_contribution": bucket_rows,
        "negative_trend_loss_share": negative_trend / all_negative if all_negative else 0.0,
    }


def _leave_one_out(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    closes: pd.DataFrame,
    baseline: dict[str, Any],
    drawdown_contributions: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(drawdown_contributions["instrument"].unique()):
        result, _, _ = _evaluate(
            scores,
            returns,
            benchmark,
            closes,
            STRATEGIES[0],
            20,
            excluded_name=name,
        )
        rows.append(
            {
                "excluded_name": name,
                "total_return": result["total_return"],
                "excess_return": result["excess_return"],
                "max_drawdown": result["max_drawdown"],
                "drawdown_improvement": result["max_drawdown"]
                - baseline["max_drawdown"],
                "excess_change": result["excess_return"] - baseline["excess_return"],
            }
        )
    return sorted(rows, key=lambda row: row["drawdown_improvement"], reverse=True)


def _decision(
    baseline: dict[str, Any],
    variants: list[dict[str, Any]],
    attribution: dict[str, Any],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    for row in variants:
        retained = (
            row["excess_return"] / baseline["excess_return"]
            if baseline["excess_return"] > 0
            else 0.0
        )
        gates.append(
            {
                "strategy_id": row["strategy_id"],
                "drawdown_improvement": row["max_drawdown"] - baseline["max_drawdown"],
                "retained_excess_ratio": retained,
                "supported": (
                    row["max_drawdown"] - baseline["max_drawdown"] >= 0.05
                    and retained >= 0.80
                ),
            }
        )
    overlay = next(
        row for row in gates if row["strategy_id"] == "top15_qqq_trend_overlay"
    )
    name_gate = (
        attribution["top3_negative_name_loss_share"] >= 0.50
        and bool(leave_one_out)
        and leave_one_out[0]["drawdown_improvement"] >= 0.04
    )
    regime_gate = (
        attribution["negative_trend_loss_share"] >= 0.60
        and overlay["drawdown_improvement"] >= 0.04
    )
    if name_gate and regime_gate:
        decision = "mixed_name_and_regime_drawdown"
    elif name_gate:
        decision = "drawdown_is_name_concentration_dominated"
    elif regime_gate:
        decision = "drawdown_is_regime_exposure_dominated"
    else:
        decision = "portfolio_control_path_supported"
    return {
        "decision": decision,
        "name_concentration_gate": name_gate,
        "regime_exposure_gate": regime_gate,
        "variant_gates": gates,
        "automatic_model_update": False,
        "creates_us_x1_2_candidate": False,
        "sector_phase_status": "deferred_pending_issue_366",
    }


def run(
    root: Path,
    provider_uri: Path,
    score_ledger: Path,
    reproduction_result: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    scores = load_scores(score_ledger.resolve())
    reproduction = _load_json(reproduction_result.resolve())
    expected = next(
        row for row in reproduction["run_a"]["windows"] if row["window"] == WINDOW
    )["cost_stress"]["20"]

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri.resolve())
    runtime.initialize(root)
    provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if provider != EXPECTED_PROVIDER:
        raise ValueError(f"unexpected provider identity: {provider}")
    symbols = sorted(scores["instrument"].unique())
    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())]
    start, end = dates[0], dates[-1]
    raw_returns = normalize_qlib_frame_index(
        runtime.features(
            symbols,
            [RETURN_EXPRESSION],
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    raw_returns.columns = ["return"]
    benchmark_frame = normalize_qlib_frame_index(
        runtime.features(
            ["QQQ"],
            [RETURN_EXPRESSION],
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    benchmark_frame.columns = ["return"]
    benchmark = {
        pd.Timestamp(date): float(group["return"].iloc[0])
        for date, group in benchmark_frame.reset_index().groupby("datetime")
    }
    close_frame = normalize_qlib_frame_index(
        runtime.features(
            [*symbols, "QQQ"],
            ["$close"],
            (start - pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    close_frame.columns = ["close"]
    closes = close_frame["close"].unstack(level="instrument").sort_index()
    returns = _return_lookup(raw_returns)

    results: dict[str, dict[str, Any]] = {}
    periods_by_strategy: dict[str, pd.DataFrame] = {}
    contributions_by_strategy: dict[str, pd.DataFrame] = {}
    for spec in STRATEGIES:
        cost_rows: dict[str, Any] = {}
        for cost in COST_STRESS_BPS:
            result, periods, contributions = _evaluate(
                scores, returns, benchmark, closes, spec, cost
            )
            cost_rows[str(cost)] = result
            if cost == 20:
                periods_by_strategy[spec.strategy_id] = periods
                contributions_by_strategy[spec.strategy_id] = contributions
                _write_csv(output_dir / "ledgers" / f"{spec.strategy_id}_periods.csv", periods)
                _write_csv(
                    output_dir / "ledgers" / f"{spec.strategy_id}_contributions.csv",
                    contributions,
                )
        results[spec.strategy_id] = {
            "contract": {
                "top_n": spec.top_n,
                "weighting": spec.weighting,
                "max_weight": spec.max_weight,
                "qqq_negative_trend_gross": spec.qqq_negative_trend_gross,
            },
            "cost_stress": cost_rows,
        }

    baseline = results["baseline_top15_equal"]["cost_stress"]["20"]
    for key in ("total_return", "benchmark_return", "excess_return", "max_drawdown", "turnover"):
        if not math.isclose(baseline[key], float(expected[key]), rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(
                f"baseline mismatch for {key}: observed={baseline[key]} expected={expected[key]}"
            )
    baseline_periods = periods_by_strategy["baseline_top15_equal"]
    baseline_contributions = contributions_by_strategy["baseline_top15_equal"]
    drawdown = _drawdown_path(baseline_periods)
    attribution = _attribution(baseline_contributions, drawdown)
    drawdown_rows = baseline_contributions.loc[
        baseline_contributions["period_index"].isin(drawdown["drawdown_period_indices"])
    ]
    leave_one_out = _leave_one_out(
        scores, returns, benchmark, closes, baseline, drawdown_rows
    )
    variants = [results[spec.strategy_id]["cost_stress"]["20"] for spec in STRATEGIES[1:]]
    decision = _decision(baseline, variants, attribution, leave_one_out)
    payload = {
        "schema_version": "1.0",
        "experiment_id": "us_x1_1_drawdown_attribution_phase_a_v1",
        "issue": 381,
        "parent_model_id": "us_x1_1",
        "window": WINDOW,
        "research_only": True,
        "trade_ready": False,
        "provider_identity_sha256": provider,
        "source_reproduction_artifact": 8831960659,
        "score_identity_sha256": EXPECTED_SCORE_SHA256,
        "baseline_reproduction_check": {
            "status": "exact_within_1e-6",
            "observed": baseline,
            "expected": expected,
        },
        "drawdown_path": drawdown,
        "contribution_attribution": attribution,
        "leave_one_name_out": leave_one_out,
        "strategy_results": results,
        "decision": decision,
        "governance": {
            "scores_changed": False,
            "model_parameters_changed": False,
            "sector_analysis": "deferred_pending_governed_map_issue_366",
            "sampling_challenger": "deferred_until_baseline_mechanism_is_recorded",
            "consumed_2026H1_used": False,
        },
    }
    _write_json(output_dir / "drawdown_attribution_phase_a.json", payload)
    _write_csv(output_dir / "leave_one_name_out.csv", pd.DataFrame(leave_one_out))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--score-ledger", type=Path, required=True)
    parser.add_argument("--reproduction-result", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_drawdown_attribution_phase_a_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        args.provider_uri,
        args.score_ledger,
        args.reproduction_result,
        args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
