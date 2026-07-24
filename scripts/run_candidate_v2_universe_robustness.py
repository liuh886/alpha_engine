"""Run frozen candidate_v2 across nested 10/50/100-symbol US cohorts.

This runner evaluates the exact PR #175 frozen candidate — 50/50 daily-ranker +
inverted 10D momentum score, Top-3 equal weight, 20 bps cash-inclusive one-way
turnover, 50% gross exposure when QQQ historical 20D return is negative — across
nested expanding US universes without tuning any model, blend, trend threshold,
exposure level, top-k, factor, or gate.

Outputs are written under ``artifacts/evidence/candidate_v2_universe_robustness/``:

* ``coverage_manifest.json`` — per-cohort coverage report with fail-closed results.
* ``per_window/`` — one JSON per cohort × window with evaluation metrics and
  score diagnostics (IC, ICIR, Rank IC, positive IC ratio, top-bottom spread).
* ``per_cohort_aggregate.json`` — aggregated metrics per cohort.
* ``cross_universe_summary.json`` — explicit robustness decision across all cohorts.

The runner is **research_only**, **promotion_eligible=false**, **trade_ready=false**
and documents static-current-membership / survivorship bias.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.core.metrics import compute_ic_series
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerFeatureGroup,
)
from src.research.risk_control_variants import (
    RiskVariantSpec,
    RiskVariantReport,
    VARIANT_TOP3_BENCHMARK_TREND,
    evaluate_risk_control_variant,
)
from src.research.selection_tail_diagnostics import (
    compute_selection_tail_diagnostics,
    summarize_window_diagnostics,
)
from src.research.rolling_windows import (
    purge_training_tail,
)
from src.research.stable_signal_blend import BlendWeight, build_two_signal_blend
from src.research.universe_robustness import (
    UniverseSpec,
    filter_universe_by_coverage,
    load_symbol_date_coverage,
    validate_no_nan_inputs,
)
from src.research.market_data_alignment import get_aligned_windows
from src.research.vectorized_backtest import compute_ic_vectorized

# ══════════════════════════════════════════════════════════════════════════════
# Frozen PR #175 configuration — DO NOT TUNE
# ══════════════════════════════════════════════════════════════════════════════

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
FROZEN_BLEND_WEIGHT = BlendWeight(ranker_weight=0.50, momentum_weight=0.50)
FROZEN_RANKER_NAME = "lgbm:daily_ranker:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05"
FROZEN_COST_BPS = 20.0
FROZEN_TOP_N = 3
FROZEN_EXPOSURE = 0.5
REQUIRED_WINDOWS = 4
MIN_POSITIVE_EXCESS_WINDOWS = 3
MIN_COMPOUNDED_RELATIVE_EXCESS = 0.30
MAX_DRAWDOWN_GATE = -0.15

# Symbols to exclude from tradable universes (benchmarks, not investable).
EXCLUDED_SYMBOLS: frozenset[str] = frozenset({"QQQ", "SPY", "SPX", "^GSPC", "NDX", "^IXIC"})

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _load_session(root: Path) -> dict[str, Any]:
    """Load the experiment session from the project root."""
    path = root / "data" / "session_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "market": "us",
        "symbols": [
            "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN",
            "META", "TSLA", "AVGO", "COST", "NFLX",
        ],
        "benchmark": "QQQ",
        "train_start": "2021-01-01",
        "test_end": "2026-06-18",
        "topk": 3,
    }


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        frame = frame.swaplevel().sort_index()
    return frame


def _candidate_id() -> str:
    return (
        "blend:ranker_momentum:momentum_volatility_volume:"
        "gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5"
    )


def _exclude_benchmark_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    """Remove QQQ, SPY, and other benchmark symbols from the tradable set."""
    return tuple(s for s in symbols if s.upper() not in EXCLUDED_SYMBOLS)


def _load_us_provider_symbols(data_root: Path) -> list[str]:
    """Load US-only symbols from the market-specific provider's instrument file."""
    from src.data.market_provider import market_provider_path

    provider_dir = market_provider_path(data_root, "us")
    path = provider_dir / "instruments" / "us.txt"
    if not path.exists():
        raise ValueError(f"US instrument metadata not found: {path}")
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split("\t")
        if parts and parts[0]:
            symbols.append(parts[0])
    result = sorted(set(_exclude_benchmark_symbols(tuple(symbols))))
    if not result:
        raise ValueError("US instrument metadata contains no tradable symbols")
    return result


def _verify_us_provider(data_root: Path) -> dict[str, Any]:
    """Verify the US market-specific provider and return its manifest.

    Uses ``market_provider_path`` and ``load_provider_manifest`` from
    ``src.data.market_provider`` to check that the provider directory
    contains a valid manifest for market=us with matching file hashes.

    Raises
    ------
    FileNotFoundError
        If the provider directory or manifest is missing.
    ValueError
        If the manifest market field is not ``us`` or file hashes mismatch.
    """
    from src.data.market_provider import market_provider_path, load_provider_manifest

    provider_dir = market_provider_path(data_root, "us")
    return load_provider_manifest(
        provider_dir,
        expected_market="us",
        required=True,
        verify_files=True,
    )


def _build_nested_cohorts(
    canonical_symbols: list[str],
    provider_symbols: list[str],
    coverage: dict[str, dict[str, Any]],
    *,
    available_end: str,
) -> tuple[list[UniverseSpec], dict[str, str]]:
    """Build exact nested 10/50/100 US cohorts from actual coverage.

    Symbols must have real observations through *available_end*.  Extras are
    ordered by first valid date and symbol so cohort membership is deterministic.
    Each cohort's aligned train start is the latest first-valid date among its
    members.
    """
    canonical = list(dict.fromkeys(_exclude_benchmark_symbols(tuple(canonical_symbols))))
    if len(canonical) != 10:
        raise ValueError(f"canonical cohort must contain exactly 10 symbols, got {len(canonical)}")

    end_ts = pd.Timestamp(available_end)

    def usable(symbol: str) -> bool:
        record = coverage.get(symbol, {})
        first = record.get("first_valid_date")
        last = record.get("last_valid_date")
        return (
            first is not None
            and last is not None
            and int(record.get("observations", 0)) > 0
            and pd.Timestamp(last) >= end_ts - pd.Timedelta(days=10)
        )

    missing_canonical = [symbol for symbol in canonical if not usable(symbol)]
    if missing_canonical:
        raise ValueError(
            "canonical symbols lack usable coverage through available_end: "
            f"{missing_canonical}"
        )

    extras = [symbol for symbol in provider_symbols if symbol not in canonical and usable(symbol)]
    extras.sort(
        key=lambda symbol: (
            pd.Timestamp(coverage[symbol]["first_valid_date"]),
            symbol,
        )
    )
    ordered = canonical + extras

    specs: list[UniverseSpec] = []
    aligned_starts: dict[str, str] = {}
    for size, name in (
        (10, "default_10_symbols"),
        (50, "expanded_50_symbols"),
        (100, "expanded_100_symbols"),
    ):
        if len(ordered) < size:
            selected = tuple(ordered)
        else:
            selected = tuple(ordered[:size])
        specs.append(UniverseSpec(name=name, symbols=selected, min_symbols=size))
        if selected:
            aligned_starts[name] = max(
                str(coverage[symbol]["first_valid_date"]) for symbol in selected
            )

    return specs, aligned_starts


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


def _compute_score_diagnostics(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
) -> dict[str, Any]:
    """Compute IC, ICIR, Rank IC, positive IC ratio, and top-bottom spread.

    Uses raw forward returns directly — no processed labels.
    """
    mean_ic, ic_ir, positive_ic_ratio, ic_series = compute_ic_vectorized(
        scores,
        returns,
    )
    rank_ic_result = compute_ic_series(scores, returns, min_stocks=5)

    # Top-bottom spread (top vs bottom 20% by score per date)
    dates = sorted(set(
        scores.index.get_level_values("datetime").unique()
    ) & set(
        returns.index.get_level_values("datetime").unique()
    ))
    spread_values: dict[pd.Timestamp, float] = {}
    for date in dates:
        try:
            s = scores.xs(date, level="datetime")["score"]
            r = returns.xs(date, level="datetime")["return"]
        except KeyError:
            continue
        common = s.index.intersection(r.index)
        if len(common) < 10:
            continue
        s_common = s.loc[common]
        r_common = r.loc[common]
        n = len(common)
        top_n = max(1, n // 5)
        top_idx = s_common.nlargest(top_n).index
        bot_idx = s_common.nsmallest(top_n).index
        top_ret = r_common.loc[top_idx].mean()
        bot_ret = r_common.loc[bot_idx].mean()
        spread_values[date] = float(top_ret - bot_ret)

    spread_series = pd.Series(spread_values, name="TopBottomSpread")

    return {
        "ic_mean": mean_ic,
        # ``compute_ic_vectorized`` returns the daily values as a plain list
        # and uses population standard deviation for its ICIR denominator.
        "ic_std": float(np.std(ic_series)) if len(ic_series) else float("nan"),
        "ic_ir": ic_ir,
        "ic_pos_pct": positive_ic_ratio,
        "ic_n_days": len(ic_series),
        "rank_ic_mean": rank_ic_result["ic_mean"],
        "rank_ic_std": rank_ic_result["ic_std"],
        "rank_ic_ir": rank_ic_result["ic_ir"],
        "rank_ic_pos_pct": rank_ic_result["ic_pos_pct"],
        "rank_ic_n_days": rank_ic_result["n_days"],
        "top_bottom_spread_mean": float(spread_series.mean()) if len(spread_series) else float("nan"),
        "top_bottom_spread_std": float(spread_series.std()) if len(spread_series) else float("nan"),
        "top_bottom_spread_pos_pct": float((spread_series > 0).mean()) if len(spread_series) else float("nan"),
        "top_bottom_spread_n_days": len(spread_series),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Per-window evaluation
# ══════════════════════════════════════════════════════════════════════════════


def _evaluate_window(
    window: Any,
    symbols: list[str],
    benchmark: str,
    expression_columns: dict[str, str],
    feature_exprs: list[str],
    baseline_expr: str,
) -> dict[str, Any] | None:
    """Train frozen ranker, generate blend score, evaluate candidate_v2."""
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

    # Validate — skip window if all-NaN or zero-filled
    ok, reason = validate_no_nan_inputs(
        features_train, context=f"features train/{window.label}"
    )
    if not ok:
        return {"window": window.to_dict(), "skipped": True, "skip_reason": reason}

    # Train frozen ranker with expanding history
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

    # Load momentum baseline for OOS test period
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

    # Generate frozen 50/50 blend
    blend = build_two_signal_blend(
        ranker_scores,
        momentum,
        weight=FROZEN_BLEND_WEIGHT,
        invert_momentum=True,
    )

    # Load benchmark returns & trend for OOS period
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
        return {"window": window.to_dict(), "skipped": True, "skip_reason": "empty benchmark returns"}

    # ── Evaluate candidate_v2: top3_benchmark_trend_filter ────────────────
    candidate_v2_spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=FROZEN_TOP_N,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=FROZEN_EXPOSURE,
    )
    variant_report = evaluate_risk_control_variant(
        blend,
        returns_test,
        benchmark_returns,
        spec=candidate_v2_spec,
        benchmark_trend=benchmark_trend,
        rebalance_days=10,
        cost_bps=FROZEN_COST_BPS,
    )

    # ── Score diagnostics on blend score ──────────────────────────────────
    diagnostics = _compute_score_diagnostics(blend, returns_test)

    # ── Selection tail diagnostics ────────────────────────────────────────
    tail_diag = compute_selection_tail_diagnostics(
        blend,
        returns_test,
        variant_report,
        top_n=FROZEN_TOP_N,
    )
    tail_diag["window_label"] = window.label
    variant_payload = variant_report.to_dict()
    # The reconciled holding/portfolio period records are persisted once under
    # selection_tail_diagnostics.periods.  Avoid duplicating the same large
    # payload under candidate_v2.period_details in every evidence file.
    variant_payload.pop("period_details", None)

    return {
        "window": window.to_dict(),
        "candidate": _candidate_id(),
        "candidate_v2": variant_payload,
        "score_diagnostics": diagnostics,
        "selection_tail_diagnostics": tail_diag,
        "skipped": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Cohort-level aggregate
# ══════════════════════════════════════════════════════════════════════════════


def _aggregate_cohort(
    cohort_name: str,
    window_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate per-window results into a cohort-level summary."""
    valid = [p for p in window_payloads if not p.get("skipped", False)]
    n_windows = len(window_payloads)
    n_valid = len(valid)

    if n_valid == 0:
        return {
            "cohort": cohort_name,
            "n_windows_total": n_windows,
            "n_windows_evaluated": 0,
            "skipped": True,
            "skip_reason": "no valid windows in cohort",
        }

    # Extract candidate_v2 metrics from each window
    rel_excesses = [
        p["candidate_v2"]["relative_excess_return"] for p in valid
    ]
    sharpes = [p["candidate_v2"]["sharpe_ratio"] for p in valid]
    drawdowns = [p["candidate_v2"]["max_drawdown"] for p in valid]
    turnovers = [p["candidate_v2"]["turnover"] for p in valid]
    costs = [p["candidate_v2"]["costs"] for p in valid]
    gross_exposures = [p["candidate_v2"]["mean_gross_exposure"] for p in valid]
    # Compounded across windows
    all_period_returns = [r for p in valid for r in p["candidate_v2"]["period_returns"]]
    all_bench_returns = [r for p in valid for r in p["candidate_v2"]["benchmark_period_returns"]]
    compounded_portfolio = float(np.prod(1.0 + np.asarray(all_period_returns)) - 1.0) if all_period_returns else 0.0
    compounded_benchmark = float(np.prod(1.0 + np.asarray(all_bench_returns)) - 1.0) if all_bench_returns else 0.0
    compounded_rel_excess = (
        (1.0 + compounded_portfolio) / (1.0 + compounded_benchmark) - 1.0
        if compounded_benchmark > -1.0
        else 0.0
    )

    # Aggregate score diagnostics
    ic_irs = [p["score_diagnostics"]["ic_ir"] for p in valid]
    rank_ic_irs = [p["score_diagnostics"]["rank_ic_ir"] for p in valid]
    ic_means = [p["score_diagnostics"]["ic_mean"] for p in valid]
    rank_ic_means = [p["score_diagnostics"]["rank_ic_mean"] for p in valid]
    ic_pos_pcts = [p["score_diagnostics"]["ic_pos_pct"] for p in valid]
    spreads = [p["score_diagnostics"]["top_bottom_spread_mean"] for p in valid]

    def finite(values: list[float]) -> list[float]:
        return [value for value in values if np.isfinite(value)]

    mean_ic = float(np.mean(finite(ic_means))) if finite(ic_means) else float("nan")
    mean_ic_ir = float(np.mean(finite(ic_irs))) if finite(ic_irs) else float("nan")
    mean_rank_ic = (
        float(np.mean(finite(rank_ic_means))) if finite(rank_ic_means) else float("nan")
    )
    mean_rank_ic_ir = (
        float(np.mean(finite(rank_ic_irs))) if finite(rank_ic_irs) else float("nan")
    )
    mean_ic_pos_pct = (
        float(np.mean(finite(ic_pos_pcts))) if finite(ic_pos_pcts) else float("nan")
    )
    mean_spread = float(np.mean(finite(spreads))) if finite(spreads) else float("nan")
    positive_excess_windows = sum(1 for excess in rel_excesses if excess > 0)
    worst_drawdown = float(min(drawdowns))
    passes_gate = (
        n_valid == REQUIRED_WINDOWS
        and positive_excess_windows >= MIN_POSITIVE_EXCESS_WINDOWS
        and compounded_rel_excess > MIN_COMPOUNDED_RELATIVE_EXCESS
        and worst_drawdown >= MAX_DRAWDOWN_GATE
        and mean_ic_ir > 0
        and mean_rank_ic_ir > 0
        and mean_spread > 0
    )

    return {
        "cohort": cohort_name,
        "n_windows_total": n_windows,
        "n_windows_evaluated": n_valid,
        "skipped": False,
        "candidate": _candidate_id(),
        "candidate_v2": {
            "compounded_total_return": compounded_portfolio,
            "compounded_benchmark_return": compounded_benchmark,
            "compounded_relative_excess_return": compounded_rel_excess,
            "mean_relative_excess": float(np.mean(rel_excesses)),
            "mean_sharpe": float(np.mean(sharpes)),
            "worst_drawdown": worst_drawdown,
            "mean_drawdown": float(np.mean(drawdowns)),
            "mean_turnover": float(np.mean(turnovers)),
            "mean_costs": float(np.mean(costs)),
            "cost_bps": FROZEN_COST_BPS,
            "turnover_model": "cash_inclusive_one_way",
            "mean_gross_exposure": float(np.mean(gross_exposures)),
            "min_gross_exposure": float(min(gross_exposures)),
            "max_gross_exposure": float(max(gross_exposures)),
            "positive_excess_windows": positive_excess_windows,
            "passes_candidate_v2_gate": passes_gate,
        },
        "score_diagnostics": {
            "mean_ic": mean_ic,
            "mean_ic_ir": mean_ic_ir,
            "mean_rank_ic": mean_rank_ic,
            "mean_rank_ic_ir": mean_rank_ic_ir,
            "mean_ic_pos_pct": mean_ic_pos_pct,
            "mean_top_bottom_spread": mean_spread,
        },
        "selection_tail_diagnostics": summarize_window_diagnostics(
            [p.get("selection_tail_diagnostics", {}) for p in valid]
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Cross-universe summary with explicit robustness decision
# ══════════════════════════════════════════════════════════════════════════════


def _build_failure_diagnostics(
    cohort_aggregates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build selection-tail diagnostic evidence across expanded-universe cohorts.

    Returns a cross-cohort diagnostic report with per-cohort candidate_v2
    metrics, enriched tail summaries, and numeric deltas vs the base
    ``default_10_symbols`` cohort.
    """
    diags: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_selection_tail_diagnostics",
        "candidate": _candidate_id(),
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "cohorts": {},
    }

    default_agg = None
    default_tail = None

    for name in ("default_10_symbols", "expanded_50_symbols", "expanded_100_symbols"):
        agg = cohort_aggregates.get(name, {})
        if agg.get("skipped", False):
            diags["cohorts"][name] = {
                "status": "skipped",
                "skip_reason": agg.get("skip_reason", "unknown"),
                "deltas_vs_default_10_symbols": None,
            }
            continue

        cv2 = agg.get("candidate_v2", {})
        tail = agg.get("selection_tail_diagnostics", {})

        cohort_entry: dict[str, Any] = {
            "status": "evaluated",
            # Source key names match _aggregate_cohort output keys
            "compounded_relative_excess_return": cv2.get(
                "compounded_relative_excess_return"
            ),
            "compounded_total_return": cv2.get("compounded_total_return"),
            "compounded_benchmark_return": cv2.get("compounded_benchmark_return"),
            "worst_drawdown": cv2.get("worst_drawdown"),
            "tail_diagnostics": {
                "n_windows": tail.get("n_windows", 0),
                "n_periods_total": tail.get("n_periods_total", 0),
                "mean_spread": tail.get("mean_spread"),
                "mean_positive_spread_ratio": tail.get(
                    "mean_positive_spread_ratio"
                ),
                "mean_selected_realized_percentile": tail.get(
                    "mean_selected_realized_percentile"
                ),
                "mean_selected_above_median_ratio": tail.get(
                    "mean_selected_above_median_ratio"
                ),
                "mean_selected_positive_return_ratio": tail.get(
                    "mean_selected_positive_return_ratio"
                ),
                "total_turnover": tail.get("total_turnover"),
                "total_cost": tail.get("total_cost"),
                "worst_net_return_period": tail.get(
                    "worst_net_return_period"
                ),
                "worst_relative_excess_period": tail.get(
                    "worst_relative_excess_period"
                ),
                "worst_net_return_period_detail": tail.get(
                    "worst_net_return_period_detail"
                ),
                "worst_relative_excess_period_detail": tail.get(
                    "worst_relative_excess_period_detail"
                ),
                "symbol_contributions": tail.get("symbol_contributions"),
                "window_breakdown": tail.get("window_breakdown"),
            },
        }

        # Numeric deltas vs default_10_symbols
        if name == "default_10_symbols":
            default_agg = cv2
            default_tail = tail
            cohort_entry["deltas_vs_default_10_symbols"] = None
        elif default_agg is not None and default_tail is not None:
            deltas: dict[str, Any] = {}
            for key in (
                "compounded_relative_excess_return",
                "compounded_total_return",
                "compounded_benchmark_return",
                "worst_drawdown",
            ):
                val = cv2.get(key)
                base = default_agg.get(key)
                if (
                    val is not None
                    and base is not None
                    and np.isfinite(val)
                    and np.isfinite(base)
                ):
                    deltas[key] = val - base
                else:
                    deltas[key] = None
            for key in (
                "mean_spread",
                "mean_positive_spread_ratio",
                "mean_selected_realized_percentile",
                "mean_selected_above_median_ratio",
                "mean_selected_positive_return_ratio",
            ):
                val = tail.get(key)
                base = default_tail.get(key)
                if (
                    val is not None
                    and base is not None
                    and np.isfinite(val)
                    and np.isfinite(base)
                ):
                    deltas[key] = val - base
                else:
                    deltas[key] = None
            cohort_entry["deltas_vs_default_10_symbols"] = deltas

        diags["cohorts"][name] = cohort_entry

    return diags


def _cross_universe_summary(
    cohort_aggregates: dict[str, dict[str, Any]],
    coverage_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build cross-universe comparison and explicit robustness decision."""
    evaluated = {
        name: agg for name, agg in cohort_aggregates.items()
        if not agg.get("skipped", True)
    }
    skipped = [
        name for name, agg in cohort_aggregates.items()
        if agg.get("skipped", True)
    ]

    rows: list[dict[str, Any]] = []
    for name, agg in sorted(cohort_aggregates.items()):
        if agg.get("skipped", True):
            rows.append({
                "cohort": name,
                "status": "skipped",
                "skip_reason": agg.get("skip_reason", "unknown"),
            })
        else:
            cv2 = agg["candidate_v2"]
            diag = agg["score_diagnostics"]
            rows.append({
                "cohort": name,
                "status": "evaluated",
                "n_windows": agg["n_windows_evaluated"],
                "compounded_relative_excess": cv2["compounded_relative_excess_return"],
                "mean_sharpe": cv2["mean_sharpe"],
                "worst_drawdown": cv2["worst_drawdown"],
                "mean_turnover": cv2["mean_turnover"],
                "mean_costs": cv2["mean_costs"],
                "mean_gross_exposure": cv2["mean_gross_exposure"],
                "mean_ic_ir": diag["mean_ic_ir"],
                "mean_rank_ic_ir": diag["mean_rank_ic_ir"],
                "mean_ic_pos_pct": diag["mean_ic_pos_pct"],
                "mean_top_bottom_spread": diag["mean_top_bottom_spread"],
                "positive_excess_windows": cv2["positive_excess_windows"],
                "passes_candidate_v2_gate": cv2["passes_candidate_v2_gate"],
            })

    # ── Decision logic ────────────────────────────────────────────────────
    decision_status = "no_cohort_evaluated"
    robust = False
    degradation_note: str | None = None

    required_names = {
        "default_10_symbols",
        "expanded_50_symbols",
        "expanded_100_symbols",
    }
    if evaluated:
        missing = sorted(required_names - set(evaluated))
        failures: list[str] = []
        if missing:
            failures.append(f"missing required cohorts: {missing}")
        for name in sorted(required_names & set(evaluated)):
            aggregate = evaluated[name]
            candidate = aggregate["candidate_v2"]
            diagnostics = aggregate["score_diagnostics"]
            if aggregate["n_windows_evaluated"] != REQUIRED_WINDOWS:
                failures.append(
                    f"{name}: {aggregate['n_windows_evaluated']}/{REQUIRED_WINDOWS} windows"
                )
            if candidate["positive_excess_windows"] < MIN_POSITIVE_EXCESS_WINDOWS:
                failures.append(f"{name}: insufficient positive excess windows")
            if (
                candidate["compounded_relative_excess_return"]
                <= MIN_COMPOUNDED_RELATIVE_EXCESS
            ):
                failures.append(f"{name}: relative excess <= 30%")
            if candidate["worst_drawdown"] < MAX_DRAWDOWN_GATE:
                failures.append(f"{name}: drawdown below -15%")
            if diagnostics["mean_ic_ir"] <= 0:
                failures.append(f"{name}: non-positive ICIR")
            if diagnostics["mean_rank_ic_ir"] <= 0:
                failures.append(f"{name}: non-positive Rank ICIR")
            if diagnostics["mean_top_bottom_spread"] <= 0:
                failures.append(f"{name}: non-positive top-bottom spread")

        if failures:
            decision_status = "candidate_v2_not_robust_across_expanded_universes"
            degradation_note = "; ".join(failures)
        else:
            decision_status = "candidate_v2_robust_across_expanded_universes"
            robust = True

    return {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_universe_robustness",
        "candidate": _candidate_id(),
        "frozen_config": {
            "feature_group": FROZEN_FEATURE_GROUP.name,
            "calibration": {
                "n_gain_bins": FROZEN_CALIBRATION.n_gain_bins,
                "num_boost_round": FROZEN_CALIBRATION.num_boost_round,
                "num_leaves": FROZEN_CALIBRATION.num_leaves,
                "learning_rate": FROZEN_CALIBRATION.learning_rate,
            },
            "blend_weight": FROZEN_BLEND_WEIGHT.to_dict(),
            "top_n": FROZEN_TOP_N,
            "cost_bps": FROZEN_COST_BPS,
            "turnover_model": "cash_inclusive_one_way",
            "negative_benchmark_trend_exposure": FROZEN_EXPOSURE,
            "trend_filter_benchmark": "QQQ",
            "trend_lookback_days": 20,
        },
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "robustness_gate": {
            "required_cohorts": sorted(required_names),
            "required_windows_per_cohort": REQUIRED_WINDOWS,
            "min_positive_excess_windows": MIN_POSITIVE_EXCESS_WINDOWS,
            "min_compounded_relative_excess": MIN_COMPOUNDED_RELATIVE_EXCESS,
            "max_drawdown": MAX_DRAWDOWN_GATE,
            "require_positive_icir": True,
            "require_positive_rank_icir": True,
            "require_positive_top_bottom_spread": True,
        },
        "survivorship_bias_documented": True,
        "survivorship_bias_notes": (
            "Cohorts are constructed from static current Qlib instrument listings. "
            "Symbols that were delisted, acquired, or otherwise removed from the "
            "provider before the snapshot date are absent from all cohorts. "
            "No historical index-constituent point-in-time membership is applied. "
            "The fixed current-member cohorts therefore differ from a true "
            "point-in-time historical universe and can inflate relative performance. "
            "Results should be interpreted as an upper bound on strategy efficacy."
        ),
        "n_cohorts_total": len(cohort_aggregates),
        "n_cohorts_evaluated": len(evaluated),
        "n_cohorts_skipped": len(skipped),
        "skipped_cohorts": skipped,
        "cohort_rows": rows,
        "decision_status": decision_status,
        "candidate_v2_robust": robust,
        "degradation_note": degradation_note,
        "non_trade_ready_warning": (
            "Research evidence is not authorization for live trading or automated "
            "execution. Universe-robustness results are diagnostic only and do not "
            "constitute a promotion recommendation."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Main runner
# ══════════════════════════════════════════════════════════════════════════════


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    first_test_year: int = 2024,
    last_test_year: int = 2026,
) -> dict[str, Any]:
    """Execute the candidate_v2 universe-robustness experiment."""
    # Session config lives under --root. --data-root governs the Qlib provider URI.
    session = _load_session(root)
    market = str(session["market"])
    canonical_symbols = list(session["symbols"])
    benchmark = str(session["benchmark"])
    train_start = str(session["train_start"])
    test_end = str(session["test_end"])
    topk = int(session.get("topk", 3))

    # ── Qlib init with data-root: US-market-only provider ────────────────
    effective_data_root = data_root if data_root is not None else root

    # Verify the US market-specific provider manifest before loading any data.
    # The old data/watchlist provider mixed CN+US calendars, causing forward
    # return Ref($close, -10) to use a union calendar that misaligned US trading
    # sessions and corrupted selected returns.
    provider_manifest = _verify_us_provider(effective_data_root)
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(effective_data_root, "us"))

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market=market,
            provider_uri_default=provider_uri,
        )
    )
    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(start_time=train_start, end_time=test_end, freq="day")
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in configured session range")
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")

    # ── Build nested US-only universe cohorts from actual Qlib coverage ───
    provider_symbols = _load_us_provider_symbols(effective_data_root)
    all_coverage = load_symbol_date_coverage(
        provider_symbols,
        train_start,
        available_end,
    )
    if not all_coverage:
        raise ValueError("could not load US symbol coverage from Qlib")
    universes, aligned_starts = _build_nested_cohorts(
        canonical_symbols,
        provider_symbols,
        all_coverage,
        available_end=available_end,
    )

    # ── Output directories ────────────────────────────────────────────────
    base_out = root / "artifacts" / "evidence" / "candidate_v2_universe_robustness"
    per_window_dir = base_out / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)

    print("\nCandidate v2 Universe Robustness Experiment")
    print(f"  market:       {market}")
    print(f"  benchmark:    {benchmark}")
    print(f"  canonical:    {canonical_symbols}")
    print(f"  data-root:    {effective_data_root}")
    print(f"  provider:     {provider_uri}")
    print(f"  output:       {base_out}")
    print("  research_only: true")
    print("  promotion_eligible: false")
    print("  trade_ready: false")
    print()

    # ── Coverage check per cohort ─────────────────────────────────────────
    coverage_reports: dict[str, dict[str, Any]] = {}
    cohort_symbols: dict[str, list[str]] = {}

    for universe in universes:
        symbols_tuple = universe.symbols
        if not symbols_tuple:
            coverage_reports[universe.name] = {
                "universe_name": universe.name,
                "skipped": True,
                "sufficient": False,
                "retained_symbols": [],
                "skip_reason": "no symbols after excluding benchmarks",
            }
            cohort_symbols[universe.name] = []
            continue

        aligned_start = aligned_starts.get(universe.name)
        if aligned_start is None:
            raise ValueError(f"missing aligned train start for {universe.name}")
        date_coverage = load_symbol_date_coverage(
            list(symbols_tuple),
            aligned_start,
            available_end,
        )
        coverage = filter_universe_by_coverage(
            symbols_tuple,
            min_symbols=universe.min_symbols,
            date_range=(aligned_start, available_end),
            date_coverage_data=date_coverage,
        )
        coverage["universe_name"] = universe.name
        coverage["aligned_train_start"] = aligned_start
        coverage["requested_size"] = universe.min_symbols
        coverage_reports[universe.name] = coverage
        cohort_symbols[universe.name] = coverage["retained_symbols"]

        status = "SKIPPED" if coverage["skipped"] else "OK"
        print(f"  [{status}] {universe.name}: "
              f"{len(coverage['retained_symbols'])}/{len(symbols_tuple)} symbols covered")

    # Write coverage manifest
    coverage_path = base_out / "coverage_manifest.json"
    coverage_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "evidence_type": "candidate_v2_universe_robustness_coverage",
                "cohorts": coverage_reports,
                "canonical_symbols": canonical_symbols,
                "provider_us_symbol_count": len(provider_symbols),
                "provider": {
                    "uri": provider_uri,
                    "market": provider_manifest["market"],
                    "identity_sha256": provider_manifest["provider_identity_sha256"],
                    "calendar": {
                        "session_count": provider_manifest["calendar"]["session_count"],
                        "first_day": provider_manifest["calendar"]["first_day"],
                        "last_day": provider_manifest["calendar"]["last_day"],
                        "note": (
                            "US-market-only trading calendar. "
                            "No CN/HK holiday contamination. "
                            "Forward-return Ref($close, -10) uses consecutive US "
                            "trading sessions, not watchlist union calendar."
                        ),
                    },
                },
                "excluded_symbols": sorted(EXCLUDED_SYMBOLS),
                "aligned_train_starts": aligned_starts,
                "survivorship_bias_note": (
                    "Symbol coverage is assessed against static current Qlib "
                    "instrument listings. Delisted or acquired symbols are absent."
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    # ── Feature expressions ───────────────────────────────────────────────
    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    dollar_sign = chr(36)
    baseline_expr = f"{dollar_sign}close/Ref({dollar_sign}close,10)-1"

    # ── Per-cohort × per-window evaluation ────────────────────────────────
    cohort_aggregates: dict[str, dict[str, Any]] = {}
    windows_per_cohort: dict[str, int] = {}

    for universe in universes:
        name = universe.name
        symbols = cohort_symbols.get(name, [])
        coverage = coverage_reports.get(name, {})

        if coverage.get("skipped", True) or len(symbols) < max(2, topk):
            cohort_aggregates[name] = {
                "cohort": name,
                "n_windows_total": 0,
                "n_windows_evaluated": 0,
                "skipped": True,
                "skip_reason": coverage.get("skip_reason", "insufficient coverage"),
            }
            windows_per_cohort[name] = 0
            continue

        aligned_start = str(coverage["aligned_train_start"])
        windows = get_aligned_windows(
            aligned_start,
            available_end,
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        )
        windows_per_cohort[name] = len(windows)
        if len(windows) != REQUIRED_WINDOWS:
            cohort_aggregates[name] = {
                "cohort": name,
                "n_windows_total": len(windows),
                "n_windows_evaluated": 0,
                "skipped": True,
                "skip_reason": (
                    f"requires exactly {REQUIRED_WINDOWS} complete OOS windows, "
                    f"found {len(windows)}"
                ),
            }
            continue

        print(f"\n── {name} ({len(symbols)} symbols) ──")
        window_payloads: list[dict[str, Any]] = []

        for window in windows:
            print(
                f"  {window.label}  train={window.train_start}->{window.train_end}  "
                f"test={window.test_start}->{window.test_end}"
            )
            payload = _evaluate_window(
                window,
                symbols,
                benchmark,
                expression_columns,
                feature_exprs,
                baseline_expr,
            )
            if payload is None:
                continue

            window_payloads.append(payload)

            if payload.get("skipped"):
                print(f"    SKIPPED: {payload.get('skip_reason', 'unknown')}")
            else:
                cv2 = payload["candidate_v2"]
                diag = payload["score_diagnostics"]
                print(
                    f"    cv2: rel_xs={cv2['relative_excess_return']:.4f}  "
                    f"SR={cv2['sharpe_ratio']:.2f}  MDD={cv2['max_drawdown']:.4f}  "
                    f"gross={cv2['mean_gross_exposure']:.2f}  "
                    f"IC_IR={diag['ic_ir']:.3f}  Rank_IC_IR={diag['rank_ic_ir']:.3f}"
                )

            # Write per-window JSON
            out_path = per_window_dir / f"{name}_{window.label}.json"
            out_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )

        cohort_aggregates[name] = _aggregate_cohort(name, window_payloads)

    # ── Write per-cohort aggregate ────────────────────────────────────────
    cohort_agg_path = base_out / "per_cohort_aggregate.json"
    cohort_agg_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "evidence_type": "candidate_v2_universe_robustness_cohorts",
                "candidate": _candidate_id(),
                "research_only": True,
                "promotion_eligible": False,
                "trade_ready": False,
                "cohorts": cohort_aggregates,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )

    # ── Cross-universe summary ────────────────────────────────────────────
    summary = _cross_universe_summary(cohort_aggregates, coverage_reports)
    summary_path = base_out / "cross_universe_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    # ── Failure diagnostics (selection tail across cohorts) ───────────────
    failure_diags = _build_failure_diagnostics(cohort_aggregates)
    failure_path = base_out / "failure_diagnostics.json"
    failure_path.write_text(
        json.dumps(failure_diags, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    # ── Evidence manifest ─────────────────────────────────────────────────
    manifest = {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_universe_robustness",
        "candidate": _candidate_id(),
        "frozen_from_pr": 175,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "cost_bps": FROZEN_COST_BPS,
        "turnover_model": "cash_inclusive_one_way",
        "n_cohorts": len(universes),
        "n_cohorts_evaluated": sum(1 for a in cohort_aggregates.values() if not a.get("skipped", True)),
        "n_windows_per_cohort": windows_per_cohort,
        "decision": summary["decision_status"],
        "candidate_v2_robust": summary["candidate_v2_robust"],
        "failure_diagnostics": "failure_diagnostics.json",
        "provider_uri": provider_uri,
        "provider_identity_sha256": provider_manifest["provider_identity_sha256"],
        "market_session_calendar_note": (
            "US-market-only calendar. Ref($close, -10) forward returns use "
            "consecutive US trading sessions, avoiding CN/HK calendar "
            "contamination from the old watchlist union calendar."
        ),
        "survivorship_bias_documented": True,
    }
    manifest_path = base_out / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print("\n── Cross-Universe Decision ──")
    print(f"  status:           {summary['decision_status']}")
    print(f"  candidate_v2_robust: {summary['candidate_v2_robust']}")
    if summary.get("degradation_note"):
        print(f"  degradation:      {summary['degradation_note']}")
    print(f"\n  coverage:    {coverage_path}")
    print(f"  per-window:  {per_window_dir}")
    print(f"  cohorts:     {cohort_agg_path}")
    print(f"  summary:     {summary_path}")
    print(f"  failure:     {failure_path}")
    print(f"  manifest:    {manifest_path}")

    return {
        "coverage_path": str(coverage_path),
        "per_window_dir": str(per_window_dir),
        "cohort_agg_path": str(cohort_agg_path),
        "summary_path": str(summary_path),
        "failure_path": str(failure_path),
        "manifest_path": str(manifest_path),
        "coverage": coverage_reports,
        "cohort_aggregates": cohort_aggregates,
        "summary": summary,
        "manifest": manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Project root directory")
    parser.add_argument("--data-root", type=Path, default=None,
                        help="Read-only data root (Qlib provider URI = <data-root>/data/providers/us)")
    parser.add_argument("--first-test-year", type=int, default=2024,
                        help="First OOS test year")
    parser.add_argument("--last-test-year", type=int, default=2026,
                        help="Last OOS test year")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run(
        args.root,
        data_root=args.data_root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
    )
    print(f"\n  coverage:  {result['coverage_path']}")
    print(f"  summary:   {result['summary_path']}")
    print(f"  manifest:  {result['manifest_path']}")


if __name__ == "__main__":
    main()
