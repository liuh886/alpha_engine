"""Generate diagnostic rolling evidence for stable signal-blend candidates.

This historical experiment retains its two selected rankers and fixed blend
weights for robustness diagnosis. It is not a lifecycle-promotion path; only a
spec-bound run with execution identity may produce PromotionDecision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import (
    CANONICAL_10D_RETURN_EXPR,
    ResearchSessionConfig,
)
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import build_ranker_calibration_grid
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)
from src.research.stable_signal_blend import (
    build_blend_candidates,
    default_blend_weights,
)
from src.research.walk_forward_stability import summarize_walk_forward_reports

TARGET_RANKER_NAMES = {
    "lgbm:daily_ranker:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05",
    "lgbm:daily_ranker:momentum_volatility:gain5_round100_leaves31_leaf10_lr0.05",
}
MIN_STABILITY_WINDOWS = 3


def _load_session(root: Path) -> dict[str, object]:
    path = root / "data" / "session_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "market": "us",
        "symbols": [
            "AAPL",
            "NVDA",
            "MSFT",
            "GOOGL",
            "AMZN",
            "META",
            "TSLA",
            "AVGO",
            "COST",
            "NFLX",
        ],
        "benchmark": "QQQ",
        "train_start": "2021-01-01",
        "test_end": "2026-06-18",
        "topk": 3,
    }


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        frame = frame.swaplevel().sort_index()
    return frame.sort_index()


def _selected_ranker_grid():
    candidates = {
        candidate.name: candidate
        for candidate in build_ranker_calibration_grid()
    }
    missing = TARGET_RANKER_NAMES - set(candidates)
    if missing:
        raise ValueError(
            f"target ranker grid candidates missing: {sorted(missing)}"
        )
    return [candidates[name] for name in sorted(TARGET_RANKER_NAMES)]


def _unique_expressions(candidates) -> list[str]:
    seen: set[str] = set()
    expressions: list[str] = []
    for candidate in candidates:
        for expression in candidate.feature_group.expressions:
            if expression not in seen:
                seen.add(expression)
                expressions.append(expression)
    return expressions


def _complete_prediction_rows(
    features: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """Return only rows with complete finite features for prediction."""

    return (
        features.loc[:, columns]
        .replace([np.inf, -np.inf], np.nan)
        .dropna(axis=0, how="any")
        .sort_index()
    )


def _mark_experiment_diagnostic(experiment: dict[str, object]) -> None:
    experiment.update(
        {
            "diagnostic_only": True,
            "research_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
            "lifecycle_promotion": "not_evaluated",
        }
    )
    artifact_path = experiment.get("artifact_path")
    if artifact_path:
        Path(str(artifact_path)).write_text(
            json.dumps(experiment, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )


def run(
    root: Path,
    *,
    first_test_year: int,
    last_test_year: int,
) -> dict[str, object]:
    session = _load_session(root)
    market = str(session["market"])
    symbols = list(session["symbols"])
    if len(symbols) < 2:
        raise ValueError("stable signal blend requires at least two symbols")
    requested_topk = int(session.get("topk", 3))
    if requested_topk <= 0:
        raise ValueError("topk must be positive")
    topk = min(requested_topk, len(symbols) - 1)
    ranker_grid = _selected_ranker_grid()
    feature_exprs = _unique_expressions(ranker_grid)
    expression_columns = {
        expression: sanitize_factor_name(expression)
        for expression in feature_exprs
    }
    dollar = chr(36)
    baseline_expr = f"{dollar}close/Ref({dollar}close,10)-1"

    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market=market,
            provider_uri_default=str(root / "data" / "watchlist"),
        )
    )
    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(
            start_time=str(session["train_start"]),
            end_time=str(session["test_end"]),
            freq="day",
        )
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in the configured session range")
    available_end = min(
        pd.Timestamp(session["test_end"]), calendar.max()
    ).strftime("%Y-%m-%d")
    windows = filter_windows_by_available_range(
        half_year_rolling_windows(
            start_year=int(str(session["train_start"])[:4]),
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        ),
        available_start=str(session["train_start"]),
        available_end=available_end,
    )
    if not windows:
        raise ValueError(
            "no complete rolling windows are covered by the available Qlib range"
        )

    out_dir = root / "artifacts" / "evidence" / "stable_signal_blend"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
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
            model_type="stable_signal_blend_diagnostic",
            experiment_id=f"{market}_stable_blend_{window.label}",
            return_expression=CANONICAL_10D_RETURN_EXPR,
        )
        features_all = D.features(
            symbols,
            feature_exprs,
            start_time=window.train_start,
            end_time=window.test_end,
        )
        raw_all = D.features(
            symbols,
            [config.return_expression],
            start_time=window.train_start,
            end_time=window.test_end,
        )
        features_all = _normalize_index(features_all).replace(
            [np.inf, -np.inf], np.nan
        )
        features_all.columns = [
            expression_columns[expression] for expression in feature_exprs
        ]
        missing_expressions = [
            expression
            for expression, column in expression_columns.items()
            if features_all[column].notna().sum() == 0
        ]
        if missing_expressions:
            raise ValueError(
                "ranker feature expressions produced no values: "
                f"{missing_expressions}"
            )

        raw_all = _normalize_index(raw_all)
        raw_all.columns = ["return"]
        raw_all.attrs["provenance"] = "raw_forward_return"
        raw_all.attrs["horizon"] = 10
        raw_all.attrs["expression"] = config.return_expression

        dates = features_all.index.get_level_values("datetime")
        train_mask = (
            (dates >= pd.Timestamp(window.train_start))
            & (dates <= pd.Timestamp(window.train_end))
        )
        test_mask = (
            (dates >= pd.Timestamp(window.test_start))
            & (dates <= pd.Timestamp(window.test_end))
        )
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            raw_all.loc[train_mask].copy(),
            holding_days=config.holding_days,
        )
        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_all.attrs)

        baseline = D.features(
            symbols,
            [baseline_expr],
            start_time=window.test_start,
            end_time=window.test_end,
        )
        baseline = (
            _normalize_index(baseline)
            .replace([np.inf, -np.inf], np.nan)
            .dropna(axis=0, how="any")
        )
        baseline.columns = ["score"]
        baseline.attrs["provenance"] = "factor_baseline"
        baseline.attrs["expression"] = baseline_expr

        ranker_scores: dict[str, pd.DataFrame] = {}
        for candidate in ranker_grid:
            columns = [
                expression_columns[expression]
                for expression in candidate.feature_group.expressions
            ]
            x_rank, y_rank, groups = prepare_ranker_frame(
                features_train.loc[:, columns],
                returns_train,
            )
            ranker = fit_lgbm_daily_ranker(
                x_rank,
                y_rank,
                groups,
                n_gain_bins=candidate.calibration.n_gain_bins,
                params=candidate.calibration.params(),
                num_boost_round=candidate.calibration.num_boost_round,
            )
            prediction_features = _complete_prediction_rows(
                features_test,
                columns,
            )
            if prediction_features.empty:
                continue
            ranker_scores[candidate.name] = predict_lgbm_daily_ranker(
                ranker,
                prediction_features,
            )

        candidates = {
            **ranker_scores,
            **build_blend_candidates(
                ranker_scores,
                baseline,
                weights=default_blend_weights(),
            ),
            "factor:historical_momentum_10d": baseline,
        }
        experiment = run_10d_experiment(
            config=config,
            candidates=candidates,
            raw_returns=returns_test,
            output_dir=out_dir,
        )
        _mark_experiment_diagnostic(experiment)
        reports.append(experiment)

    summary = summarize_walk_forward_reports(
        reports,
        min_windows=MIN_STABILITY_WINDOWS,
    )
    summary_path = out_dir / "walk_forward_stability.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    diagnostic_manifest = {
        "schema_version": "1.0",
        "diagnostic_type": "stable_signal_blend",
        "diagnostic_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "lifecycle_promotion": "not_evaluated",
        "n_windows": len(windows),
        "n_reports": len(reports),
        "target_rankers": sorted(TARGET_RANKER_NAMES),
        "blend_weights": [
            weight.to_dict() for weight in default_blend_weights()
        ],
    }
    diagnostic_path = out_dir / "diagnostic_manifest.json"
    diagnostic_path.write_text(
        json.dumps(diagnostic_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "windows": [window.to_dict() for window in windows],
        "summary_path": str(summary_path),
        "summary": summary,
        "diagnostic_manifest_path": str(diagnostic_path),
        "diagnostic_manifest": diagnostic_manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--first-test-year", type=int, default=2024)
    parser.add_argument("--last-test-year", type=int, default=2026)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root,
                first_test_year=args.first_test_year,
                last_test_year=args.last_test_year,
            ),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
