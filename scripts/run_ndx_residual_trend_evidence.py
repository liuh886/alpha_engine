"""Evaluate one predeclared QQQ-residual trend-quality signal on NDX.

This runner changes the economic information set instead of tuning the rejected
candidate_v2 model family.  The candidate is frozen before evaluation:

* 126 historical sessions;
* the most recent 10 sessions skipped;
* rolling QQQ beta removed;
* residual mean divided by residual volatility;
* higher score selected;
* the existing Top-3, 20 bps cost, and QQQ trend-exposure portfolio retained.

The already-observed 2024H1--2025H2 windows and 2026H1 partial holdout are
diagnostic/falsification evidence only.  They cannot promote the signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_candidate_v2_universe_robustness import (
    FROZEN_COST_BPS,
    FROZEN_EXPOSURE,
    FROZEN_TOP_N,
    MAX_DRAWDOWN_GATE,
    _compute_score_diagnostics,
    _load_benchmark_returns,
    _load_benchmark_trend,
    _normalize_index,
    _verify_us_provider,
)
from src.research.benchmark_residual_trend import (
    DEFAULT_LOOKBACK_SESSIONS,
    DEFAULT_SKIP_RECENT_SESSIONS,
    BenchmarkResidualTrendResult,
    compute_benchmark_residual_trend,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.risk_control_variants import (
    RiskVariantSpec,
    VARIANT_TOP3_BENCHMARK_TREND,
    evaluate_risk_control_variant,
)
from src.research.selection_tail_diagnostics import (
    compute_selection_tail_diagnostics,
    summarize_window_diagnostics,
)

SCHEMA_VERSION = "1.0"
CANDIDATE_ID = "factor:qqq_residual_trend_quality:lookback126_skip10"
ONE_DAY_RETURN_EXPR = "$close/Ref($close,1)-1"
DEFAULT_SOURCE_DIR = Path("artifacts/evidence/candidate_v2_ndx_window_start")
DEFAULT_HOLDOUT_DIR = Path("artifacts/evidence/candidate_v2_top3_holdout")
DEFAULT_OUTPUT_DIR = Path("artifacts/evidence/ndx_residual_trend_quality")
REQUIRED_FULL_WINDOWS = 4
MIN_SCORE_COVERAGE = 0.90
MIN_POSITIVE_EXCESS_WINDOWS = 3
MIN_POSITIVE_TOP3_PERIOD_RATIO = 0.55


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _validate_source_flags(payload: dict[str, Any], *, context: str) -> None:
    for key, expected in (
        ("research_only", True),
        ("promotion_eligible", False),
        ("trade_ready", False),
    ):
        if payload.get(key) is not expected:
            raise ValueError(f"{context} must declare {key}={expected!r}")


def _load_source_windows(
    source_dir: Path,
    holdout_dir: Path,
    *,
    provider_identity: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    source_manifest_path = source_dir / "evidence_manifest.json"
    source_aggregate_path = source_dir / "aggregate.json"
    holdout_manifest_path = holdout_dir / "evidence_manifest.json"
    holdout_frozen_path = holdout_dir / "frozen_gain5.json"

    source_manifest = _read_json(source_manifest_path)
    source_aggregate_wrapper = _read_json(source_aggregate_path)
    holdout_manifest = _read_json(holdout_manifest_path)
    holdout_frozen = _read_json(holdout_frozen_path)
    _validate_source_flags(source_manifest, context="NDX source manifest")
    _validate_source_flags(holdout_manifest, context="holdout manifest")
    _validate_source_flags(holdout_frozen["coverage_meta"], context="holdout window")

    if source_manifest.get("provider_identity_sha256") != provider_identity:
        raise ValueError("NDX source evidence provider identity mismatch")
    holdout_provider = holdout_manifest.get("provider")
    if (
        not isinstance(holdout_provider, dict)
        or holdout_provider.get("identity_sha256") != provider_identity
    ):
        raise ValueError("holdout evidence provider identity mismatch")
    if holdout_manifest.get("single_window_only") is not True:
        raise ValueError("holdout source must remain single_window_only")
    if holdout_manifest.get("falsification_only") is not True:
        raise ValueError("holdout source must remain falsification_only")

    source_aggregate = source_aggregate_wrapper.get("aggregate")
    if not isinstance(source_aggregate, dict):
        raise ValueError("NDX source aggregate payload is missing")
    window_paths = sorted((source_dir / "per_window").glob("*.json"))
    if len(window_paths) != REQUIRED_FULL_WINDOWS:
        raise ValueError(
            f"expected {REQUIRED_FULL_WINDOWS} complete NDX source windows"
        )
    windows = [_read_json(path) for path in window_paths]
    windows.append(holdout_frozen)
    labels = [str(item.get("window", {}).get("label", "")) for item in windows]
    if len(labels) != len(set(labels)) or any(not label for label in labels):
        raise ValueError("source window labels must be unique and non-empty")
    if sum(label.endswith("_partial") for label in labels) != 1:
        raise ValueError("source evidence must contain exactly one partial window")
    for payload in windows:
        if payload.get("skipped") is True:
            raise ValueError("source evidence cannot contain skipped windows")
        coverage = payload.get("coverage_meta")
        if not isinstance(coverage, dict):
            raise ValueError("source window is missing coverage_meta")
        if coverage.get("oos_membership_point_in_time") is not True:
            raise ValueError("source OOS membership must be point-in-time")

    hashed_paths = [
        source_manifest_path,
        source_aggregate_path,
        holdout_manifest_path,
        holdout_frozen_path,
        *window_paths,
    ]
    hashes = {
        str(path).replace("\\", "/"): _sha256_file(path)
        for path in hashed_paths
    }
    return windows, source_aggregate, hashes


def _slice_dates(
    frame: pd.DataFrame,
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    dates = frame.index.get_level_values("datetime")
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    sliced = frame.loc[mask].copy()
    sliced.attrs.update(frame.attrs)
    return sliced


def _load_residual_signal(
    symbols: list[str],
    *,
    history_start: str,
    test_start: str,
    test_end: str,
    benchmark: str,
) -> BenchmarkResidualTrendResult:
    from qlib.data import D

    stock_daily = D.features(
        symbols,
        [ONE_DAY_RETURN_EXPR],
        start_time=history_start,
        end_time=test_end,
    )
    stock_daily = _normalize_index(stock_daily)
    stock_daily.columns = ["return"]

    benchmark_daily = D.features(
        [benchmark],
        [ONE_DAY_RETURN_EXPR],
        start_time=history_start,
        end_time=test_end,
    )
    benchmark_daily = _normalize_index(benchmark_daily)
    benchmark_daily.columns = ["return"]
    if benchmark not in set(
        benchmark_daily.index.get_level_values("instrument")
    ):
        raise ValueError(f"benchmark daily returns missing {benchmark}")
    benchmark_series = benchmark_daily.xs(
        benchmark,
        level="instrument",
    )["return"]

    result = compute_benchmark_residual_trend(
        stock_daily,
        benchmark_series,
        benchmark=benchmark,
        lookback_sessions=DEFAULT_LOOKBACK_SESSIONS,
        skip_recent_sessions=DEFAULT_SKIP_RECENT_SESSIONS,
    )
    return BenchmarkResidualTrendResult(
        score=_slice_dates(result.score, start=test_start, end=test_end),
        beta=_slice_dates(result.beta, start=test_start, end=test_end),
        residual_mean=_slice_dates(
            result.residual_mean,
            start=test_start,
            end=test_end,
        ),
        residual_volatility=_slice_dates(
            result.residual_volatility,
            start=test_start,
            end=test_end,
        ),
    )


def _score_coverage(
    scores: pd.DataFrame,
    *,
    rebalance_dates: list[str],
    n_symbols: int,
) -> dict[str, Any]:
    threshold = max(FROZEN_TOP_N, math.ceil(n_symbols * MIN_SCORE_COVERAGE))
    per_date: list[dict[str, Any]] = []
    for raw_date in rebalance_dates:
        date = pd.Timestamp(raw_date)
        try:
            values = scores.xs(date, level="datetime")["score"]
        except KeyError:
            finite_count = 0
        else:
            finite_count = int(np.isfinite(values.to_numpy(dtype=float)).sum())
        per_date.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "finite_scores": finite_count,
                "requested_symbols": n_symbols,
                "coverage_ratio": finite_count / n_symbols,
                "passes": finite_count >= threshold,
            }
        )
    if not per_date:
        raise ValueError("source window has no rebalance dates")
    failed = [item for item in per_date if not item["passes"]]
    return {
        "minimum_required_ratio": MIN_SCORE_COVERAGE,
        "minimum_required_count": threshold,
        "minimum_observed_ratio": min(
            item["coverage_ratio"] for item in per_date
        ),
        "mean_observed_ratio": float(
            np.mean([item["coverage_ratio"] for item in per_date])
        ),
        "all_rebalance_dates_pass": not failed,
        "failed_dates": failed,
        "per_date": per_date,
    }


def _exposure_diagnostics(
    signal: BenchmarkResidualTrendResult,
    tail_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    selected_betas: list[float] = []
    universe_betas: list[float] = []
    selected_residual_volatility: list[float] = []
    universe_residual_volatility: list[float] = []
    score_beta_rank_correlations: list[float] = []

    for period in tail_diagnostics.get("periods", []):
        date = pd.Timestamp(period["date"])
        selected = [
            str(item["symbol"]) for item in period.get("selected_holdings", [])
        ]
        try:
            beta = signal.beta.xs(date, level="datetime")["beta"].dropna()
            residual_vol = signal.residual_volatility.xs(
                date,
                level="datetime",
            )["residual_volatility"].dropna()
            scores = signal.score.xs(date, level="datetime")["score"].dropna()
        except KeyError:
            continue

        selected_beta = beta.reindex(selected).dropna()
        selected_vol = residual_vol.reindex(selected).dropna()
        if len(selected_beta):
            selected_betas.append(float(selected_beta.mean()))
        if len(beta):
            universe_betas.append(float(beta.mean()))
        if len(selected_vol):
            selected_residual_volatility.append(float(selected_vol.mean()))
        if len(residual_vol):
            universe_residual_volatility.append(float(residual_vol.mean()))
        common = scores.index.intersection(beta.index)
        if len(common) >= 5:
            correlation = scores.loc[common].corr(
                beta.loc[common],
                method="spearman",
            )
            if np.isfinite(correlation):
                score_beta_rank_correlations.append(float(correlation))

    def mean(values: list[float]) -> float | None:
        return float(np.mean(values)) if values else None

    selected_beta_mean = mean(selected_betas)
    universe_beta_mean = mean(universe_betas)
    selected_vol_mean = mean(selected_residual_volatility)
    universe_vol_mean = mean(universe_residual_volatility)
    return {
        "selected_top3_mean_beta": selected_beta_mean,
        "universe_mean_beta": universe_beta_mean,
        "selected_minus_universe_beta": (
            selected_beta_mean - universe_beta_mean
            if selected_beta_mean is not None and universe_beta_mean is not None
            else None
        ),
        "selected_top3_mean_residual_volatility": selected_vol_mean,
        "universe_mean_residual_volatility": universe_vol_mean,
        "selected_minus_universe_residual_volatility": (
            selected_vol_mean - universe_vol_mean
            if selected_vol_mean is not None and universe_vol_mean is not None
            else None
        ),
        "mean_score_beta_rank_correlation": mean(
            score_beta_rank_correlations
        ),
        "n_rebalance_periods": len(tail_diagnostics.get("periods", [])),
    }


def _source_reference(source: dict[str, Any]) -> dict[str, Any]:
    tail = source["selection_tail_diagnostics"]["aggregate"]
    candidate = source["candidate_v2"]
    return {
        "candidate": source["candidate"],
        "total_return": candidate["total_return"],
        "benchmark_return": candidate["benchmark_return"],
        "relative_excess_return": candidate["relative_excess_return"],
        "sharpe_ratio": candidate["sharpe_ratio"],
        "max_drawdown": candidate["max_drawdown"],
        "icir": source["score_diagnostics"]["ic_ir"],
        "rank_icir": source["score_diagnostics"]["rank_ic_ir"],
        "rebalance_top3_spread": tail["mean_spread"],
        "positive_top3_spread_ratio": tail["positive_spread_ratio"],
    }


def _evaluate_window(
    source: dict[str, Any],
    *,
    history_start: str,
    benchmark: str,
) -> dict[str, Any]:
    from qlib.data import D

    window = source["window"]
    coverage_meta = source["coverage_meta"]
    symbols = [str(item) for item in coverage_meta["oos_test_symbols"]]
    rebalance_dates = [
        str(item["date"])
        for item in source["selection_tail_diagnostics"]["periods"]
    ]
    signal = _load_residual_signal(
        symbols,
        history_start=history_start,
        test_start=window["test_start"],
        test_end=window["test_end"],
        benchmark=benchmark,
    )
    coverage = _score_coverage(
        signal.score,
        rebalance_dates=rebalance_dates,
        n_symbols=len(symbols),
    )
    if not coverage["all_rebalance_dates_pass"]:
        raise ValueError(
            f"{window['label']} residual-trend score coverage failed"
        )

    raw_returns = D.features(
        symbols,
        [CANONICAL_10D_RETURN_EXPR],
        start_time=window["test_start"],
        end_time=window["test_end"],
    )
    raw_returns = _normalize_index(raw_returns)
    raw_returns.columns = ["return"]
    raw_returns.attrs["provenance"] = "raw_forward_return"
    raw_returns.attrs["horizon"] = 10
    raw_returns.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    benchmark_returns = _load_benchmark_returns(
        benchmark,
        window["test_start"],
        window["test_end"],
    )
    benchmark_trend = _load_benchmark_trend(
        benchmark,
        window["test_start"],
        window["test_end"],
    )
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=FROZEN_TOP_N,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=FROZEN_EXPOSURE,
    )
    report = evaluate_risk_control_variant(
        signal.score,
        raw_returns,
        benchmark_returns,
        spec=spec,
        benchmark_trend=benchmark_trend,
        rebalance_days=10,
        cost_bps=FROZEN_COST_BPS,
    )
    tail = compute_selection_tail_diagnostics(
        signal.score,
        raw_returns,
        report,
        top_n=FROZEN_TOP_N,
    )
    tail["window_label"] = window["label"]
    portfolio = report.to_dict()
    portfolio.pop("period_details", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "ndx_residual_trend_quality_window",
        "research_only": True,
        "diagnostic_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "window": window,
        "partial_window": str(window["label"]).endswith("_partial"),
        "candidate": CANDIDATE_ID,
        "signal_contract": {
            "benchmark": benchmark,
            "one_day_return_expression": ONE_DAY_RETURN_EXPR,
            "lookback_sessions": DEFAULT_LOOKBACK_SESSIONS,
            "skip_recent_sessions": DEFAULT_SKIP_RECENT_SESSIONS,
            "orientation": "higher_residual_trend_quality_is_better",
            "parameter_search_performed": False,
            "uses_future_returns": False,
        },
        "score_coverage": coverage,
        "score_diagnostics": _compute_score_diagnostics(
            signal.score,
            raw_returns,
        ),
        "selection_tail_diagnostics": tail,
        "risk_exposure_diagnostics": _exposure_diagnostics(signal, tail),
        "portfolio": portfolio,
        "source_candidate_reference": _source_reference(source),
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
    }


def _compound(values: list[float]) -> float:
    return float(np.prod([1.0 + value for value in values]) - 1.0)


def _mean(values: list[float]) -> float:
    finite = [float(value) for value in values if np.isfinite(value)]
    if not finite:
        raise ValueError("cannot aggregate an empty finite metric")
    return float(np.mean(finite))


def aggregate_window_reports(
    reports: list[dict[str, Any]],
    *,
    source_aggregate: dict[str, Any],
) -> dict[str, Any]:
    full = [item for item in reports if not item["partial_window"]]
    partial = [item for item in reports if item["partial_window"]]
    if len(full) != REQUIRED_FULL_WINDOWS or len(partial) != 1:
        raise ValueError("aggregate requires four full windows and one partial")

    portfolio_returns = [
        float(item["portfolio"]["total_return"]) for item in full
    ]
    benchmark_returns = [
        float(item["portfolio"]["benchmark_return"]) for item in full
    ]
    relative_excess = [
        float(item["portfolio"]["relative_excess_return"]) for item in full
    ]
    candidate_total = _compound(portfolio_returns)
    benchmark_total = _compound(benchmark_returns)
    compounded_relative_excess = (
        (1.0 + candidate_total) / (1.0 + benchmark_total) - 1.0
    )
    tail = summarize_window_diagnostics(
        [item["selection_tail_diagnostics"] for item in full]
    )
    worst_drawdown = min(
        float(item["portfolio"]["max_drawdown"]) for item in full
    )
    positive_excess_windows = sum(value > 0.0 for value in relative_excess)
    minimum_score_coverage = min(
        float(item["score_coverage"]["minimum_observed_ratio"])
        for item in full
    )
    full_checks = {
        "exactly_four_complete_windows": len(full) == REQUIRED_FULL_WINDOWS,
        "score_coverage": minimum_score_coverage >= MIN_SCORE_COVERAGE,
        "positive_excess_windows": (
            positive_excess_windows >= MIN_POSITIVE_EXCESS_WINDOWS
        ),
        "positive_compounded_relative_excess": (
            compounded_relative_excess > 0.0
        ),
        "drawdown_floor": worst_drawdown >= MAX_DRAWDOWN_GATE,
        "positive_top3_spread": float(tail["mean_spread"]) > 0.0,
        "top3_period_consistency": (
            float(tail["mean_positive_spread_ratio"])
            >= MIN_POSITIVE_TOP3_PERIOD_RATIO
        ),
    }

    stress = partial[0]
    stress_source = stress["source_candidate_reference"]
    stress_checks = {
        "positive_relative_excess": (
            float(stress["portfolio"]["relative_excess_return"]) > 0.0
        ),
        "relative_excess_improved_vs_frozen": (
            float(stress["portfolio"]["relative_excess_return"])
            > float(stress_source["relative_excess_return"])
        ),
        "drawdown_not_worse_than_frozen": (
            float(stress["portfolio"]["max_drawdown"])
            >= float(stress_source["max_drawdown"])
        ),
        "top3_spread_improved_vs_frozen": (
            float(
                stress["selection_tail_diagnostics"]["aggregate"][
                    "mean_spread"
                ]
            )
            > float(stress_source["rebalance_top3_spread"])
        ),
    }
    supported = all(full_checks.values()) and all(stress_checks.values())
    source_candidate = source_aggregate["candidate_v2"]
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "ndx_residual_trend_quality_aggregate",
        "research_only": True,
        "diagnostic_only": True,
        "same_oos_evidence_observed_before_hypothesis": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "candidate": CANDIDATE_ID,
        "n_complete_windows": len(full),
        "n_partial_stress_windows": len(partial),
        "complete_windows": {
            "compounded_total_return": candidate_total,
            "compounded_benchmark_return": benchmark_total,
            "compounded_relative_excess_return": (
                compounded_relative_excess
            ),
            "positive_excess_windows": positive_excess_windows,
            "mean_sharpe": _mean(
                [float(item["portfolio"]["sharpe_ratio"]) for item in full]
            ),
            "worst_drawdown": worst_drawdown,
            "mean_icir": _mean(
                [float(item["score_diagnostics"]["ic_ir"]) for item in full]
            ),
            "mean_rank_icir": _mean(
                [
                    float(item["score_diagnostics"]["rank_ic_ir"])
                    for item in full
                ]
            ),
            "mean_daily_quintile_spread": _mean(
                [
                    float(
                        item["score_diagnostics"][
                            "top_bottom_spread_mean"
                        ]
                    )
                    for item in full
                ]
            ),
            "selection_tail_diagnostics": tail,
            "minimum_score_coverage": minimum_score_coverage,
            "mean_selected_minus_universe_beta": _mean(
                [
                    float(
                        item["risk_exposure_diagnostics"][
                            "selected_minus_universe_beta"
                        ]
                    )
                    for item in full
                ]
            ),
        },
        "frozen_candidate_reference": {
            "compounded_total_return": source_candidate[
                "compounded_total_return"
            ],
            "compounded_benchmark_return": source_candidate[
                "compounded_benchmark_return"
            ],
            "compounded_relative_excess_return": source_candidate[
                "compounded_relative_excess_return"
            ],
            "positive_excess_windows": source_candidate[
                "positive_excess_windows"
            ],
            "mean_sharpe": source_candidate["mean_sharpe"],
            "worst_drawdown": source_candidate["worst_drawdown"],
        },
        "partial_stress_window": {
            "window": stress["window"]["label"],
            "candidate": stress["portfolio"],
            "frozen_reference": stress_source,
            "selection_tail": stress[
                "selection_tail_diagnostics"
            ]["aggregate"],
            "checks": stress_checks,
        },
        "predeclared_checks": {
            "complete_windows": full_checks,
            "partial_stress": stress_checks,
        },
        "failed_checks": [
            f"complete_windows.{key}"
            for key, passed in full_checks.items()
            if not passed
        ]
        + [
            f"partial_stress.{key}"
            for key, passed in stress_checks.items()
            if not passed
        ],
        "hypothesis_supported_for_fresh_validation": supported,
        "decision": (
            "residual_trend_quality_supported_for_fresh_validation"
            if supported
            else "residual_trend_quality_not_supported"
        ),
    }


def run(
    root: Path,
    *,
    data_root: Path,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    holdout_dir: Path = DEFAULT_HOLDOUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    benchmark: str = "QQQ",
) -> dict[str, Any]:
    root = root.resolve()
    data_root = data_root.resolve()
    source_dir = source_dir if source_dir.is_absolute() else root / source_dir
    holdout_dir = (
        holdout_dir if holdout_dir.is_absolute() else root / holdout_dir
    )
    output_dir = (
        output_dir if output_dir.is_absolute() else root / output_dir
    )

    provider_manifest = _verify_us_provider(data_root)
    provider_identity = str(provider_manifest["provider_identity_sha256"])
    sources, source_aggregate, source_hashes = _load_source_windows(
        source_dir,
        holdout_dir,
        provider_identity=provider_identity,
    )

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(data_root, "us"))
    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market="us",
            provider_uri_default=provider_uri,
        )
    )

    history_start = min(
        str(item["coverage_meta"]["aligned_train_start"]) for item in sources
    )
    per_window_dir = output_dir / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    expected_names: set[str] = set()
    for source in sorted(
        sources,
        key=lambda item: str(item["window"]["test_start"]),
    ):
        report = _evaluate_window(
            source,
            history_start=history_start,
            benchmark=benchmark,
        )
        label = str(report["window"]["label"])
        expected_names.add(f"{label}.json")
        _write_json(per_window_dir / f"{label}.json", report)
        reports.append(report)
        print(
            f"{label}: rel_excess="
            f"{report['portfolio']['relative_excess_return']:.4f} "
            f"drawdown={report['portfolio']['max_drawdown']:.4f} "
            f"top3_spread="
            f"{report['selection_tail_diagnostics']['aggregate']['mean_spread']:.4f}"
        )
    for stale in per_window_dir.glob("*.json"):
        if stale.name not in expected_names:
            stale.unlink()

    aggregate = aggregate_window_reports(
        reports,
        source_aggregate=source_aggregate,
    )
    aggregate_path = output_dir / "aggregate.json"
    _write_json(aggregate_path, aggregate)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "ndx_residual_trend_quality",
        "research_only": True,
        "diagnostic_only": True,
        "same_oos_evidence_observed_before_hypothesis": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "candidate": CANDIDATE_ID,
        "parameter_grid_searched": False,
        "orientation_selected_after_evaluation": False,
        "signal_contract": {
            "benchmark": benchmark,
            "one_day_return_expression": ONE_DAY_RETURN_EXPR,
            "lookback_sessions": DEFAULT_LOOKBACK_SESSIONS,
            "skip_recent_sessions": DEFAULT_SKIP_RECENT_SESSIONS,
            "orientation": "higher_residual_trend_quality_is_better",
            "uses_future_returns": False,
        },
        "portfolio_contract": {
            "top_n": FROZEN_TOP_N,
            "cost_bps": FROZEN_COST_BPS,
            "negative_benchmark_trend_exposure": FROZEN_EXPOSURE,
            "rebalance_sessions": 10,
        },
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
        "provider_uri": provider_uri,
        "provider_identity_sha256": provider_identity,
        "source_evidence_hashes": source_hashes,
        "aggregate_artifact": aggregate_path.name,
        "per_window_artifacts": [
            f"per_window/{report['window']['label']}.json"
            for report in reports
        ],
        "decision": aggregate["decision"],
    }
    manifest_path = output_dir / "evidence_manifest.json"
    _write_json(manifest_path, manifest)
    print(f"aggregate: {aggregate_path}")
    print(f"manifest: {manifest_path}")
    print(f"decision: {aggregate['decision']}")
    print("promotion_eligible=false")
    print("trade_ready=false")
    return {
        "aggregate": aggregate,
        "manifest": manifest,
        "aggregate_path": str(aggregate_path),
        "manifest_path": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Isolated repaired-provider data root",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Existing repaired NDX evidence directory",
    )
    parser.add_argument(
        "--holdout-dir",
        type=Path,
        default=DEFAULT_HOLDOUT_DIR,
        help="Existing 2026H1 holdout evidence directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output evidence directory",
    )
    parser.add_argument("--benchmark", default="QQQ")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        args.root,
        data_root=args.data_root,
        source_dir=args.source_dir,
        holdout_dir=args.holdout_dir,
        output_dir=args.output_dir,
        benchmark=args.benchmark,
    )


if __name__ == "__main__":
    main()
