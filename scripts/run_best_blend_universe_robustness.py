"""Generate universe-robustness evidence for the #86 best 50/50 ranker + inverted momentum blend.

This script reuses the #84 rolling-window framework, #85 ranker grid, #86 stable
blend logic, and #87 model-decision-pack API.  It runs the exact frozen
calibration/blend on every eligible universe and produces:

- ``coverage_report.json``
- per-universe folders under ``artifacts/evidence/universe_robustness/``
- ``universe_robustness_summary.json``
- ``model_decision_pack_by_universe.json``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import fit_lgbm_daily_ranker, predict_lgbm_daily_ranker
from src.research.market_data_alignment import align_train_start_to_coverage, get_aligned_windows
from src.research.model_decision_pack import build_model_decision_pack
from src.research.multi_market_readiness import MarketReadinessSpec
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import RankerCalibration, RankerFeatureGroup, RankerGridCandidate
from src.research.rolling_windows import purge_training_tail
from src.research.stable_signal_blend import BlendWeight, build_blend_candidates
from src.research.universe_robustness import (
    UniverseSpec,
    build_required_candidate_names,
    default_universe_specs,
    filter_universe_by_coverage,
    load_symbol_date_coverage,
    summarize_universe_robustness,
    validate_no_nan_inputs,
)
from src.research.walk_forward_stability import summarize_walk_forward_reports

# ── frozen #86 best configuration ──────────────────────────────────────────
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
FROZEN_CALIBRATION = RankerCalibration(
    n_gain_bins=5,
    num_boost_round=100,
    num_leaves=31,
    min_data_in_leaf=10,
    learning_rate=0.05,
)
FROZEN_RANKER = RankerGridCandidate(
    feature_group=FROZEN_FEATURE_GROUP,
    calibration=FROZEN_CALIBRATION,
)
FROZEN_BLEND_WEIGHT = BlendWeight(ranker_weight=0.50, momentum_weight=0.50)
MIN_STABILITY_WINDOWS = 3
EMBARGO_DAYS = 10


def _load_session(root: Path) -> dict[str, Any]:
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
        frame = frame.swaplevel().sort_index()
    return frame



def _build_universe_specs(
    session: dict[str, Any],
    root: Path,
) -> list[UniverseSpec]:
    """Build universe specs from session + local sources, ordered smallest→largest."""
    session_symbols = list(session["symbols"])
    market = str(session["market"])
    return default_universe_specs(session_symbols, market=market)


def run(root: Path, *, first_test_year: int, last_test_year: int, alignment_mode: str = "strict") -> dict[str, Any]:
    session = _load_session(root)
    market = str(session["market"])
    benchmark = str(session["benchmark"])
    train_start = str(session["train_start"])
    test_end = str(session["test_end"])
    requested_topk = int(session.get("topk", 3))

    universes = _build_universe_specs(session, root)
    if not universes:
        raise ValueError("no universe specs could be built from session or local sources")

    base_out = root / "artifacts" / "evidence" / "universe_robustness"
    base_out.mkdir(parents=True, exist_ok=True)

    # ── Qlib init ───────────────────────────────────────────────────────
    try:
        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market=market,
                provider_uri_default=str(root / "data" / "watchlist"),
            )
        )
        from qlib.data import D

        calendar = pd.DatetimeIndex(
            D.calendar(start_time=train_start, end_time=test_end, freq="day")
        )
        qlib_available = True
    except Exception:
        qlib_available = False
        calendar = pd.DatetimeIndex([])

    # ── coverage check with alignment ────────────────────────────────────
    coverage_reports: dict[str, dict[str, Any]] = {}
    alignment_results: dict[str, Any] = {}
    effective_train_starts: dict[str, str] = {}

    for universe in universes:
        if qlib_available:
            date_coverage = load_symbol_date_coverage(
                universe.symbols, train_start, test_end
            )
        else:
            date_coverage = {}

        # Run alignment for this universe
        universe_spec = MarketReadinessSpec(
            market=market,
            symbols=universe.symbols,
            benchmark=benchmark,
            train_start=train_start,
            test_end=test_end,
            min_symbols=universe.min_symbols,
        )
        alignment = align_train_start_to_coverage(
            universe_spec, date_coverage, alignment_mode=alignment_mode,
            first_test_year=first_test_year, last_test_year=last_test_year,
        )
        alignment_results[universe.name] = alignment.to_dict()

        # Use aligned start for this universe when auto mode
        effective_start = alignment.aligned_start

        coverage = filter_universe_by_coverage(
            universe.symbols,
            min_symbols=universe.min_symbols,
            date_range=(effective_start, test_end),
            date_coverage_data=date_coverage,
        )
        coverage["universe_name"] = universe.name
        coverage["alignment_mode"] = alignment_mode
        coverage["requested_train_start"] = train_start
        coverage["aligned_train_start"] = effective_start
        # Alignment decision is the authoritative downstream gate for execution.
        if alignment.skipped:
            coverage["skipped"] = True
            coverage["sufficient"] = False
            coverage["retained_symbols"] = []
            coverage["skip_reason"] = alignment.skip_reason
        elif alignment_mode == "auto":
            # Auto mode: alignment success overrides strict date-coverage report.
            # The alignment's retained/dropped symbols, skip state, and coverage
            # ratio become authoritative — the strict sufficient_coverage gate
            # that may have flagged symbols is superseded.
            coverage["skipped"] = False
            coverage["sufficient"] = True
            coverage["retained_symbols"] = list(alignment.retained_symbols)
            coverage["dropped_symbols"] = list(alignment.dropped_symbols)
            coverage["skip_reason"] = None
            n_total = len(universe.symbols) or 1
            coverage["coverage_ratio"] = round(
                len(alignment.retained_symbols) / n_total, 4
            )

        coverage_reports[universe.name] = coverage
        effective_train_starts[universe.name] = effective_start

    coverage_path = base_out / "coverage_report.json"
    coverage_path.write_text(json.dumps(coverage_reports, indent=2, sort_keys=True), encoding="utf-8")

    # ── per-universe walk-forward ───────────────────────────────────────
    available_end = test_end
    if qlib_available and not calendar.empty:
        available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")

    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    dollar = chr(36)
    baseline_expr = f"{dollar}close/Ref({dollar}close,10)-1"

    per_universe_summaries: dict[str, Any] = {}
    per_universe_decision_packs: dict[str, Any] = {}

    for universe in universes:
        coverage = coverage_reports[universe.name]
        effective_start = effective_train_starts.get(universe.name, train_start)

        if coverage["skipped"]:
            per_universe_summaries[universe.name] = None
            per_universe_decision_packs[universe.name] = None
            continue

        symbols = coverage["retained_symbols"]
        if len(symbols) < 2:
            per_universe_summaries[universe.name] = None
            per_universe_decision_packs[universe.name] = None
            continue

        topk = min(requested_topk, len(symbols) - 1)
        if topk <= 0:
            per_universe_summaries[universe.name] = None
            per_universe_decision_packs[universe.name] = None
            continue

        if not qlib_available:
            per_universe_summaries[universe.name] = None
            per_universe_decision_packs[universe.name] = None
            continue

        windows = get_aligned_windows(
            effective_start,
            available_end,
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        )

        if not windows:
            per_universe_summaries[universe.name] = None
            per_universe_decision_packs[universe.name] = None
            continue

        universe_out = base_out / universe.name
        universe_out.mkdir(parents=True, exist_ok=True)
        reports: list[dict[str, Any]] = []
        required = build_required_candidate_names()

        for window in windows:
            config = ResearchSessionConfig(
                market=market,
                symbols=symbols,
                benchmark=benchmark,
                train_start=window.train_start,
                train_end=window.train_end,
                test_start=window.test_start,
                test_end=window.test_end,
                topk=topk,
                model_type="stable_signal_blend",
                experiment_id=f"{market}_universe_{universe.name}_{window.label}",
                return_expression=CANONICAL_10D_RETURN_EXPR,
            )

            features_all = D.features(
                symbols, feature_exprs, start_time=window.train_start, end_time=window.test_end
            )
            raw_all = D.features(
                symbols, [config.return_expression], start_time=window.train_start, end_time=window.test_end
            )
            features_all = _normalize_index(features_all).replace([np.inf, -np.inf], np.nan)
            features_all.columns = [expression_columns[expr] for expr in feature_exprs]

            raw_all = _normalize_index(raw_all)
            raw_all.columns = ["return"]
            raw_all.attrs["provenance"] = "raw_forward_return"
            raw_all.attrs["horizon"] = 10
            raw_all.attrs["expression"] = config.return_expression

            dates = features_all.index.get_level_values("datetime")
            train_mask = (dates >= pd.Timestamp(window.train_start)) & (
                dates <= pd.Timestamp(window.train_end)
            )
            test_mask = (dates >= pd.Timestamp(window.test_start)) & (
                dates <= pd.Timestamp(window.test_end)
            )

            features_train, returns_train = purge_training_tail(
                features_all.loc[train_mask].copy(),
                raw_all.loc[train_mask].copy(),
                holding_days=config.holding_days,
            )
            features_test = features_all.loc[test_mask].copy()
            returns_test = raw_all.loc[test_mask].copy()
            returns_test.attrs.update(raw_all.attrs)

            # Validate training features — skip window if all-NaN or zero-filled
            ok, reason = validate_no_nan_inputs(features_train, context=f"features train/{window.label}")
            if not ok:
                print(f"Skipping window {window.label}: {reason}")
                continue

            # Historical momentum baseline
            baseline = D.features(
                symbols, [baseline_expr], start_time=window.test_start, end_time=window.test_end
            )
            baseline = _normalize_index(baseline)
            baseline.columns = ["score"]
            baseline.attrs["provenance"] = "factor_baseline"
            baseline.attrs["expression"] = baseline_expr

            # Train frozen ranker
            cols = [expression_columns[expr] for expr in feature_exprs]
            x_rank, y_rank, groups = prepare_ranker_frame(
                features_train.loc[:, cols], returns_train
            )
            ranker = fit_lgbm_daily_ranker(
                x_rank,
                y_rank,
                groups,
                n_gain_bins=FROZEN_CALIBRATION.n_gain_bins,
                params=FROZEN_CALIBRATION.params(),
                num_boost_round=FROZEN_CALIBRATION.num_boost_round,
            )
            ranker_scores = predict_lgbm_daily_ranker(ranker, features_test.loc[:, cols])

            # Build candidates — ranker + exact blend via build_blend_candidates + baseline
            ranker_label = FROZEN_RANKER.name
            candidates: dict[str, pd.DataFrame] = {}
            candidates[ranker_label] = ranker_scores
            blends = build_blend_candidates(
                {ranker_label: ranker_scores},
                baseline,
                weights=[FROZEN_BLEND_WEIGHT],
            )
            candidates.update(blends)
            candidates[required["baseline"]] = baseline

            # Assert contract: keys must match required names
            expected_keys = {required["ranker"], required["blend"], required["baseline"]}
            actual_keys = set(candidates.keys())
            assert actual_keys == expected_keys, (
                f"Candidate keys mismatch for {window.label}: "
                f"{actual_keys - expected_keys} extra, {expected_keys - actual_keys} missing"
            )

            experiment = run_10d_experiment(
                config=config,
                candidates=candidates,
                raw_returns=returns_test,
                output_dir=universe_out,
            )
            reports.append(experiment)

        summary = summarize_walk_forward_reports(reports, min_windows=MIN_STABILITY_WINDOWS)
        summary_path = universe_out / "walk_forward_stability.json"
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        per_universe_summaries[universe.name] = summary

        # Build decision pack per universe
        try:
            decision_pack = build_model_decision_pack(summary)
        except ValueError:
            decision_pack = None
        per_universe_decision_packs[universe.name] = decision_pack

    # ── universe robustness summary ─────────────────────────────────────
    valid_summaries = {k: v for k, v in per_universe_summaries.items() if v is not None}
    if not valid_summaries:
        robustness_summary = {
            "skipped": True,
            "reason": "no universe produced sufficient stability reports",
            "alignment_mode": alignment_mode,
            "requested_train_start": train_start,
        }
    else:
        robustness_summary = summarize_universe_robustness(valid_summaries)
    summary_path = base_out / "universe_robustness_summary.json"
    summary_path.write_text(json.dumps(robustness_summary, indent=2, sort_keys=True), encoding="utf-8")

    # ── model decision pack by universe ─────────────────────────────────
    packs_path = base_out / "model_decision_pack_by_universe.json"
    packs_path.write_text(
        json.dumps(per_universe_decision_packs, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    return {
        "coverage_path": str(coverage_path),
        "summary_path": str(summary_path),
        "packs_path": str(packs_path),
        "coverage": coverage_reports,
        "summary": robustness_summary,
        "alignment_mode": alignment_mode,
        "alignment": alignment_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root directory")
    parser.add_argument("--first-test-year", type=int, default=2024, help="First OOS test year")
    parser.add_argument("--last-test-year", type=int, default=2026, help="Last OOS test year")
    parser.add_argument("--alignment-mode", choices=["strict", "auto"], default="strict",
                        help="Train-start alignment mode (default: strict)")
    args = parser.parse_args()
    result = run(
        args.root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
        alignment_mode=args.alignment_mode,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
