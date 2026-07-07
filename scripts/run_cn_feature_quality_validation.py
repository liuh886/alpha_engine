"""Run CN-specific feature-quality validation with aligned rolling evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.cn_feature_quality import (
    build_cn_feature_quality_grid,
    cn_factor_baseline_expressions,
    cn_feature_grid_manifest,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import fit_lgbm_daily_ranker, predict_lgbm_daily_ranker
from src.research.market_data_alignment import align_train_start_to_coverage, get_aligned_windows
from src.research.model_decision_pack import build_model_decision_pack, render_model_decision_markdown
from src.research.multi_market_readiness import MarketReadinessSpec, check_market_data_coverage, load_market_watchlist, normalize_market_symbols
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import load_symbol_date_coverage, validate_no_nan_inputs
from src.research.walk_forward_stability import summarize_walk_forward_reports

MIN_STABILITY_WINDOWS = 3


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        frame = frame.swaplevel().sort_index()
    return frame


def _available_symbols() -> set[str]:
    try:
        from qlib.data import D

        instruments = D.list_instruments(D.instruments("all"), level="market")
        if hasattr(instruments, "tolist"):
            return {str(item) for item in instruments.tolist()}
        return {str(item) for item in instruments}
    except Exception:
        return set()


def _cn_spec(root: Path, *, train_start: str, test_end: str, min_symbols: int) -> MarketReadinessSpec:
    raw = load_market_watchlist("cn", watchlist_path=root / "configs" / "watchlist.yaml")
    rows = normalize_market_symbols("cn", raw, available_symbols=_available_symbols() or None)
    symbols = tuple(row.normalized_symbol for row in rows)
    if len(symbols) < min_symbols:
        raise ValueError(f"CN watchlist has only {len(symbols)} symbols, below min_symbols={min_symbols}")
    return MarketReadinessSpec(
        market="cn",
        symbols=symbols,
        benchmark="000300",
        train_start=train_start,
        test_end=test_end,
        min_symbols=min_symbols,
    )


def _fit_ranker_scores(candidate, features_train, returns_train, features_test, expression_columns):
    cols = [expression_columns[expr] for expr in candidate.feature_group.expressions]
    x_rank, y_rank, groups = prepare_ranker_frame(features_train.loc[:, cols], returns_train)
    ranker = fit_lgbm_daily_ranker(
        x_rank,
        y_rank,
        groups,
        n_gain_bins=candidate.calibration.n_gain_bins,
        params=candidate.calibration.params(),
        num_boost_round=candidate.calibration.num_boost_round,
    )
    return predict_lgbm_daily_ranker(ranker, features_test.loc[:, cols])


def run(
    root: Path,
    *,
    first_test_year: int,
    last_test_year: int,
    train_start: str,
    test_end: str,
    alignment_mode: str = "auto",
    min_symbols: int = 50,
) -> dict[str, Any]:
    safe_qlib_init(build_qlib_init_cfg(None, market="cn", provider_uri_default=str(root / "data" / "watchlist")))
    from qlib.data import D

    spec = _cn_spec(root, train_start=train_start, test_end=test_end, min_symbols=min_symbols)
    out_dir = root / "artifacts" / "evidence" / "cn_feature_quality"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_coverage = load_symbol_date_coverage(list(spec.symbols), train_start, test_end)
    alignment = align_train_start_to_coverage(
        spec,
        date_coverage,
        alignment_mode=alignment_mode,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    readiness = check_market_data_coverage(
        spec,
        available_symbols=_available_symbols() or None,
        date_coverage_data=date_coverage,
    )
    readiness.update(alignment.to_dict())
    (out_dir / "readiness.json").write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")
    if alignment.skipped:
        payload = {"status": "skipped", "reason": alignment.skip_reason, "readiness": readiness}
        (out_dir / "cn_feature_quality_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    symbols = list(alignment.retained_symbols)
    topk = min(3, len(symbols) - 1)
    calendar = pd.DatetimeIndex(D.calendar(start_time=alignment.aligned_start, end_time=test_end, freq="day"))
    if calendar.empty:
        raise ValueError("CN Qlib calendar has no data in aligned range")
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")
    windows = get_aligned_windows(
        alignment.aligned_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    if len(windows) < MIN_STABILITY_WINDOWS:
        payload = {
            "status": "skipped",
            "reason": f"only {len(windows)} aligned windows available (need >= {MIN_STABILITY_WINDOWS})",
            "readiness": readiness,
        }
        (out_dir / "cn_feature_quality_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    grid = build_cn_feature_quality_grid()
    manifest = cn_feature_grid_manifest(grid)
    (out_dir / "candidate_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    feature_exprs = sorted({expr for candidate in grid for expr in candidate.feature_group.expressions})
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    factor_baselines = cn_factor_baseline_expressions()
    reports: list[dict[str, Any]] = []
    for window in windows:
        config = ResearchSessionConfig(
            market="cn",
            symbols=symbols,
            benchmark=spec.benchmark,
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            topk=topk,
            model_type="cn_feature_quality",
            experiment_id=f"cn_feature_quality_{window.label}",
            return_expression=CANONICAL_10D_RETURN_EXPR,
        )
        features_all = D.features(symbols, feature_exprs, start_time=window.train_start, end_time=window.test_end)
        raw_all = D.features(symbols, [config.return_expression], start_time=window.train_start, end_time=window.test_end)
        features_all = _normalize_index(features_all).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[expr] for expr in feature_exprs]
        raw_all = _normalize_index(raw_all)
        raw_all.columns = ["return"]
        raw_all.attrs.update({"provenance": "raw_forward_return", "horizon": 10, "expression": config.return_expression})
        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = (dates >= pd.Timestamp(window.test_start)) & (dates <= pd.Timestamp(window.test_end))
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            raw_all.loc[train_mask].copy(),
            holding_days=config.holding_days,
        )
        ok, reason = validate_no_nan_inputs(features_train, context=f"CN feature train/{window.label}")
        if not ok:
            print(f"Skipping window {window.label}: {reason}")
            continue
        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_all.attrs)

        candidates: dict[str, pd.DataFrame] = {}
        for candidate in grid:
            scores = _fit_ranker_scores(candidate, features_train, returns_train, features_test, expression_columns)
            candidates[candidate.name] = scores
        for name, expr in factor_baselines.items():
            baseline = D.features(symbols, [expr], start_time=window.test_start, end_time=window.test_end)
            baseline = _normalize_index(baseline)
            baseline.columns = ["score"]
            baseline.attrs.update({"provenance": "factor_baseline", "expression": expr})
            candidates[name] = baseline

        reports.append(run_10d_experiment(config=config, candidates=candidates, raw_returns=returns_test, output_dir=out_dir))

    if len(reports) < MIN_STABILITY_WINDOWS:
        payload = {
            "status": "skipped",
            "reason": f"only {len(reports)} reports survived validation (need >= {MIN_STABILITY_WINDOWS})",
            "readiness": readiness,
        }
        (out_dir / "cn_feature_quality_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    summary = summarize_walk_forward_reports(reports, min_windows=MIN_STABILITY_WINDOWS)
    (out_dir / "walk_forward_stability.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    pack = build_model_decision_pack(summary)
    (out_dir / "model_decision_pack.json").write_text(json.dumps(pack, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "model_decision_pack.md").write_text(render_model_decision_markdown(pack), encoding="utf-8")
    return {"status": "passed", "summary_path": str(out_dir / "walk_forward_stability.json"), "decision": pack["decision"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--first-test-year", type=int, default=2024)
    parser.add_argument("--last-test-year", type=int, default=2026)
    parser.add_argument("--train-start", default="2021-01-01")
    parser.add_argument("--test-end", default="2026-06-18")
    parser.add_argument("--alignment-mode", choices=["strict", "auto"], default="auto")
    parser.add_argument("--min-symbols", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(run(
        args.root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
        train_start=args.train_start,
        test_end=args.test_end,
        alignment_mode=args.alignment_mode,
        min_symbols=args.min_symbols,
    ), indent=2, default=str))


if __name__ == "__main__":
    main()
