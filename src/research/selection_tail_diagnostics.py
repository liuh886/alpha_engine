"""Selection tail diagnostics for benchmark-aware Top-K research.

Provides deterministic per-rebalance diagnostic evidence about the selected
Top-K names and the Bottom-K-by-score names, enabling root-cause analysis of
unstable portfolio outcomes across expanded universes.

All diagnostics are **research_only** and **trade_ready=false**.
The bottom-leg computations are **diagnostic only** and do not represent a
trading signal or short recommendation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.research.risk_control_variants import RiskVariantReport


def _validate_score_frame(scores: pd.DataFrame) -> None:
    """Validate the score frame has expected columns, index, and non-empty data."""
    if list(scores.columns) != ["score"]:
        raise ValueError("scores must contain exactly one 'score' column")
    if not isinstance(scores.index, pd.MultiIndex):
        raise ValueError("scores must use a MultiIndex")
    if set(scores.index.names) != {"datetime", "instrument"}:
        raise ValueError("scores index levels must be datetime and instrument")
    if scores.empty or scores.dropna().empty:
        raise ValueError("scores must contain usable non-NaN values")


def _validate_returns_frame(returns: pd.DataFrame) -> None:
    """Validate the returns frame has expected provenance, horizon, and structure."""
    if list(returns.columns) != ["return"]:
        raise ValueError("returns must contain exactly one 'return' column")
    if not isinstance(returns.index, pd.MultiIndex):
        raise ValueError("returns must use a MultiIndex")
    if set(returns.index.names) != {"datetime", "instrument"}:
        raise ValueError("returns index levels must be datetime and instrument")
    if returns.attrs.get("provenance") != "raw_forward_return":
        raise ValueError("returns provenance must be raw_forward_return")
    if returns.attrs.get("horizon") != 10:
        raise ValueError("returns horizon must be 10")
    if returns.empty or returns.dropna().empty:
        raise ValueError("returns must contain usable non-NaN values")


def _common_dates(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    report: RiskVariantReport,
) -> tuple[pd.Timestamp, ...]:
    """Find dates common to scores, returns, and report period details."""
    score_dates = set(scores.index.get_level_values("datetime"))
    return_dates = set(returns.index.get_level_values("datetime"))
    report_dates = set()
    for pd_ in report.period_details:
        try:
            report_dates.add(pd.Timestamp(pd_.date))
        except (ValueError, TypeError):
            pass
    dates = tuple(sorted(score_dates & return_dates & report_dates))
    if not dates:
        raise ValueError("no common dates across scores, returns, and report periods")
    return dates


def _cross_sectional_returns(
    returns: pd.DataFrame,
    date: pd.Timestamp,
) -> pd.Series:
    """Get cross-sectional raw returns for a single date, filtering inf/NaN."""
    try:
        row = returns.xs(date, level="datetime")["return"]
    except KeyError:
        raise ValueError(f"no returns data for date {date}")
    row = row.replace([np.inf, -np.inf], np.nan).dropna()
    if row.empty:
        raise ValueError(f"all returns are NaN/inf for date {date}")
    return row.astype(float)


def _compute_period_diagnostics(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    report: RiskVariantReport,
    date: pd.Timestamp,
    *,
    top_n: int,
) -> dict[str, Any]:
    """Compute tail diagnostics for one rebalance period."""
    date_str = str(date.date())

    # Locate the matching period detail in the report
    period_detail = None
    for pd_ in report.period_details:
        if pd_.date == date_str:
            period_detail = pd_
            break
    if period_detail is None:
        raise ValueError(f"report missing period detail for date {date_str}")

    # Cross-sectional scores and returns for this date
    try:
        daily_scores = (
            scores.xs(date, level="datetime")["score"]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
    except KeyError:
        raise ValueError(f"no scores for date {date_str}")

    xret = _cross_sectional_returns(returns, date)

    if len(daily_scores) < 2 * top_n:
        raise ValueError(
            f"insufficient scored symbols on {date_str}: "
            f"need {2 * top_n}, got {len(daily_scores)}"
        )

    # Select tails from scores alone.  Intersecting with realized-return
    # availability before ranking would let a future label decide which names
    # enter Top-K or Bottom-K.
    top_k_idx = daily_scores.nlargest(top_n).index
    bot_k_idx = daily_scores.nsmallest(top_n).index
    missing_tail_returns = [
        str(symbol)
        for symbol in top_k_idx.append(bot_k_idx).unique()
        if symbol not in xret.index
    ]
    if missing_tail_returns:
        raise ValueError(
            f"tail selections on {date_str} have no finite raw returns: "
            f"{missing_tail_returns}"
        )

    report_symbols = {holding.symbol for holding in period_detail.holdings}
    if report_symbols != {str(symbol) for symbol in top_k_idx}:
        raise ValueError(
            f"report holdings on {date_str} do not match score-selected Top-{top_n}"
        )

    # The common return cross-section is used only for realized percentiles,
    # never to choose the portfolio or diagnostic tails.
    common = daily_scores.index.intersection(xret.index)
    if len(common) < 2 * top_n:
        raise ValueError(
            f"insufficient common symbols on {date_str}: "
            f"need {2 * top_n}, got {len(common)}"
        )

    s_common = daily_scores.loc[common]
    r_common = xret.loc[common]

    # Cross-sectional Top-K and Bottom-K by score (diagnostic only).
    top_k_mean = float(xret.loc[top_k_idx].mean())
    bot_k_mean = float(xret.loc[bot_k_idx].mean())
    spread = top_k_mean - bot_k_mean

    # Selected holdings: realized return percentiles
    selected_present = [
        h.symbol for h in period_detail.holdings if h.symbol in r_common.index
    ]

    n_cs = len(r_common)
    ranks = r_common.rank(method="average")
    selected_percentiles: dict[str, float | None] = {}
    for h in period_detail.holdings:
        if h.symbol in r_common.index and n_cs > 1:
            rank = float(ranks.loc[h.symbol])
            selected_percentiles[h.symbol] = (rank - 1.0) / (n_cs - 1.0)
        else:
            selected_percentiles[h.symbol] = None

    # Selected above cross-sectional median
    median_ret = float(r_common.median())
    selected_above_median = sum(
        1 for sym in selected_present
        if float(r_common.loc[sym]) > median_ret
    )
    selected_above_median_ratio = (
        selected_above_median / len(selected_present)
        if selected_present
        else 0.0
    )

    # Selected positive return ratio
    selected_positive = sum(
        1 for sym in selected_present
        if float(r_common.loc[sym]) > 0.0
    )
    selected_positive_ratio = (
        selected_positive / len(selected_present)
        if selected_present
        else 0.0
    )

    return {
        "date": date_str,
        "selected_holdings": [
            {
                "symbol": h.symbol,
                "weight": h.weight,
                "raw_return": h.raw_return,
                "gross_contribution": h.gross_contribution,
                "realized_return_percentile": selected_percentiles.get(h.symbol),
            }
            for h in period_detail.holdings
        ],
        "bottom_k_diagnostic_symbols": [
            {
                "symbol": str(sym),
                "score": float(s_common.loc[sym]),
                "raw_return": float(r_common.loc[sym]),
            }
            for sym in bot_k_idx
        ],
        "unscaled_top_k_mean_raw_return": top_k_mean,
        "unscaled_bottom_k_mean_raw_return": bot_k_mean,
        "top_minus_bottom_spread": spread,
        "selected_above_median_ratio": selected_above_median_ratio,
        "selected_positive_return_ratio": selected_positive_ratio,
        "portfolio": {
            "gross_exposure": period_detail.gross_exposure,
            "turnover": period_detail.turnover,
            "cost": period_detail.cost,
            "gross_return": period_detail.gross_return,
            "net_return": period_detail.net_return,
            "benchmark_return": period_detail.benchmark_return,
            "relative_excess": period_detail.relative_excess,
        },
    }


def _aggregate_period_diagnostics(
    period_diags: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate per-period diagnostics across all periods."""
    n = len(period_diags)
    if n == 0:
        return {"n_periods": 0}

    spreads = [
        d["top_minus_bottom_spread"]
        for d in period_diags
        if np.isfinite(d["top_minus_bottom_spread"])
    ]
    positive_spread_count = sum(1 for s in spreads if s > 0)

    # Selected percentiles across all periods
    all_percentiles = []
    all_above_median_flags: list[float] = []
    all_positive_flags: list[float] = []
    for d in period_diags:
        for h in d["selected_holdings"]:
            pct = h.get("realized_return_percentile")
            if pct is not None and np.isfinite(pct):
                all_percentiles.append(pct)
                all_above_median_flags.append(1.0 if pct > 0.5 else 0.0)
            raw_ret = h.get("raw_return")
            if raw_ret is not None and np.isfinite(raw_ret):
                all_positive_flags.append(1.0 if raw_ret > 0.0 else 0.0)

    # Worst periods — use full period dicts for complete detail
    worst_net_period = min(period_diags, key=lambda d: d["portfolio"]["net_return"])
    worst_rel_period = min(period_diags, key=lambda d: d["portfolio"]["relative_excess"])

    # Per-symbol contribution counts and sums
    symbol_contributions: dict[str, dict[str, float]] = {}
    for d in period_diags:
        for h in d["selected_holdings"]:
            sym = h["symbol"]
            if sym not in symbol_contributions:
                symbol_contributions[sym] = {
                    "count": 0.0,
                    "sum_gross_contribution": 0.0,
                    "negative_count": 0.0,
                    "worst_gross_contribution": float("inf"),
                }
            symbol_contributions[sym]["count"] += 1.0
            gc = h.get("gross_contribution")
            if gc is not None and np.isfinite(gc):
                symbol_contributions[sym]["sum_gross_contribution"] += gc
                if gc < 0:
                    symbol_contributions[sym]["negative_count"] += 1.0
                if gc < symbol_contributions[sym]["worst_gross_contribution"]:
                    symbol_contributions[sym]["worst_gross_contribution"] = gc

    total_turnover = sum(d["portfolio"]["turnover"] for d in period_diags)
    total_cost = sum(d["portfolio"]["cost"] for d in period_diags)

    return {
        "n_periods": n,
        "mean_spread": float(np.mean(spreads)) if spreads else float("nan"),
        "positive_spread_count": positive_spread_count,
        "positive_spread_ratio": (
            positive_spread_count / n if n > 0 else float("nan")
        ),
        "mean_selected_realized_percentile": (
            float(np.mean(all_percentiles)) if all_percentiles else float("nan")
        ),
        "selected_above_median_ratio": (
            float(np.mean(all_above_median_flags))
            if all_above_median_flags
            else float("nan")
        ),
        "selected_positive_return_ratio": (
            float(np.mean(all_positive_flags))
            if all_positive_flags
            else float("nan")
        ),
        "total_turnover": total_turnover,
        "total_cost": total_cost,
        "worst_net_return_period": {
            "date": worst_net_period["date"],
            "net_return": worst_net_period["portfolio"]["net_return"],
        },
        "worst_relative_excess_period": {
            "date": worst_rel_period["date"],
            "relative_excess": worst_rel_period["portfolio"]["relative_excess"],
        },
        "symbol_contributions": {
            sym: {
                "times_selected": int(data["count"]),
                "sum_gross_contribution": data["sum_gross_contribution"],
                "negative_contribution_count": int(data["negative_count"]),
                "worst_gross_contribution": (
                    data["worst_gross_contribution"]
                    if np.isfinite(data["worst_gross_contribution"])
                    else None
                ),
            }
            for sym, data in sorted(symbol_contributions.items())
        },
    }


def compute_selection_tail_diagnostics(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    report: RiskVariantReport,
    *,
    top_n: int = 3,
) -> dict[str, Any]:
    """Compute per-rebalance tail diagnostics for a frozen candidate.

    Parameters
    ----------
    scores : pd.DataFrame
        Blend or model score frame with MultiIndex (datetime, instrument)
        and a single 'score' column.
    returns : pd.DataFrame
        Canonical raw 10D forward return frame with MultiIndex (datetime, instrument)
        and a single 'return' column.  Must have ``provenance=raw_forward_return``
        and ``horizon=10`` attributes.
    report : RiskVariantReport
        Cost-aware portfolio report with ``period_details`` from
        :func:`~src.research.risk_control_variants.evaluate_variant_weights`.
    top_n : int
        Number of Top / Bottom symbols for spread computation (default 3).

    Returns
    -------
    dict[str, Any]
        Diagnostics dict with ``research_only=True``, ``trade_ready=False``,
        and ``bottom_leg_is_diagnostic_only=True``.
    """
    _validate_score_frame(scores)
    _validate_returns_frame(returns)

    dates = _common_dates(scores, returns, report)
    n_top = max(1, top_n)

    period_diags: list[dict[str, Any]] = []
    for date in dates:
        diag = _compute_period_diagnostics(
            scores, returns, report, date, top_n=n_top
        )
        period_diags.append(diag)

    aggregate = _aggregate_period_diagnostics(period_diags)

    return {
        "research_only": True,
        "trade_ready": False,
        "bottom_leg_is_diagnostic_only": True,
        "candidate_variant_id": report.variant_id,
        "top_n": n_top,
        "periods": period_diags,
        "aggregate": aggregate,
    }


def summarize_window_diagnostics(
    per_window_diags: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine multiple window diagnostics into a cross-window summary.

    Flattens actual period records across all windows and computes exact
    period-weighted aggregates via the common aggregate helper.  Each period
    record is tagged with the originating ``window_label``.

    Produces aggregated statistics without inventing causal or promotion claims.
    The output remains **research_only**, **trade_ready=false**, and
    **bottom_leg_is_diagnostic_only=true**.
    """
    failed = [d for d in per_window_diags if d and d.get("skipped", False)]
    if failed:
        reasons = [
            str(d.get("skip_reason", "selection tail diagnostics skipped"))
            for d in failed
        ]
        raise ValueError(
            "cannot summarize incomplete selection tail diagnostics: "
            + "; ".join(reasons)
        )

    valid = [
        d for d in per_window_diags
        if d is not None
        and isinstance(d, dict)
        and "periods" in d
    ]
    n_windows = len(valid)

    if n_windows == 0:
        return {
            "research_only": True,
            "trade_ready": False,
            "bottom_leg_is_diagnostic_only": True,
            "n_windows": 0,
        }

    # Flatten periods across windows, preserving window_label on each period
    all_periods: list[dict[str, Any]] = []
    for d in valid:
        window_label = d.get("window_label", "")
        for period in d.get("periods", []):
            tagged = dict(period)
            tagged["window_label"] = window_label
            all_periods.append(tagged)

    # Compute exact period-weighted aggregates via the common helper
    aggregate = _aggregate_period_diagnostics(all_periods)

    # Full worst-period details (complete period dicts from the flattened list)
    if all_periods:
        worst_net_full = min(all_periods, key=lambda p: p["portfolio"]["net_return"])
        worst_rel_full = min(all_periods, key=lambda p: p["portfolio"]["relative_excess"])
    else:
        worst_net_full = {}
        worst_rel_full = {}

    window_breakdown: dict[str, dict[str, Any]] = {}
    for index, diagnostic in enumerate(valid):
        label = str(diagnostic.get("window_label") or f"window_{index + 1}")
        periods = diagnostic.get("periods", [])
        window_aggregate = _aggregate_period_diagnostics(periods)
        # Detailed period and per-symbol records already live in each per-window
        # evidence file.  Keep the cross-window artifact compact instead of
        # duplicating those large payloads four times.
        window_breakdown[label] = {
            key: value
            for key, value in window_aggregate.items()
            if key != "symbol_contributions"
        }

    return {
        "research_only": True,
        "trade_ready": False,
        "bottom_leg_is_diagnostic_only": True,
        "n_windows": n_windows,
        "n_periods_total": aggregate["n_periods"],
        "mean_spread": aggregate["mean_spread"],
        "mean_positive_spread_ratio": aggregate["positive_spread_ratio"],
        "mean_selected_realized_percentile": (
            aggregate["mean_selected_realized_percentile"]
        ),
        "mean_selected_above_median_ratio": (
            aggregate["selected_above_median_ratio"]
        ),
        "mean_selected_positive_return_ratio": (
            aggregate["selected_positive_return_ratio"]
        ),
        "total_turnover": aggregate["total_turnover"],
        "total_cost": aggregate["total_cost"],
        "worst_net_return_period": aggregate["worst_net_return_period"],
        "worst_relative_excess_period": aggregate["worst_relative_excess_period"],
        "worst_net_return_period_detail": worst_net_full,
        "worst_relative_excess_period_detail": worst_rel_full,
        "symbol_contributions": aggregate["symbol_contributions"],
        "window_breakdown": window_breakdown,
    }
