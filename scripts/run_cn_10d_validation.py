"""Run CN 10D validation for the frozen ranker + momentum blend when CN data is ready."""

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
from src.research.market_data_alignment import align_train_start_to_coverage, get_aligned_windows
from src.research.model_decision_pack import build_model_decision_pack, render_model_decision_markdown
from src.research.multi_market_readiness import MarketReadinessSpec, check_market_data_coverage, load_market_watchlist, normalize_market_symbols
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import RankerCalibration, RankerFeatureGroup, RankerGridCandidate
from src.research.rolling_windows import purge_training_tail
from src.research.stable_signal_blend import BlendWeight, build_blend_candidates
from src.research.universe_robustness import load_symbol_date_coverage, validate_no_nan_inputs
from src.research.walk_forward_stability import summarize_walk_forward_reports

FROZEN_FEATURE_GROUP = RankerFeatureGroup(
    name="momentum_volatility_volume",
    expressions=(
        "$close/Ref($close,5)-1",
        "$close/Ref($close,10)-1",
        "$close/Ref($close,20)-1",
        "Std($close/Ref($close,1)-1,10)",
        "Std($close/Ref($close,1)-1,20)",
        "$volume/Ref($volume,10)-1",
        "$volume/Mean($volume,20)-1",
    ),
)
FROZEN_CALIBRATION = RankerCalibration(n_gain_bins=5, num_boost_round=100, num_leaves=31, min_data_in_leaf=10)
FROZEN_RANKER = RankerGridCandidate(feature_group=FROZEN_FEATURE_GROUP, calibration=FROZEN_CALIBRATION)
FROZEN_BLEND_WEIGHT = BlendWeight(ranker_weight=0.50, momentum_weight=0.50)
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


def _cn_spec(root: Path, *, train_start: str, test_end: str) -> MarketReadinessSpec:
    raw = load_market_watchlist("cn", watchlist_path=root / "configs" / "watchlist.yaml")
    available = _available_symbols()
    rows = normalize_market_symbols("cn", raw, available_symbols=available or None)
    symbols = tuple(row.normalized_symbol for row in rows)
    if len(symbols) < 2:
        raise ValueError("CN watchlist has fewer than two normalized symbols")
    return MarketReadinessSpec(
        market="cn",
        symbols=symbols,
        benchmark="000300",
        train_start=train_start,
        test_end=test_end,
        min_symbols=min(50, max(20, min(len(symbols), 50))),
    )


def run(root: Path, *, first_test_year: int, last_test_year: int, train_start: str, test_end: str, alignment_mode: str = "strict") -> dict[str, Any]:
    safe_qlib_init(
        build_qlib_init_cfg(None, market="cn", provider_uri_default=str(root / "data" / "watchlist"))
    )
    from qlib.data import D

    available = _available_symbols()
    spec = _cn_spec(root, train_start=train_start, test_end=test_end)
    out_dir = root / "artifacts" / "evidence" / "cn_10d_validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── alignment-aware readiness ──────────────────────────────────────────
    date_coverage = load_symbol_date_coverage(list(spec.symbols), train_start, test_end)
    alignment = align_train_start_to_coverage(
        spec, date_coverage, alignment_mode=alignment_mode,
        first_test_year=first_test_year, last_test_year=last_test_year,
    )

    # Build readiness report enriched with alignment fields
    readiness = check_market_data_coverage(spec, available_symbols=available or None, date_coverage_data=date_coverage)
    readiness["alignment_mode"] = alignment.alignment_mode
    readiness["requested_train_start"] = alignment.requested_train_start
    readiness["aligned_train_start"] = alignment.aligned_train_start

    (out_dir / "readiness.json").write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    if alignment.skipped:
        payload = {
            "status": "skipped",
            "reason": alignment.skip_reason,
            "alignment_mode": alignment.alignment_mode,
            "requested_train_start": alignment.requested_train_start,
            "aligned_train_start": alignment.aligned_train_start,
            "readiness": readiness,
        }
        (out_dir / "cn_validation_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    symbols = list(alignment.retained_symbols)
    effective_start = alignment.aligned_start
    topk = min(3, len(symbols) - 1)
    calendar = pd.DatetimeIndex(D.calendar(start_time=effective_start, end_time=test_end, freq="day"))
    if calendar.empty:
        raise ValueError("CN Qlib calendar has no data in configured range")
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")
    windows = get_aligned_windows(
        effective_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    if not windows:
        payload = {
            "status": "skipped",
            "reason": f"no complete aligned windows for {effective_start} through {available_end}",
            "alignment_mode": alignment.alignment_mode,
            "requested_train_start": alignment.requested_train_start,
            "aligned_train_start": alignment.aligned_train_start,
            "readiness": readiness,
        }
        (out_dir / "cn_validation_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    baseline_expr = "$close/Ref($close,10)-1"
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
            model_type="cn_stable_signal_blend",
            experiment_id=f"cn_stable_blend_{window.label}",
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
        features_train, returns_train = purge_training_tail(features_all.loc[train_mask].copy(), raw_all.loc[train_mask].copy(), holding_days=config.holding_days)

        ok, reason = validate_no_nan_inputs(features_train, context=f"features train/{window.label}")
        if not ok:
            print(f"Skipping window {window.label}: {reason}")
            continue

        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_all.attrs)
        baseline = D.features(symbols, [baseline_expr], start_time=window.test_start, end_time=window.test_end)
        baseline = _normalize_index(baseline)
        baseline.columns = ["score"]
        baseline.attrs.update({"provenance": "factor_baseline", "expression": baseline_expr})
        cols = [expression_columns[expr] for expr in feature_exprs]
        x_rank, y_rank, groups = prepare_ranker_frame(features_train.loc[:, cols], returns_train)
        ranker = fit_lgbm_daily_ranker(x_rank, y_rank, groups, n_gain_bins=FROZEN_CALIBRATION.n_gain_bins, params=FROZEN_CALIBRATION.params(), num_boost_round=FROZEN_CALIBRATION.num_boost_round)
        ranker_scores = predict_lgbm_daily_ranker(ranker, features_test.loc[:, cols])
        candidates = {FROZEN_RANKER.name: ranker_scores, "factor:historical_momentum_10d": baseline}
        candidates.update(build_blend_candidates({FROZEN_RANKER.name: ranker_scores}, baseline, weights=[FROZEN_BLEND_WEIGHT]))
        reports.append(run_10d_experiment(config=config, candidates=candidates, raw_returns=returns_test, output_dir=out_dir))

    if len(reports) < MIN_STABILITY_WINDOWS:
        payload = {
            "status": "skipped",
            "reason": f"only {len(reports)} reports survived validation (need ≥ {MIN_STABILITY_WINDOWS})",
            "alignment_mode": alignment.alignment_mode,
            "requested_train_start": alignment.requested_train_start,
            "aligned_train_start": alignment.aligned_train_start,
            "readiness": readiness,
        }
        (out_dir / "cn_validation_skipped.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
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
    parser.add_argument("--alignment-mode", choices=["strict", "auto"], default="strict",
                        help="Train-start alignment mode (default: strict)")
    args = parser.parse_args()
    print(json.dumps(run(args.root, first_test_year=args.first_test_year, last_test_year=args.last_test_year, train_start=args.train_start, test_end=args.test_end, alignment_mode=args.alignment_mode), indent=2, default=str))


if __name__ == "__main__":
    main()
