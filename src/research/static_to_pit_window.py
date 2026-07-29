"""Per-window four-cell execution for static-to-PIT diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    fit_xgb_daily_ranker,
    percentile_rank_to_gain,
    predict_lgbm_daily_ranker,
    predict_xgb_daily_ranker,
)
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.ndx_window_start_universe import (
    filter_training_by_asof_membership,
)
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.qlib_execution_common import (
    ExecutionRuntime,
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.rolling_windows import RollingResearchWindow, purge_training_tail
from src.research.static_to_pit_contract import build_four_cell_matrix
from src.research.static_to_pit_diagnostics import (
    contribution_gap,
    score_rank_migration,
    selected_return_contributions,
    selection_overlap,
    symbol_membership_categories,
    topk_selections,
)
from src.research.static_to_pit_effects import (
    extract_original_candidate_metrics,
    four_cell_effects,
)
from src.research.universe_robustness import validate_no_nan_inputs


@dataclass(frozen=True)
class WindowExecutionContext:
    """Immutable inputs for one observed half-year window."""

    market: str
    benchmark: str
    benchmark_instrument: str
    experiment_id: str
    feature_expressions: tuple[str, ...]
    expression_columns: dict[str, str]
    return_expression: str
    return_provenance: str
    top_n: int
    holding_days: int
    rebalance_days: int
    static_symbols: tuple[str, ...]
    pit_train_symbols: tuple[str, ...]
    pit_oos_symbols: tuple[str, ...]
    latest_snapshot_symbols: tuple[str, ...]
    first_snapshot_by_symbol: dict[str, str]
    window_snapshot_date: str
    aligned_train_start: str
    candidates: tuple[Any, ...]
    baseline_factors: dict[str, str]
    snapshot: Any
    provider_symbols: set[str]
    output_dir: Path


def _subset(frame: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    allowed = set(map(str, symbols))
    instruments = frame.index.get_level_values("instrument")
    result = frame.loc[instruments.isin(allowed)].copy()
    result.attrs.update(frame.attrs)
    return result


def _prepare_training(
    features: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    start: str,
    end: str,
    symbols: Sequence[str],
    holding_days: int,
    pit_snapshot: Any | None,
    provider_symbols: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = features.index.get_level_values("datetime")
    instruments = features.index.get_level_values("instrument")
    mask = (
        (dates >= pd.Timestamp(start))
        & (dates <= pd.Timestamp(end))
        & instruments.isin(set(map(str, symbols)))
    )
    feature_raw = features.loc[mask].copy()
    return_raw = returns.loc[mask].copy()
    return_raw.attrs.update(returns.attrs)

    if pit_snapshot is not None:
        feature_raw = filter_training_by_asof_membership(
            feature_raw,
            pit_snapshot,
            provider_symbols,
        )
        return_raw = filter_training_by_asof_membership(
            return_raw,
            pit_snapshot,
            provider_symbols,
        )
        return_raw.attrs.update(returns.attrs)

    feature_train, return_train = purge_training_tail(
        feature_raw,
        return_raw,
        holding_days=holding_days,
    )
    return_train.attrs.update(returns.attrs)
    valid, reason = validate_no_nan_inputs(
        feature_train,
        context="static-to-PIT decomposition training frame",
    )
    if not valid:
        raise ValueError(reason)

    prepared_x, prepared_y, _ = prepare_ranker_frame(
        feature_train,
        return_train,
    )
    gains = percentile_rank_to_gain(prepared_y, n_bins=5).to_frame("gain")
    return feature_train, return_train, gains


def _fit_model(
    candidate: Any,
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    expression_columns: dict[str, str],
) -> Any:
    columns = [
        expression_columns[item]
        for item in candidate.feature_group.expressions
    ]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, columns],
        returns_train,
    )
    if candidate.model_family == "xgb":
        return fit_xgb_daily_ranker(
            x_rank,
            y_rank,
            groups,
            n_gain_bins=candidate.calibration.n_gain_bins,
            params=None,
            num_boost_round=candidate.calibration.num_boost_round,
        )
    return fit_lgbm_daily_ranker(
        x_rank,
        y_rank,
        groups,
        n_gain_bins=candidate.calibration.n_gain_bins,
        params=candidate.calibration.params(),
        num_boost_round=candidate.calibration.num_boost_round,
    )


def _predict_model(
    candidate: Any,
    model: Any,
    features_test: pd.DataFrame,
    expression_columns: dict[str, str],
) -> pd.DataFrame:
    columns = [
        expression_columns[item]
        for item in candidate.feature_group.expressions
    ]
    matrix = features_test.loc[:, columns]
    if candidate.model_family == "xgb":
        return predict_xgb_daily_ranker(model, matrix)
    return predict_lgbm_daily_ranker(model, matrix)


def _run_cell(
    *,
    context: WindowExecutionContext,
    window: RollingResearchWindow,
    cell_id: str,
    candidate_scores: dict[str, pd.DataFrame],
    raw_returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    symbols: Sequence[str],
    evaluation_start: str,
    evaluation_end: str,
) -> dict[str, Any]:
    config = SpecBoundEvaluationContext(
        market=context.market,
        symbols=tuple(map(str, symbols)),
        benchmark=context.benchmark,
        train_start=context.aligned_train_start,
        train_end=window.train_end,
        test_start=evaluation_start,
        test_end=evaluation_end,
        holding_days=context.holding_days,
        rebalance_days=context.rebalance_days,
        topk=context.top_n,
        model_type="static_to_pit_diagnostic_ranker",
        factor_expressions=context.feature_expressions,
        return_expression=context.return_expression,
        experiment_id=(
            f"{context.experiment_id}_{window.label}_"
            f"{cell_id.replace('/', '').lower()}"
        ),
    )
    return run_10d_experiment(
        config=config,
        candidates=candidate_scores,
        raw_returns=raw_returns,
        benchmark_returns=benchmark_returns,
        output_dir=(
            context.output_dir / window.label / cell_id.replace("/", "")
        ),
    )


def _direct_gain_migration(
    static_gains: pd.DataFrame,
    pit_gains: pd.DataFrame,
) -> dict[str, Any]:
    common = static_gains.index.intersection(pit_gains.index)
    left = static_gains.loc[common, "gain"]
    right = pit_gains.loc[common, "gain"]
    matrix = (
        pd.DataFrame({"static_gain": left, "pit_gain": right})
        .groupby(["static_gain", "pit_gain"], sort=True)
        .size()
        .rename("count")
        .reset_index()
    )
    changed = left != right
    return {
        "common_rows": int(len(common)),
        "changed_rows": int(changed.sum()),
        "changed_ratio": float(changed.mean()) if len(common) else None,
        "mean_absolute_gain_shift": (
            float((right - left).abs().mean()) if len(common) else None
        ),
        "confusion": [
            {
                "static_gain": int(row.static_gain),
                "pit_gain": int(row.pit_gain),
                "count": int(row.count),
            }
            for row in matrix.itertuples(index=False)
        ],
    }


def _common_intersection_report(
    *,
    context: WindowExecutionContext,
    window: RollingResearchWindow,
    candidate: Any,
    ss_scores: pd.DataFrame,
    pp_scores: pd.DataFrame,
    static_returns: pd.DataFrame,
    pit_returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    common_symbols: Sequence[str],
    evaluation_start: str,
    evaluation_end: str,
) -> dict[str, Any]:
    if len(common_symbols) <= context.top_n:
        return {
            "skipped": True,
            "reason": (
                f"common intersection has {len(common_symbols)} symbols, "
                f"insufficient for Top-{context.top_n}"
            ),
        }
    candidate_name = candidate.name
    common_static_returns = _subset(static_returns, common_symbols)
    common_pit_returns = _subset(pit_returns, common_symbols)
    return {
        "S/S": _run_cell(
            context=context,
            window=window,
            cell_id=f"common_{candidate.model_family}_SS",
            candidate_scores={
                candidate_name: _subset(ss_scores, common_symbols)
            },
            raw_returns=common_static_returns,
            benchmark_returns=benchmark_returns,
            symbols=common_symbols,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        ),
        "P/P": _run_cell(
            context=context,
            window=window,
            cell_id=f"common_{candidate.model_family}_PP",
            candidate_scores={
                candidate_name: _subset(pp_scores, common_symbols)
            },
            raw_returns=common_pit_returns,
            benchmark_returns=benchmark_returns,
            symbols=common_symbols,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        ),
    }


def execute_decomposition_window(
    *,
    runtime: ExecutionRuntime,
    context: WindowExecutionContext,
    window: RollingResearchWindow,
    evaluation_dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    """Train two frozen model sets, cross-score four cells and attribute gaps."""

    union_symbols = sorted(
        set(context.static_symbols)
        | set(context.pit_train_symbols)
        | set(context.pit_oos_symbols)
    )
    missing = sorted(set(union_symbols) - context.provider_symbols)
    if missing:
        raise ValueError(
            f"provider misses {len(missing)} decomposition symbols: {missing}"
        )

    evaluation_start = evaluation_dates.min().strftime("%Y-%m-%d")
    evaluation_end = evaluation_dates.max().strftime("%Y-%m-%d")
    features = normalize_qlib_frame_index(
        runtime.features(
            union_symbols,
            context.feature_expressions,
            context.aligned_train_start,
            window.test_end,
        )
    ).replace([np.inf, -np.inf], np.nan)
    features.columns = [
        context.expression_columns[item]
        for item in context.feature_expressions
    ]

    returns = normalize_qlib_frame_index(
        runtime.features(
            union_symbols,
            [context.return_expression],
            context.aligned_train_start,
            window.test_end,
        )
    )
    returns.columns = ["return"]
    returns.attrs.update(
        {
            "provenance": context.return_provenance,
            "horizon": context.holding_days,
            "expression": context.return_expression,
        }
    )

    static_x, static_y, static_gains = _prepare_training(
        features,
        returns,
        start=context.aligned_train_start,
        end=window.train_end,
        symbols=context.static_symbols,
        holding_days=context.holding_days,
        pit_snapshot=None,
        provider_symbols=context.provider_symbols,
    )
    pit_x, pit_y, pit_gains = _prepare_training(
        features,
        returns,
        start=context.aligned_train_start,
        end=window.train_end,
        symbols=context.pit_train_symbols,
        holding_days=context.holding_days,
        pit_snapshot=context.snapshot,
        provider_symbols=context.provider_symbols,
    )

    test_mask = features.index.get_level_values("datetime").isin(
        evaluation_dates
    )
    test_features = features.loc[test_mask].copy()
    static_test = _subset(test_features, context.static_symbols)
    pit_test = _subset(test_features, context.pit_oos_symbols)

    return_mask = returns.index.get_level_values("datetime").isin(
        evaluation_dates
    )
    test_returns = returns.loc[return_mask].copy()
    test_returns.attrs.update(returns.attrs)
    static_returns = _subset(test_returns, context.static_symbols)
    pit_returns = _subset(test_returns, context.pit_oos_symbols)

    benchmark_returns = load_window_benchmark_returns(
        runtime,
        benchmark_instrument=context.benchmark_instrument,
        return_expression=context.return_expression,
        evaluation_dates=evaluation_dates,
        start=evaluation_start,
        end=evaluation_end,
        provenance=context.return_provenance,
        horizon=context.holding_days,
    )

    scores: dict[str, dict[str, pd.DataFrame]] = {
        cell.cell_id: {} for cell in build_four_cell_matrix()
    }
    for candidate in context.candidates:
        static_model = _fit_model(
            candidate,
            static_x,
            static_y,
            context.expression_columns,
        )
        pit_model = _fit_model(
            candidate,
            pit_x,
            pit_y,
            context.expression_columns,
        )
        scores["S/S"][candidate.name] = _predict_model(
            candidate,
            static_model,
            static_test,
            context.expression_columns,
        )
        scores["S/P"][candidate.name] = _predict_model(
            candidate,
            static_model,
            pit_test,
            context.expression_columns,
        )
        scores["P/S"][candidate.name] = _predict_model(
            candidate,
            pit_model,
            static_test,
            context.expression_columns,
        )
        scores["P/P"][candidate.name] = _predict_model(
            candidate,
            pit_model,
            pit_test,
            context.expression_columns,
        )

    for name, expression in context.baseline_factors.items():
        baseline = normalize_qlib_frame_index(
            runtime.features(
                union_symbols,
                [expression],
                evaluation_start,
                evaluation_end,
            )
        )
        baseline = baseline.loc[
            baseline.index.get_level_values("datetime").isin(evaluation_dates)
        ].copy()
        baseline.columns = ["score"]
        baseline.attrs.update(
            {"provenance": "factor_baseline", "expression": expression}
        )
        static_baseline = _subset(baseline, context.static_symbols)
        pit_baseline = _subset(baseline, context.pit_oos_symbols)
        scores["S/S"][name] = static_baseline
        scores["P/S"][name] = static_baseline.copy()
        scores["S/P"][name] = pit_baseline
        scores["P/P"][name] = pit_baseline.copy()

    reports: dict[str, dict[str, Any]] = {}
    for cell in build_four_cell_matrix():
        static_oos = cell.oos_membership == "static_curated"
        reports[cell.cell_id] = _run_cell(
            context=context,
            window=window,
            cell_id=cell.cell_id,
            candidate_scores=scores[cell.cell_id],
            raw_returns=static_returns if static_oos else pit_returns,
            benchmark_returns=benchmark_returns,
            symbols=(
                context.static_symbols
                if static_oos
                else context.pit_oos_symbols
            ),
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        )

    categories = symbol_membership_categories(
        static_symbols=context.static_symbols,
        pit_symbols=context.pit_oos_symbols,
        latest_snapshot_symbols=context.latest_snapshot_symbols,
        first_snapshot_by_symbol=context.first_snapshot_by_symbol,
        window_snapshot_date=context.window_snapshot_date,
    )
    common_symbols = sorted(
        set(context.static_symbols).intersection(context.pit_oos_symbols)
    )
    diagnostics: dict[str, Any] = {}
    for candidate in context.candidates:
        ss_scores = scores["S/S"][candidate.name]
        pp_scores = scores["P/P"][candidate.name]
        ss_selections = topk_selections(
            ss_scores,
            top_n=context.top_n,
            rebalance_days=context.rebalance_days,
            allowed_symbols=context.static_symbols,
        )
        pp_selections = topk_selections(
            pp_scores,
            top_n=context.top_n,
            rebalance_days=context.rebalance_days,
            allowed_symbols=context.pit_oos_symbols,
        )
        ss_contributions = selected_return_contributions(
            ss_scores,
            static_returns,
            categories=categories,
            top_n=context.top_n,
            rebalance_days=context.rebalance_days,
            allowed_symbols=context.static_symbols,
        )
        pp_contributions = selected_return_contributions(
            pp_scores,
            pit_returns,
            categories=categories,
            top_n=context.top_n,
            rebalance_days=context.rebalance_days,
            allowed_symbols=context.pit_oos_symbols,
        )
        diagnostics[candidate.name] = {
            "selection_overlap": selection_overlap(
                ss_selections,
                pp_selections,
            ),
            "score_rank_migration": score_rank_migration(
                _subset(ss_scores, common_symbols),
                _subset(pp_scores, common_symbols),
            ),
            "S/S_contributions": ss_contributions,
            "P/P_contributions": pp_contributions,
            "static_minus_pit_contribution_gap": contribution_gap(
                ss_contributions,
                pp_contributions,
            ),
            "common_intersection": _common_intersection_report(
                context=context,
                window=window,
                candidate=candidate,
                ss_scores=ss_scores,
                pp_scores=pp_scores,
                static_returns=static_returns,
                pit_returns=pit_returns,
                benchmark_returns=benchmark_returns,
                common_symbols=common_symbols,
                evaluation_start=evaluation_start,
                evaluation_end=evaluation_end,
            ),
        }

    metrics = {
        cell_id: extract_original_candidate_metrics(report)
        for cell_id, report in reports.items()
    }
    return {
        "schema_version": "1.0",
        "window": window.to_dict(),
        "snapshot_date": context.window_snapshot_date,
        "static_symbol_count": len(context.static_symbols),
        "pit_train_symbol_count": len(context.pit_train_symbols),
        "pit_oos_symbol_count": len(context.pit_oos_symbols),
        "common_oos_symbol_count": len(common_symbols),
        "categories": categories,
        "cell_reports": reports,
        "four_cell_effects": four_cell_effects(metrics),
        "label_bin_migration": _direct_gain_migration(
            static_gains,
            pit_gains,
        ),
        "candidate_diagnostics": diagnostics,
    }
