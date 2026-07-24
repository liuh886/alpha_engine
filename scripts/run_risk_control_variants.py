"""Run approved drawdown-control variants against baseline_v1.

This runner keeps the frozen PR #172 candidate score unchanged and evaluates only
portfolio-construction variants:

1. ``top5_equal_weight``
2. ``top3_inverse_vol20_weight``
3. ``top3_benchmark_trend_filter``

Outputs are written under ``artifacts/evidence/risk_control_variants/``.  The
runner is research-only: it does not tune model weights, add factors, change the
universe, promote a model, or mark anything trade-ready.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_benchmark_aware_topk_evidence import (
    FROZEN_BLEND_WEIGHT,
    FROZEN_CALIBRATION,
    FROZEN_FEATURE_GROUP,
    _init_qlib,
    _load_session,
    _normalize_index,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.notebook_research_api import sanitize_factor_name
from src.research.risk_control_variants import (
    RiskVariantReport,
    aggregate_variant_reports,
    default_variant_specs,
    evaluate_risk_control_variant,
)
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)
from src.research.stable_signal_blend import build_two_signal_blend


def _candidate_id() -> str:
    return (
        "blend:ranker_momentum:momentum_volatility_volume:"
        "gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5"
    )


def _load_benchmark_returns(
    benchmark: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    from qlib.data import D

    bench_raw = D.features(
        [benchmark],
        [CANONICAL_10D_RETURN_EXPR],
        start_time=start,
        end_time=end,
    )
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench_raw = bench_raw.xs(benchmark, level="instrument")
    benchmark_returns = bench_raw.copy()
    benchmark_returns.columns = ["return"]
    benchmark_returns.attrs["provenance"] = "raw_forward_return"
    benchmark_returns.attrs["horizon"] = 10
    benchmark_returns.attrs["expression"] = CANONICAL_10D_RETURN_EXPR
    return benchmark_returns


def _load_benchmark_trend(
    benchmark: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    from qlib.data import D

    dollar = chr(36)
    expr = f"{dollar}close/Ref({dollar}close,20)-1"
    trend_raw = D.features([benchmark], [expr], start_time=start, end_time=end)
    if isinstance(trend_raw.index, pd.MultiIndex):
        trend_raw = trend_raw.xs(benchmark, level="instrument")
    trend = trend_raw.copy()
    trend.columns = ["trend_return_20d"]
    return trend.replace([np.inf, -np.inf], np.nan)


def _evaluate_window_variants(
    window: Any,
    symbols: list[str],
    benchmark: str,
    expression_columns: dict[str, str],
    feature_exprs: list[str],
    baseline_expr: str,
) -> dict[str, Any] | None:
    from qlib.data import D

    features_all = D.features(
        symbols,
        feature_exprs,
        start_time=window.train_start,
        end_time=window.test_end,
    )
    raw_all = D.features(
        symbols,
        [CANONICAL_10D_RETURN_EXPR],
        start_time=window.train_start,
        end_time=window.test_end,
    )
    features_all = _normalize_index(features_all).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [expression_columns[expr] for expr in feature_exprs]

    raw_all = _normalize_index(raw_all)
    raw_all.columns = ["return"]
    raw_all.attrs["provenance"] = "raw_forward_return"
    raw_all.attrs["horizon"] = 10
    raw_all.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

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
        holding_days=10,
    )
    features_test = features_all.loc[test_mask].copy()
    returns_test = raw_all.loc[test_mask].copy()
    returns_test.attrs.update(raw_all.attrs)

    cols = [expression_columns[expr] for expr in feature_exprs]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, cols],
        returns_train,
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

    momentum = D.features(
        symbols,
        [baseline_expr],
        start_time=window.test_start,
        end_time=window.test_end,
    )
    momentum = _normalize_index(momentum)
    momentum.columns = ["score"]
    momentum.attrs["provenance"] = "factor_baseline"
    momentum.attrs["expression"] = baseline_expr

    blend = build_two_signal_blend(
        ranker_scores,
        momentum,
        weight=FROZEN_BLEND_WEIGHT,
        invert_momentum=True,
    )

    dollar = chr(36)
    vol_expr = f"Std({dollar}close/Ref({dollar}close,1)-1,20)"
    vol20 = D.features(
        symbols,
        [vol_expr],
        start_time=window.test_start,
        end_time=window.test_end,
    )
    vol20 = _normalize_index(vol20).replace([np.inf, -np.inf], np.nan)
    vol20.columns = ["vol20"]

    benchmark_returns = _load_benchmark_returns(
        benchmark,
        window.test_start,
        window.test_end,
    )
    benchmark_trend = _load_benchmark_trend(
        benchmark,
        window.test_start,
        window.test_end,
    )
    if benchmark_returns.empty:
        print(f"  [skip] {window.label}: empty benchmark returns")
        return None

    variants: dict[str, dict[str, Any]] = {}
    reports: dict[str, RiskVariantReport] = {}
    for spec in default_variant_specs():
        report = evaluate_risk_control_variant(
            blend,
            returns_test,
            benchmark_returns,
            spec=spec,
            vol20=vol20,
            benchmark_trend=benchmark_trend,
            rebalance_days=10,
            cost_bps=20.0,
        )
        reports[spec.variant_id] = report
        variants[spec.variant_id] = report.to_dict()

    return {
        "window": window.to_dict(),
        "candidate": _candidate_id(),
        "variants": variants,
        "_reports": reports,
    }


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    first_test_year: int = 2024,
    last_test_year: int = 2026,
) -> dict[str, Any]:
    # Session config always lives under --root.  --data-root only governs
    # the Qlib provider URI below so the watchlist can live on a separate volume.
    session = _load_session(root)
    market = str(session["market"])
    symbols = list(session["symbols"])
    benchmark = str(session["benchmark"])
    train_start = str(session["train_start"])
    test_end = str(session["test_end"])

    effective_data_root = data_root if data_root is not None else root
    provider_uri = str(effective_data_root / "data" / "watchlist")
    _init_qlib(market, provider_uri)

    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(start_time=train_start, end_time=test_end, freq="day")
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in configured session range")
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")

    windows = filter_windows_by_available_range(
        half_year_rolling_windows(
            start_year=int(train_start[:4]),
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        ),
        available_start=train_start,
        available_end=available_end,
    )
    if not windows:
        raise ValueError("no complete rolling windows covered by available Qlib range")

    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    dollar = chr(36)
    baseline_expr = f"{dollar}close/Ref({dollar}close,10)-1"

    base_out = root / "artifacts" / "evidence" / "risk_control_variants"
    per_window_dir = base_out / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)

    print("\nRisk-control variants against baseline_v1")
    print(f"  market:       {market}")
    print(f"  benchmark:    {benchmark}")
    print(f"  symbols:      {symbols}")
    print(f"  output:       {base_out}")
    print("  trade_ready:  false")
    print()

    per_variant_reports: dict[str, list[RiskVariantReport]] = {
        spec.variant_id: [] for spec in default_variant_specs()
    }
    window_payloads: list[dict[str, Any]] = []
    for window in windows:
        print(
            f"  {window.label}  train={window.train_start}->{window.train_end}  "
            f"test={window.test_start}->{window.test_end}"
        )
        payload = _evaluate_window_variants(
            window,
            symbols,
            benchmark,
            expression_columns,
            feature_exprs,
            baseline_expr,
        )
        if payload is None:
            continue
        reports = payload.pop("_reports")
        for variant_id, report in reports.items():
            per_variant_reports[variant_id].append(report)
            print(
                f"    {variant_id}: rel_xs={report.relative_excess_return:.4f}  "
                f"SR={report.sharpe_ratio:.2f}  MDD={report.max_drawdown:.4f}  "
                f"gross={report.mean_gross_exposure:.2f}"
            )
        window_payloads.append(payload)
        out_path = per_window_dir / f"{window.label}.json"
        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    if not window_payloads:
        raise ValueError("no windows produced valid risk-control variant results")

    aggregate = aggregate_variant_reports(per_variant_reports)
    aggregate_path = base_out / "aggregate_summary.json"
    aggregate_path.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "1.0",
        "evidence_type": "risk_control_variants",
        "baseline_id": "us_top3_blend_v1",
        "candidate": _candidate_id(),
        "research_only": True,
        "trade_ready": False,
        "promotion_eligible": False,
        "cost_bps": 20.0,
        "turnover_model": "cash_inclusive_one_way",
        "n_windows_evaluated": len(window_payloads),
        "n_windows_total": len(windows),
        "variants": [spec.variant_id for spec in default_variant_specs()],
        "candidate_v2_selected": aggregate["candidate_v2_selected"],
        "decision": aggregate["candidate_v2_decision"],
    }
    manifest_path = base_out / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "aggregate_path": str(aggregate_path),
        "manifest_path": str(manifest_path),
        "per_window_dir": str(per_window_dir),
        "aggregate": aggregate,
        "manifest": manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--first-test-year", type=int, default=2024)
    parser.add_argument("--last-test-year", type=int, default=2026)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run(
        args.root,
        data_root=args.data_root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
    )
    print(f"\n  aggregate:  {result['aggregate_path']}")
    print(f"  manifest:   {result['manifest_path']}")
    print(f"  per-window: {result['per_window_dir']}")


if __name__ == "__main__":
    main()
