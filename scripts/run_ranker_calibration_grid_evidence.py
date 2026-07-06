"""Generate rolling fixed-10D evidence for the ranker calibration grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import fit_lgbm_daily_ranker, predict_lgbm_daily_ranker
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import (
    RankerGridCandidate,
    build_ranker_calibration_grid,
    default_ranker_calibrations,
    default_ranker_feature_groups,
    grid_manifest,
)
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)
from src.research.walk_forward_stability import summarize_walk_forward_reports


def _load_session(root: Path) -> dict[str, object]:
    path = root / "data" / "session_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "market": "us",
        "symbols": ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "COST", "NFLX"],
        "benchmark": "QQQ",
        "train_start": "2021-01-01",
        "test_end": "2026-06-18",
        "topk": 3,
    }


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        return frame.swaplevel().sort_index()
    return frame.sort_index()


def _ordered_feature_expressions(candidates: list[RankerGridCandidate]) -> list[str]:
    return list(
        dict.fromkeys(
            expression
            for candidate in candidates
            for expression in candidate.feature_group.expressions
        )
    )


def _available_windows(
    data_provider: Any,
    session: dict[str, object],
    *,
    first_test_year: int,
    last_test_year: int,
) -> list[Any]:
    calendar = pd.DatetimeIndex(
        data_provider.calendar(
            start_time=str(session["train_start"]),
            end_time=str(session["test_end"]),
            freq="day",
        )
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in the configured session range")
    available_start = str(session["train_start"])
    available_end = min(pd.Timestamp(session["test_end"]), calendar.max()).strftime("%Y-%m-%d")
    windows = filter_windows_by_available_range(
        half_year_rolling_windows(
            start_year=int(str(session["train_start"])[:4]),
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        ),
        available_start=available_start,
        available_end=available_end,
    )
    if not windows:
        raise ValueError(
            "no complete rolling windows are covered by the available Qlib range "
            f"{available_start}..{available_end}"
        )
    return windows


def run(root: Path, *, first_test_year: int, last_test_year: int) -> dict[str, object]:
    session = _load_session(root)
    symbols = list(session["symbols"])
    if len(symbols) < 2:
        raise ValueError("ranker grid requires at least two symbols")
    requested_topk = int(session.get("topk", 3))
    if requested_topk <= 0:
        raise ValueError("topk must be positive")
    topk = min(requested_topk, len(symbols) - 1)
    market = str(session["market"])

    feature_groups = default_ranker_feature_groups()
    calibrations = default_ranker_calibrations()
    grid = build_ranker_calibration_grid(feature_groups, calibrations)
    manifest = grid_manifest(grid)
    feature_expressions = _ordered_feature_expressions(grid)
    expression_columns = {expression: sanitize_factor_name(expression) for expression in feature_expressions}
    if len(set(expression_columns.values())) != len(expression_columns):
        raise ValueError("sanitized ranker feature names must be unique")

    out_dir = root / "artifacts" / "evidence" / "ranker_calibration_grid"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "grid_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market=market,
            provider_uri_default=str(root / "data" / "watchlist"),
        )
    )
    from qlib.data import D

    windows = _available_windows(
        D,
        session,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    reports: list[dict[str, Any]] = []
    baseline_expression = "$close/Ref($close,10)-1"

    for window in windows:
        config = ResearchSessionConfig(
            market=market,
            symbols=symbols,
            benchmark=str(session["benchmark"]),
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            topk=topk,
            model_type="lgbm_lambdarank_grid",
            factor_expressions=feature_expressions,
            return_expression=CANONICAL_10D_RETURN_EXPR,
            experiment_id=f"{market}_ranker_grid_{window.label}",
        )
        features_all = D.features(
            symbols,
            feature_expressions,
            start_time=window.train_start,
            end_time=window.test_end,
        )
        raw_all = D.features(
            symbols,
            [config.return_expression],
            start_time=window.train_start,
            end_time=window.test_end,
        )
        features_all = _normalize_index(features_all).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[expression] for expression in feature_expressions]
        missing_expressions = [
            expression
            for expression, column in expression_columns.items()
            if features_all[column].notna().sum() == 0
        ]
        if missing_expressions:
            raise ValueError(f"ranker feature expressions produced no values: {missing_expressions}")
        features_all = features_all.fillna(0.0)
        raw_all = _normalize_index(raw_all)
        raw_all.columns = ["return"]
        raw_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": config.return_expression,
            }
        )

        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = (dates >= pd.Timestamp(window.test_start)) & (dates <= pd.Timestamp(window.test_end))
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            raw_all.loc[train_mask].copy(),
            holding_days=config.holding_days,
        )
        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_all.attrs)

        candidate_scores: dict[str, pd.DataFrame] = {}
        for candidate in grid:
            columns = [expression_columns[expression] for expression in candidate.feature_group.expressions]
            x_rank, y_rank, groups = prepare_ranker_frame(features_train.loc[:, columns], returns_train)
            fitted = fit_lgbm_daily_ranker(
                x_rank,
                y_rank,
                groups,
                n_gain_bins=candidate.calibration.n_gain_bins,
                params=candidate.calibration.params(),
                num_boost_round=candidate.calibration.num_boost_round,
            )
            candidate_scores[candidate.name] = predict_lgbm_daily_ranker(
                fitted,
                features_test.loc[:, columns],
            )

        baseline = D.features(
            symbols,
            [baseline_expression],
            start_time=window.test_start,
            end_time=window.test_end,
        )
        baseline = _normalize_index(baseline)
        baseline.columns = ["score"]
        baseline.attrs.update(
            {"provenance": "factor_baseline", "expression": baseline_expression}
        )
        candidate_scores["factor:historical_momentum_10d"] = baseline

        experiment = run_10d_experiment(
            config=config,
            candidates=candidate_scores,
            raw_returns=returns_test,
            output_dir=out_dir,
        )
        reports.append(experiment)

    summary = summarize_walk_forward_reports(reports, min_windows=3)
    summary_path = out_dir / "walk_forward_stability.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "windows": [window.to_dict() for window in windows],
        "grid_manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--first-test-year", type=int, default=2024)
    parser.add_argument("--last-test-year", type=int, default=2026)
    args = parser.parse_args()
    result = run(
        args.root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
