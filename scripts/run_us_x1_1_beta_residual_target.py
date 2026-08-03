"""Run the fixed-US87 QQQ beta-residual target experiment for US x1.1."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_us_x1_1_deterministic_reproduction import (
    COST_STRESS_BPS,
    EXPECTED_PROVIDER,
    _aggregate,
    _canonical_json_hash,
    _rank_ledger,
    _score_ledger,
    _selection_ledger,
    _write_json,
    _write_ledger,
)
from scripts.run_us_x1_1_native_xgb_grid import (
    BASELINE_ID,
    DECISION_WINDOWS,
    EXPERIMENT_CONFIG,
    MODEL_CONFIG,
    RETURN_EXPRESSION,
    UNIVERSE_CONFIG,
    _load_yaml,
    _native_calibrations,
    _resolve_symbols,
    _stress_result,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.relative_return_target import (
    benchmark_series_by_date,
    estimate_trailing_market_beta,
    make_beta_residual_forward_returns,
    make_naive_benchmark_excess_returns,
    prove_naive_rank_invariance,
)
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

EXPERIMENT_ID = "us_x1_1_beta_residual_target_v1"
DAILY_RETURN_EXPRESSION = "$close / Ref($close, 1) - 1"
BETA_LOOKBACK = 60
BETA_MIN_OBSERVATIONS = 40
BETA_MATERIAL_REDUCTION = 0.10
TOPK = 15
REBALANCE_DAYS = 10


def _finite_rows(frame: pd.DataFrame) -> pd.Series:
    return frame.replace([np.inf, -np.inf], np.nan).notna().all(axis=1)


def _frame_identity(frame: pd.DataFrame) -> str:
    output = frame.reset_index().copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    return _canonical_json_hash(
        {
            "columns": list(output.columns),
            "rows": [
                [
                    format(float(value), ".17g")
                    if isinstance(value, (float, np.floating))
                    else int(value)
                    if isinstance(value, (int, np.integer))
                    else str(value)
                    for value in row
                ]
                for row in output.itertuples(index=False, name=None)
            ],
        }
    )


def _cross_sectional_metrics(
    scores: pd.DataFrame,
    target_returns: pd.DataFrame,
) -> dict[str, float | int]:
    aligned = scores.join(target_returns, how="inner").replace(
        [np.inf, -np.inf], np.nan
    )
    aligned = aligned.dropna()
    pearson: list[float] = []
    spearman: list[float] = []
    for _, group in aligned.groupby(level="datetime", sort=True):
        if len(group) < 3:
            continue
        ic = group.iloc[:, 0].corr(group.iloc[:, 1], method="pearson")
        rank_ic = group.iloc[:, 0].corr(group.iloc[:, 1], method="spearman")
        if pd.notna(ic):
            pearson.append(float(ic))
        if pd.notna(rank_ic):
            spearman.append(float(rank_ic))
    ic_mean = float(np.mean(pearson)) if pearson else 0.0
    ic_std = float(np.std(pearson, ddof=1)) if len(pearson) > 1 else 0.0
    return {
        "n_dates": len(pearson),
        "ic": ic_mean,
        "icir": ic_mean / ic_std if ic_std > 0.0 else 0.0,
        "rank_ic": float(np.mean(spearman)) if spearman else 0.0,
    }


def _period_ledger(
    *,
    model_name: str,
    window: str,
    scores: pd.DataFrame,
    raw_returns: pd.DataFrame,
    benchmark: pd.DataFrame,
    beta_ledger: pd.DataFrame,
    cost_bps: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    score = scores.rename(columns={scores.columns[0]: "score"})
    returns = raw_returns.rename(columns={raw_returns.columns[0]: "raw_return"})
    aligned = score.join(returns, how="inner").join(
        beta_ledger[["beta"]], how="left"
    )
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()
    benchmark_by_date = benchmark_series_by_date(
        benchmark,
        name="benchmark_return",
    )
    dates = sorted(
        pd.Timestamp(value)
        for value in aligned.index.get_level_values("datetime").unique()
        if pd.Timestamp(value) in benchmark_by_date.index
    )
    rebalance_dates = dates[::REBALANCE_DAYS]
    previous_weights: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for period_index, date in enumerate(rebalance_dates, start=1):
        day = aligned.xs(date, level="datetime").reset_index()
        selected = day.sort_values(
            ["score", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).head(TOPK)
        if len(selected) != TOPK:
            raise ValueError(f"{window}/{model_name}: fewer than {TOPK} names")
        current_weights = {
            str(instrument): 1.0 / TOPK
            for instrument in selected["instrument"]
        }
        union = set(previous_weights) | set(current_weights)
        turnover = 0.5 * sum(
            abs(
                current_weights.get(instrument, 0.0)
                - previous_weights.get(instrument, 0.0)
            )
            for instrument in union
        )
        transaction_cost = turnover * cost_bps / 10000.0
        gross_return = float(selected["raw_return"].mean())
        net_return = gross_return - transaction_cost
        benchmark_return = float(benchmark_by_date.loc[date])
        periods.append(
            {
                "model": model_name,
                "window": window,
                "period_index": period_index,
                "datetime": date,
                "gross_return": gross_return,
                "transaction_cost": transaction_cost,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "simple_excess": net_return - benchmark_return,
                "turnover": turnover,
                "selected_beta": float(selected["beta"].mean()),
                "regime": "QQQ_UP" if benchmark_return >= 0.0 else "QQQ_DOWN",
            }
        )
        allocated_cost = transaction_cost / TOPK
        for row in selected.itertuples(index=False):
            holdings.append(
                {
                    "model": model_name,
                    "window": window,
                    "period_index": period_index,
                    "datetime": date,
                    "instrument": str(row.instrument),
                    "score": float(row.score),
                    "beta": float(row.beta),
                    "target_weight": 1.0 / TOPK,
                    "raw_return": float(row.raw_return),
                    "gross_contribution": float(row.raw_return) / TOPK,
                    "allocated_cost": allocated_cost,
                    "net_contribution": float(row.raw_return) / TOPK
                    - allocated_cost,
                }
            )
        previous_weights = current_weights
    return pd.DataFrame(periods), pd.DataFrame(holdings)


def _selection_comparison(
    baseline_ranks: pd.DataFrame,
    challenger_ranks: pd.DataFrame,
) -> dict[str, float | int]:
    merged = baseline_ranks.merge(
        challenger_ranks,
        on=["datetime", "instrument"],
        suffixes=("_baseline", "_challenger"),
        validate="one_to_one",
    )
    correlations = merged.groupby("datetime", sort=True).apply(
        lambda group: group["score_baseline"].corr(
            group["score_challenger"], method="spearman"
        ),
        include_groups=False,
    )
    dates = sorted(pd.Timestamp(value) for value in merged["datetime"].unique())
    rebalance_dates = dates[::REBALANCE_DAYS]
    overlaps: list[float] = []
    migrations: list[float] = []
    for date in rebalance_dates:
        day = merged.loc[merged["datetime"] == date]
        baseline_top = set(
            day.loc[day["rank_baseline"] <= TOPK, "instrument"].astype(str)
        )
        challenger_top = set(
            day.loc[day["rank_challenger"] <= TOPK, "instrument"].astype(str)
        )
        overlaps.append(len(baseline_top & challenger_top) / TOPK)
        migrations.append(
            float(
                np.mean(
                    np.abs(
                        day["rank_baseline"].to_numpy(dtype=float)
                        - day["rank_challenger"].to_numpy(dtype=float)
                    )
                )
            )
        )
    return {
        "n_rebalances": len(rebalance_dates),
        "mean_score_rank_correlation": float(correlations.dropna().mean()),
        "mean_top15_overlap": float(np.mean(overlaps)),
        "mean_absolute_rank_migration": float(np.mean(migrations)),
    }


def _compound(values: pd.Series | list[float]) -> float:
    return float(math.prod(1.0 + float(value) for value in values) - 1.0)


def _regime_summary(periods: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (model, regime), group in periods.groupby(["model", "regime"], sort=True):
        rows.append(
            {
                "model": str(model),
                "regime": str(regime),
                "n_periods": int(len(group)),
                "compounded_net_return": _compound(group["net_return"]),
                "compounded_benchmark_return": _compound(
                    group["benchmark_return"]
                ),
                "arithmetic_excess": float(group["simple_excess"].sum()),
                "mean_selected_beta": float(group["selected_beta"].mean()),
            }
        )
    return rows


def _security_attribution(holdings: pd.DataFrame) -> pd.DataFrame:
    return (
        holdings.groupby(["model", "instrument"], sort=True)
        .agg(
            periods_held=("period_index", "size"),
            mean_beta=("beta", "mean"),
            gross_contribution=("gross_contribution", "sum"),
            allocated_cost=("allocated_cost", "sum"),
            net_contribution=("net_contribution", "sum"),
        )
        .reset_index()
        .sort_values(["model", "net_contribution"], ascending=[True, False])
    )


def _leave_one_name_out(holdings: pd.DataFrame, periods: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, model_holdings in holdings.groupby("model", sort=True):
        model_periods = periods.loc[periods["model"] == model]
        for instrument in sorted(model_holdings["instrument"].unique()):
            counterfactual: list[float] = []
            for period in model_periods.itertuples(index=False):
                selected = model_holdings.loc[
                    (model_holdings["window"] == period.window)
                    & (model_holdings["period_index"] == period.period_index)
                    & (model_holdings["instrument"] != instrument)
                ]
                if selected.empty:
                    gross = float(period.gross_return)
                else:
                    gross = float(selected["raw_return"].mean())
                counterfactual.append(gross - float(period.transaction_cost))
            rows.append(
                {
                    "model": str(model),
                    "excluded_instrument": str(instrument),
                    "compounded_net_return": _compound(counterfactual),
                }
            )
    return pd.DataFrame(rows)


def _decision(
    *,
    baseline: dict[str, Any],
    challenger: dict[str, Any],
    periods: pd.DataFrame,
    comparison: dict[str, Any],
    naive_identity: bool,
    deterministic: bool,
) -> dict[str, Any]:
    baseline_down = periods.loc[
        (periods["model"] == "baseline") & (periods["regime"] == "QQQ_DOWN")
    ]
    challenger_down = periods.loc[
        (periods["model"] == "beta_residual")
        & (periods["regime"] == "QQQ_DOWN")
    ]
    baseline_down_return = _compound(baseline_down["net_return"])
    challenger_down_return = _compound(challenger_down["net_return"])
    down_improvement = (
        (challenger_down_return - baseline_down_return) / abs(baseline_down_return)
        if baseline_down_return < 0.0
        else 0.0
    )
    baseline_beta = float(
        periods.loc[periods["model"] == "baseline", "selected_beta"].mean()
    )
    challenger_beta = float(
        periods.loc[
            periods["model"] == "beta_residual", "selected_beta"
        ].mean()
    )
    beta_reduction = baseline_beta - challenger_beta
    baseline_20 = float(
        baseline["cost_stress"]["20"]["compounded_relative_excess_return"]
    )
    challenger_20 = float(
        challenger["cost_stress"]["20"]["compounded_relative_excess_return"]
    )
    alpha_retention = challenger_20 / baseline_20 if baseline_20 > 0.0 else 0.0
    drawdown_improvement = float(baseline["worst_drawdown"]) - float(
        challenger["worst_drawdown"]
    )
    gates = {
        "naive_rank_identity": naive_identity,
        "deterministic": deterministic,
        "four_positive_windows": challenger["positive_excess_windows"] == 4,
        "positive_60bps_relative_excess": float(
            challenger["cost_stress"]["60"][
                "compounded_relative_excess_return"
            ]
        )
        > 0.0,
        "retains_85pct_alpha": alpha_retention >= 0.85,
        "risk_improvement": drawdown_improvement >= 0.04
        or down_improvement >= 0.25,
        "window_share_below_55pct": float(
            challenger["strongest_positive_window_share"]
        )
        < 0.55,
        "selected_beta_reduction_at_least_0_10": beta_reduction
        >= BETA_MATERIAL_REDUCTION,
    }
    if not naive_identity or not deterministic:
        code = "data_blocked"
    elif all(gates.values()):
        code = "beta_residual_target_supported"
    elif (
        float(comparison["mean_top15_overlap"]) >= 0.995
        and float(comparison["mean_score_rank_correlation"]) >= 0.999
    ):
        code = "relative_label_is_rank_equivalent"
    elif gates["risk_improvement"] and gates[
        "selected_beta_reduction_at_least_0_10"
    ]:
        code = "beta_residual_reduces_risk_but_costs_too_much_alpha"
    else:
        code = "beta_residual_adds_no_value"
    return {
        "decision": code,
        "gates": gates,
        "baseline_qqq_down_return": baseline_down_return,
        "challenger_qqq_down_return": challenger_down_return,
        "qqq_down_loss_improvement_fraction": down_improvement,
        "baseline_mean_selected_beta": baseline_beta,
        "challenger_mean_selected_beta": challenger_beta,
        "selected_beta_reduction": beta_reduction,
        "alpha_retention_fraction": alpha_retention,
        "worst_drawdown_improvement": drawdown_improvement,
        "creates_x1_2_candidate": code == "beta_residual_target_supported",
        "automatic_promotion": False,
    }


def run(root: Path, *, provider_uri: Path, output_dir: Path) -> dict[str, Any]:
    root = root.resolve()
    provider_uri = provider_uri.resolve()
    output_dir = output_dir.resolve()
    model = _load_yaml(root / MODEL_CONFIG)
    experiment = _load_yaml(root / EXPERIMENT_CONFIG)
    universe = _load_yaml(root / UNIVERSE_CONFIG)
    calibration = dict(_native_calibrations(experiment))[BASELINE_ID]
    parameter_manifest = calibration.identity_manifest()
    features = [str(value) for value in model["features"]["expressions"]]

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if observed_provider != EXPECTED_PROVIDER:
        raise ValueError(
            f"unexpected provider {observed_provider}; expected {EXPECTED_PROVIDER}"
        )
    symbols = _resolve_symbols(runtime, universe)
    calendar = runtime.calendar("2020-01-01", "2025-12-31")
    available_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime(
        "%Y-%m-%d"
    )
    plan = build_window_sampling_plan(
        calendar,
        "2021-01-01",
        available_end,
        first_test_year=2024,
        last_test_year=2025,
        min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    windows = list(plan.selected_windows)
    if tuple(window.label for window in windows) != DECISION_WINDOWS:
        raise ValueError(f"unexpected windows: {[window.label for window in windows]}")
    eligible_dates = horizon_eligible_dates_by_window(plan, calendar)

    rows: dict[str, list[dict[str, Any]]] = {"baseline": [], "beta_residual": []}
    periods_all: list[pd.DataFrame] = []
    holdings_all: list[pd.DataFrame] = []
    comparisons: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    naive_checks: list[dict[str, Any]] = []

    history_start = calendar.min().strftime("%Y-%m-%d")
    daily_stock = normalize_qlib_frame_index(
        runtime.features(
            symbols,
            [DAILY_RETURN_EXPRESSION],
            history_start,
            available_end,
        )
    )
    daily_stock.columns = ["daily_return"]
    daily_qqq = normalize_qlib_frame_index(
        runtime.features(
            ["QQQ"],
            [DAILY_RETURN_EXPRESSION],
            history_start,
            available_end,
        )
    )
    daily_qqq.columns = ["daily_return"]
    beta_ledger = estimate_trailing_market_beta(
        daily_stock,
        daily_qqq,
        lookback_sessions=BETA_LOOKBACK,
        minimum_observations=BETA_MIN_OBSERVATIONS,
    )
    beta_export = beta_ledger.reset_index()
    _write_ledger(output_dir / "beta_ledger.csv", beta_export)

    for window in windows:
        dates = eligible_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, features, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{index}" for index in range(len(features))]
        returns_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        )
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": RETURN_EXPRESSION,
            }
        )
        benchmark_all = normalize_qlib_frame_index(
            runtime.features(
                ["QQQ"],
                [RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        )
        benchmark_all.columns = ["return"]
        benchmark_all.attrs.update(returns_all.attrs)
        all_dates = features_all.index.get_level_values("datetime")
        train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
            all_dates <= pd.Timestamp(window.train_end)
        )
        test_mask = all_dates.isin(dates)
        train_features, train_returns = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        valid, reason = validate_no_nan_inputs(
            train_features,
            context=f"US x1.1 beta residual/{window.label}",
        )
        if not valid:
            raise ValueError(reason)
        train_residual = make_beta_residual_forward_returns(
            train_returns,
            benchmark_all,
            beta_ledger,
        )
        residual_valid = _finite_rows(train_residual)
        train_features = train_features.loc[residual_valid]
        train_returns = train_returns.loc[residual_valid]
        train_residual = train_residual.loc[residual_valid]
        naive_check = prove_naive_rank_invariance(train_returns, benchmark_all)
        naive_check["window"] = window.label
        naive_checks.append(naive_check)

        x_residual, y_residual, residual_groups = prepare_ranker_frame(
            train_features,
            train_residual,
        )
        x_baseline, y_baseline, baseline_groups = prepare_ranker_frame(
            train_features,
            train_returns,
        )
        if not x_baseline.index.equals(x_residual.index):
            raise ValueError("baseline and residual training samples differ")
        if baseline_groups != residual_groups:
            raise ValueError("baseline and residual rank groups differ")

        test_features = features_all.loc[test_mask].copy()
        test_returns = returns_all.loc[test_mask].copy()
        test_returns.attrs.update(returns_all.attrs)
        test_residual = make_beta_residual_forward_returns(
            test_returns,
            benchmark_all,
            beta_ledger,
        )
        test_valid = _finite_rows(test_residual)
        test_features = test_features.loc[test_valid]
        test_returns = test_returns.loc[test_valid]
        test_residual = test_residual.loc[test_valid]
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument="QQQ",
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=dates,
            start=dates.min().strftime("%Y-%m-%d"),
            end=dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return",
            horizon=10,
        )

        fitted: dict[str, pd.DataFrame] = {}
        deterministic_hashes: dict[str, list[str]] = {
            "baseline": [],
            "beta_residual": [],
        }
        targets = {
            "baseline": (x_baseline, y_baseline, baseline_groups),
            "beta_residual": (x_residual, y_residual, residual_groups),
        }
        for model_name, (frame_x, frame_y, groups) in targets.items():
            first_scores: pd.DataFrame | None = None
            for repeat in ("a", "b"):
                model_fit = fit_xgb_native_daily_ranker(
                    frame_x,
                    frame_y,
                    groups,
                    calibration=calibration,
                )
                scores = predict_xgb_native_daily_ranker(
                    model_fit,
                    test_features,
                )
                score_ledger = _score_ledger(scores)
                score_hash = _frame_identity(score_ledger.set_index(
                    ["datetime", "instrument"]
                ))
                deterministic_hashes[model_name].append(score_hash)
                if repeat == "a":
                    first_scores = scores
                    ledger_root = output_dir / "ledgers" / model_name / window.label
                    ranks = _rank_ledger(score_ledger)
                    _write_ledger(ledger_root / "scores.csv", score_ledger)
                    _write_ledger(ledger_root / "ranks.csv", ranks)
                    _write_ledger(
                        ledger_root / "top15_selections.csv",
                        _selection_ledger(ranks),
                    )
            if first_scores is None:
                raise RuntimeError("model fit produced no scores")
            if len(set(deterministic_hashes[model_name])) != 1:
                raise ValueError(f"{window.label}/{model_name} is not deterministic")
            fitted[model_name] = first_scores

        baseline_ranks = _rank_ledger(_score_ledger(fitted["baseline"]))
        challenger_ranks = _rank_ledger(_score_ledger(fitted["beta_residual"]))
        comparison = _selection_comparison(baseline_ranks, challenger_ranks)
        comparison["window"] = window.label
        comparisons.append(comparison)

        for model_name, scores in fitted.items():
            cost_stress = {
                str(cost): _stress_result(
                    scores,
                    test_returns,
                    benchmark,
                    cost_bps=cost,
                )
                for cost in COST_STRESS_BPS
            }
            target_metrics = _cross_sectional_metrics(
                scores,
                test_returns if model_name == "baseline" else test_residual,
            )
            period_ledger, holding_ledger = _period_ledger(
                model_name=model_name,
                window=window.label,
                scores=scores,
                raw_returns=test_returns,
                benchmark=benchmark,
                beta_ledger=beta_ledger,
            )
            periods_all.append(period_ledger)
            holdings_all.append(holding_ledger)
            row = {
                "window": window.label,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "test_start": dates.min().strftime("%Y-%m-%d"),
                "test_end": dates.max().strftime("%Y-%m-%d"),
                "parameter_identity_sha256": parameter_manifest[
                    "identity_sha256"
                ],
                "training_rows": len(frame_x),
                "target_identity_sha256": _canonical_json_hash(
                    [format(float(value), ".17g") for value in frame_y]
                ),
                "score_identity_sha256": deterministic_hashes[model_name][0],
                "deterministic_repeat_match": True,
                "cost_stress": cost_stress,
                "target_metrics": target_metrics,
                "mean_selected_beta": float(
                    period_ledger["selected_beta"].mean()
                ),
            }
            rows[model_name].append(row)
        identity_rows.append(
            {
                "window": window.label,
                "baseline_target_sha256": rows["baseline"][-1][
                    "target_identity_sha256"
                ],
                "residual_target_sha256": rows["beta_residual"][-1][
                    "target_identity_sha256"
                ],
                "targets_differ": rows["baseline"][-1][
                    "target_identity_sha256"
                ]
                != rows["beta_residual"][-1]["target_identity_sha256"],
                "baseline_repeat_match": True,
                "residual_repeat_match": True,
            }
        )

    baseline_aggregate = _aggregate(rows["baseline"])
    challenger_aggregate = _aggregate(rows["beta_residual"])
    periods = pd.concat(periods_all, ignore_index=True)
    holdings = pd.concat(holdings_all, ignore_index=True)
    comparison_aggregate = {
        "mean_score_rank_correlation": float(
            np.mean([row["mean_score_rank_correlation"] for row in comparisons])
        ),
        "mean_top15_overlap": float(
            np.mean([row["mean_top15_overlap"] for row in comparisons])
        ),
        "mean_absolute_rank_migration": float(
            np.mean([row["mean_absolute_rank_migration"] for row in comparisons])
        ),
        "windows": comparisons,
    }
    deterministic = all(
        row["baseline_repeat_match"] and row["residual_repeat_match"]
        for row in identity_rows
    )
    naive_identity = all(bool(row["rank_identity"]) for row in naive_checks)
    decision = _decision(
        baseline=baseline_aggregate,
        challenger=challenger_aggregate,
        periods=periods,
        comparison=comparison_aggregate,
        naive_identity=naive_identity,
        deterministic=deterministic,
    )

    _write_ledger(output_dir / "periods.csv", periods)
    _write_ledger(output_dir / "holdings.csv", holdings)
    _write_ledger(
        output_dir / "security_attribution.csv",
        _security_attribution(holdings),
    )
    _write_ledger(
        output_dir / "leave_one_name_out.csv",
        _leave_one_name_out(holdings, periods),
    )
    _write_json(
        output_dir / "beta_residual_target_experiment.json",
        {
            "schema_version": "1.0",
            "experiment_id": EXPERIMENT_ID,
            "issue": 422,
            "parent_model_id": "us_x1_1",
            "research_only": True,
            "trade_ready": False,
            "fixed_pool": {
                "universe_id": "us_selected_equities_v2",
                "candidate_count": len(symbols),
                "pool_external_claim": False,
            },
            "provider": {
                "observed_identity_sha256": observed_provider,
                "expected_identity_sha256": EXPECTED_PROVIDER,
                "matches_expected": observed_provider == EXPECTED_PROVIDER,
            },
            "parameter_identity": parameter_manifest,
            "target_contract": {
                "daily_return_expression": DAILY_RETURN_EXPRESSION,
                "forward_return_expression": RETURN_EXPRESSION,
                "beta_lookback_sessions": BETA_LOOKBACK,
                "beta_minimum_observations": BETA_MIN_OBSERVATIONS,
                "material_beta_reduction": BETA_MATERIAL_REDUCTION,
                "beta_clipping": False,
            },
            "naive_rank_invariance": naive_checks,
            "identity_checks": identity_rows,
            "baseline": baseline_aggregate,
            "beta_residual": challenger_aggregate,
            "selection_comparison": comparison_aggregate,
            "regime_attribution": _regime_summary(periods),
            "decision": decision,
            "automatic_model_update": False,
        },
    )
    return {
        "decision": decision,
        "baseline": baseline_aggregate,
        "beta_residual": challenger_aggregate,
        "selection_comparison": comparison_aggregate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_beta_residual_target_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
