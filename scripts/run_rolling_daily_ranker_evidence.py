"""Generate rolling fixed-10D evidence for the daily ranker lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import fit_lgbm_daily_ranker, predict_lgbm_daily_ranker
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)
from src.research.walk_forward_stability import summarize_walk_forward_reports

MIN_STABILITY_WINDOWS = 3


def _default_feature_exprs() -> list[str]:
    dollar = chr(36)
    return [
        f"{dollar}close/Ref({dollar}close,5)-1",
        f"{dollar}close/Ref({dollar}close,10)-1",
        f"{dollar}close/Ref({dollar}close,20)-1",
        "Std($ret,10)",
        f"{dollar}volume/Ref({dollar}volume,10)-1",
    ]


def _load_session(root: Path) -> dict[str, object]:
    path = root / "data" / "session_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "market": "us",
        "symbols": ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "COST", "NFLX"],
        "benchmark": "QQQ",
        "train_start": "2021-01-01",
        "train_end": "2025-12-31",
        "test_start": "2024-01-01",
        "test_end": "2026-06-18",
        "topk": 3,
    }


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        frame = frame.swaplevel().sort_index()
    return frame


def run(root: Path, *, first_test_year: int, last_test_year: int) -> dict[str, object]:
    session = _load_session(root)
    symbols = list(session["symbols"])
    topk = min(int(session.get("topk", 3)), len(symbols) - 1)
    config_base = {
        "market": str(session["market"]),
        "symbols": symbols,
        "benchmark": str(session["benchmark"]),
        "topk": topk,
        "model_type": "lgbm_lambdarank",
        "return_expression": CANONICAL_10D_RETURN_EXPR,
    }

    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market=str(session["market"]),
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
    # The configured boundary may fall on a weekend before the first trading
    # session. Treat that as covered; use the actual calendar to cap the end.
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
    feature_exprs = _default_feature_exprs()
    reports = []
    out_dir = root / "artifacts" / "evidence" / "rolling_10d_lab"
    out_dir.mkdir(parents=True, exist_ok=True)

    for window in windows:
        config = ResearchSessionConfig(
            **config_base,
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            experiment_id=f"{config_base['market']}_daily_ranker_{window.label}",
        )
        features_all = D.features(symbols, feature_exprs, start_time=window.train_start, end_time=window.test_end)
        raw_all = D.features(symbols, [config.return_expression], start_time=window.train_start, end_time=window.test_end)
        features_all = _normalize_index(features_all).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        features_all.columns = [sanitize_factor_name(expr) for expr in feature_exprs]
        raw_all = _normalize_index(raw_all)
        raw_all.columns = ["return"]
        raw_all.attrs["provenance"] = "raw_forward_return"
        raw_all.attrs["horizon"] = 10
        raw_all.attrs["expression"] = config.return_expression

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

        x_rank, y_rank, groups = prepare_ranker_frame(features_train, returns_train)
        ranker = fit_lgbm_daily_ranker(x_rank, y_rank, groups, n_gain_bins=5, num_boost_round=200)
        ranker_scores = predict_lgbm_daily_ranker(ranker, features_test)
        baseline_expr = feature_exprs[1]
        baseline = D.features(symbols, [baseline_expr], start_time=window.test_start, end_time=window.test_end)
        baseline = _normalize_index(baseline)
        baseline.columns = ["score"]
        baseline.attrs["provenance"] = "factor_baseline"
        baseline.attrs["expression"] = baseline_expr

        experiment = run_10d_experiment(
            config=config,
            candidates={
                "lgbm:daily_ranker": ranker_scores,
                "factor:historical_momentum_10d": baseline,
            },
            raw_returns=returns_test,
            output_dir=out_dir,
        )
        reports.append(experiment)

    summary = summarize_walk_forward_reports(reports, min_windows=MIN_STABILITY_WINDOWS)
    summary_path = out_dir / "walk_forward_stability.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return {"windows": [window.to_dict() for window in windows], "summary_path": str(summary_path), "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--first-test-year", type=int, default=2024)
    parser.add_argument("--last-test-year", type=int, default=2026)
    args = parser.parse_args()
    print(json.dumps(run(args.root, first_test_year=args.first_test_year, last_test_year=args.last_test_year), indent=2, default=str))


if __name__ == "__main__":
    main()
