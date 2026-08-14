"""PIT regime gate for the fixed CN x1.1 sector-breadth sleeve."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.cn130_cross_sectional_ranking import compound, max_drawdown
from src.research.cn130_ranking_pipeline import turnover
from src.research.cn130_tail_factor_discovery import PortfolioVariant, choose_holdings

#: Explicit risk-on rules accepted by :func:`regime_signal`. ``two_of_three`` remains
#: the legacy default; ``breadth_veto`` is the Issue #947 challenger rule.
SUPPORTED_REGIME_RULES = frozenset(
    {
        "two_of_three",
        "trend_only",
        "momentum_and_breadth",
        "three_of_three",
        "breadth_veto",
    }
)

#: Exposure policies accepted by :func:`run_regime_portfolio`. ``full_exposure`` is
#: the legacy default (risk-on holds the fixed selection at 100%); ``breadth_scaled``
#: is the Issue #954 challenger policy that scales the active sleeve by
#: :func:`clamped_active_share` and allocates the remainder to the benchmark.
EXPOSURE_POLICIES = frozenset({"full_exposure", "breadth_scaled"})


def clamped_active_share(
    breadth_value: float,
    breadth_threshold: float = 0.50,
) -> float:
    """Issue #954: scale active exposure by ``breadth_value / breadth_threshold``.

    The ratio is clamped to ``[0, 1]``: a weak breadth value never produces a
    negative or oversized active sleeve. The frozen threshold is 0.50 (the same
    ``regime_breadth_threshold`` used to form the breadth vote).
    """

    if breadth_threshold <= 0:
        raise ValueError("breadth_threshold must be positive")
    ratio = float(breadth_value) / float(breadth_threshold)
    return float(min(max(ratio, 0.0), 1.0))


@dataclass(frozen=True)
class RegimeGateSpec:
    model_id: str = "cn_x1_1_regime_gated_sector_breadth_v1"
    benchmark: str = "000300"
    long_ma_sessions: int = 200
    momentum_sessions: int = 60
    breadth_ma_sessions: int = 60
    breadth_threshold: float = 0.50
    votes_required: int = 2
    sectors: int = 4
    names_per_sector: int = 1
    rebalance_sessions: int = 10
    execution_delay_sessions: int = 1
    horizon_sessions: int = 10
    cost_bps: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def variant(self) -> PortfolioVariant:
        return PortfolioVariant(
            "sector_4x1",
            "sector_hierarchical",
            sectors=self.sectors,
            names_per_sector=self.names_per_sector,
        )


def build_regime_state(
    close: pd.DataFrame,
    *,
    symbols: Sequence[str],
    benchmark: str,
    long_ma_sessions: int = 200,
    momentum_sessions: int = 60,
    breadth_ma_sessions: int = 60,
    breadth_threshold: float = 0.50,
) -> pd.DataFrame:
    """Build strictly trailing market-state votes at every provider session."""

    benchmark_close = close[benchmark]
    long_trend = (
        benchmark_close
        > benchmark_close.rolling(
            long_ma_sessions,
            min_periods=long_ma_sessions,
        ).mean()
    )
    medium_momentum = benchmark_close / benchmark_close.shift(momentum_sessions) - 1.0 > 0.0
    breadth_values = (
        close.loc[:, list(symbols)]
        > close.loc[:, list(symbols)]
        .rolling(
            breadth_ma_sessions,
            min_periods=breadth_ma_sessions,
        )
        .mean()
    ).mean(axis=1)
    breadth = breadth_values >= breadth_threshold
    output = pd.DataFrame(
        {
            "long_trend": long_trend.fillna(False).astype(bool),
            "medium_momentum": medium_momentum.fillna(False).astype(bool),
            "breadth_value": breadth_values.fillna(0.0),
            "cross_sectional_breadth": breadth.fillna(False).astype(bool),
        },
        index=close.index,
    )
    output["votes"] = (
        output[["long_trend", "medium_momentum", "cross_sectional_breadth"]].sum(axis=1).astype(int)
    )
    return output


def regime_signal(state: pd.DataFrame, date: pd.Timestamp, rule: str) -> bool:
    row = state.loc[date]
    if rule == "two_of_three":
        return int(row["votes"]) >= 2
    if rule == "trend_only":
        return bool(row["long_trend"])
    if rule == "momentum_and_breadth":
        return bool(row["medium_momentum"] and row["cross_sectional_breadth"])
    if rule == "three_of_three":
        return int(row["votes"]) >= 3
    if rule == "breadth_veto":
        # Issue #947: the breadth vote becomes a veto that must accompany at least
        # one of the trend votes. No new threshold is introduced.
        return bool(
            row["cross_sectional_breadth"] and (row["long_trend"] or row["medium_momentum"])
        )
    raise ValueError(f"unsupported regime rule: {rule}")


def run_regime_portfolio(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    state: pd.DataFrame,
    *,
    windows: Sequence[str],
    variant: PortfolioVariant,
    rule: str = "two_of_three",
    exposure_policy: str | None = None,
    breadth_threshold: float = 0.50,
    rebalance_sessions: int = 10,
    cost_bps: int = 20,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
    initial_weights: Mapping[str, float] | None = None,
    validate_holdings: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Allocate to sector breadth when risk-on and CSI300 when risk-off.

    ``exposure_policy`` selects how the risk-on selection is held. The default
    ``full_exposure`` is unchanged: the fixed selection is held at 100% when
    risk-on. With ``breadth_scaled`` (Issue #954) the same ``rule`` provides
    two_of_three eligibility, but the active sleeve is scaled to
    :func:`clamped_active_share`` of the current ``breadth_value`` and the
    remainder ``1 - active_share`` is allocated to the CSI300 benchmark sleeve;
    the mixed weights always sum to exactly 1. An eligible date with zero active
    share (or an ineligible date) holds the benchmark at 100% and is attributed
    as risk-off. The period and holding frames gain the ``risk_on_eligible``,
    ``active_share``, and ``benchmark_sleeve`` diagnostic columns only under the
    scaled policy, so the legacy and Issue #947 frames are byte-identical.

    ``validate_holdings`` enables a fail-closed guard on the actual risk-on
    selection for fixed-count variants: every selected holding's
    ``execution_forward_return`` must be finite, the chosen set must contain
    exactly ``sectors * names_per_sector`` names, and holdings must be unique.
    Without it, a short or non-finite selection would silently shrink or skip a
    period; with it the portfolio path raises instead. Risk-off behavior is
    unchanged. Selection, dropna behavior, returns, costs, and weights are
    never modified — the guard only verifies what was actually chosen.
    """

    exposure = str(exposure_policy or "full_exposure")
    if exposure not in EXPOSURE_POLICIES:
        raise ValueError(f"unsupported exposure policy: {exposure}")

    previous = {
        str(instrument): float(weight)
        for instrument, weight in (initial_weights or {}).items()
        if float(weight) != 0.0
    }
    period_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window].copy()
        dates = sorted(pd.to_datetime(part["datetime"].unique()))[::rebalance_sessions]
        for date in dates:
            date = pd.Timestamp(date)
            if date not in state.index or date not in benchmark_returns.index:
                continue
            benchmark_return = float(benchmark_returns.loc[date])
            if not np.isfinite(benchmark_return):
                continue
            eligible = regime_signal(state, date, rule)
            if exposure == "breadth_scaled":
                active_share = clamped_active_share(
                    float(state.loc[date, "breadth_value"]),
                    breadth_threshold,
                )
                risk_on = bool(eligible and active_share > 0.0)
            else:
                active_share = 1.0
                risk_on = eligible
            if risk_on:
                day = part.loc[pd.to_datetime(part["datetime"]) == date]
                chosen = choose_holdings(
                    day,
                    variant,
                    excluded_name=excluded_name,
                    excluded_sector=excluded_sector,
                )
                if validate_holdings:
                    expected = int(variant.sectors) * int(variant.names_per_sector)
                    if len(chosen) != expected:
                        raise ValueError(
                            f"CN risk-on selection on {date:%Y-%m-%d} in {window} "
                            f"must hold exactly {expected} names "
                            f"({variant.selector} {variant.sectors}x"
                            f"{variant.names_per_sector}); chose {len(chosen)}"
                        )
                    if not np.isfinite(chosen["execution_forward_return"].to_numpy()).all():
                        raise ValueError(
                            f"CN risk-on selection on {date:%Y-%m-%d} in {window} "
                            "contains a non-finite execution return"
                        )
                    if not chosen["instrument"].is_unique:
                        raise ValueError(
                            f"CN risk-on selection on {date:%Y-%m-%d} in {window} "
                            "contains duplicate holdings"
                        )
                if chosen.empty:
                    continue
                name_count = len(chosen)
                if exposure == "breadth_scaled":
                    name_weight = active_share / name_count
                    weights = {str(symbol): name_weight for symbol in chosen["instrument"]}
                    weights["000300"] = 1.0 - active_share
                    sleeve_weight = 1.0 - active_share
                    gross_return = (
                        active_share * float(chosen["execution_forward_return"].mean())
                        + sleeve_weight * benchmark_return
                    )
                else:
                    name_weight = 1.0 / name_count
                    weights = {str(symbol): name_weight for symbol in chosen["instrument"]}
                    sleeve_weight = 0.0
                    gross_return = float(chosen["execution_forward_return"].mean())
            else:
                chosen = part.iloc[0:0]
                weights = {"000300": 1.0}
                active_share = 0.0
                sleeve_weight = 1.0
                gross_return = benchmark_return
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000.0
            net_return = gross_return - cost
            relative_log_return = float(np.log1p(net_return) - np.log1p(benchmark_return))
            period_row = {
                "window": window,
                "datetime": date,
                "risk_on": risk_on,
                "rule": rule,
                "votes": int(state.loc[date, "votes"]),
                "long_trend": bool(state.loc[date, "long_trend"]),
                "medium_momentum": bool(state.loc[date, "medium_momentum"]),
                "cross_sectional_breadth": bool(state.loc[date, "cross_sectional_breadth"]),
                "breadth_value": float(state.loc[date, "breadth_value"]),
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "relative_log_return": relative_log_return,
                "turnover": period_turnover,
                "cost": cost,
                "benchmark_hit": net_return > benchmark_return,
            }
            if exposure == "breadth_scaled":
                period_row["risk_on_eligible"] = bool(eligible)
                period_row["active_share"] = active_share
                period_row["benchmark_sleeve"] = sleeve_weight
            period_rows.append(period_row)
            if risk_on:
                denominator = name_count + 1 if exposure == "breadth_scaled" else name_count
                for row in chosen.itertuples(index=False):
                    holding_rows.append(
                        {
                            "window": window,
                            "datetime": date,
                            "instrument": str(row.instrument),
                            "entity": row.entity,
                            "sector": row.sector,
                            "score": float(row.score),
                            "weight": name_weight,
                            "raw_return": float(row.execution_forward_return),
                            "benchmark_return": benchmark_return,
                            "net_contribution": (
                                name_weight * float(row.execution_forward_return)
                                - cost / denominator
                            ),
                            "precision_hit": (
                                float(row.execution_forward_return) > benchmark_return
                            ),
                        }
                    )
                if exposure == "breadth_scaled" and sleeve_weight > 0.0:
                    holding_rows.append(
                        {
                            "window": window,
                            "datetime": date,
                            "instrument": "000300",
                            "entity": "CSI300 sleeve",
                            "sector": "CSI300",
                            "score": np.nan,
                            "weight": sleeve_weight,
                            "raw_return": benchmark_return,
                            "benchmark_return": benchmark_return,
                            "net_contribution": (
                                sleeve_weight * benchmark_return - cost / denominator
                            ),
                            "precision_hit": False,
                        }
                    )
            else:
                holding_rows.append(
                    {
                        "window": window,
                        "datetime": date,
                        "instrument": "000300",
                        "entity": "CSI300 fallback",
                        "sector": "CSI300",
                        "score": np.nan,
                        "weight": 1.0,
                        "raw_return": benchmark_return,
                        "benchmark_return": benchmark_return,
                        "net_contribution": net_return,
                        "precision_hit": False,
                    }
                )
            previous = weights

    periods = pd.DataFrame(period_rows)
    holdings = pd.DataFrame(holding_rows)
    if periods.empty:
        raise ValueError(f"no periods for rule={rule}, windows={tuple(windows)}")

    window_rows: list[dict[str, Any]] = []
    for window, group in periods.groupby("window", sort=False):
        total_return = compound(group["net_return"])
        benchmark_return = compound(group["benchmark_return"])
        window_rows.append(
            {
                "window": window,
                "total_return": total_return,
                "benchmark_return": benchmark_return,
                "relative_excess": ((1.0 + total_return) / (1.0 + benchmark_return) - 1.0),
                "max_drawdown": max_drawdown(group["net_return"]),
                "all_period_hit_rate": float(group["benchmark_hit"].mean()),
                "risk_on_share": float(group["risk_on"].mean()),
                "turnover": float(group["turnover"].sum()),
                "rebalance_count": int(len(group)),
            }
        )
    window_results = pd.DataFrame(window_rows)

    active_periods = periods.loc[periods["risk_on"]]
    fallback_periods = periods.loc[~periods["risk_on"]]
    active_holdings = holdings.loc[holdings["instrument"] != "000300"]
    total_return = compound(periods["net_return"])
    benchmark_return = compound(periods["benchmark_return"])
    name_contribution = active_holdings.groupby("instrument")["net_contribution"].sum()
    sector_contribution = active_holdings.groupby("sector")["net_contribution"].sum()
    name_abs = float(name_contribution.abs().sum())
    sector_abs = float(sector_contribution.abs().sum())
    summary = {
        "rule": rule,
        "rebalance_sessions": rebalance_sessions,
        "cost_bps": cost_bps,
        "windows": list(windows),
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "relative_excess": (1.0 + total_return) / (1.0 + benchmark_return) - 1.0,
        "max_drawdown": max_drawdown(periods["net_return"]),
        "positive_excess_windows": int((window_results["relative_excess"] > 0.0).sum()),
        "all_period_hit_rate": float(periods["benchmark_hit"].mean()),
        "risk_on_active_hit_rate": (
            float(active_periods["benchmark_hit"].mean()) if len(active_periods) else 0.0
        ),
        "risk_on_share": float(periods["risk_on"].mean()),
        "risk_on_relative_excess": (
            float(np.expm1(active_periods["relative_log_return"].sum()))
            if len(active_periods)
            else 0.0
        ),
        "risk_off_relative_excess": (
            float(np.expm1(fallback_periods["relative_log_return"].sum()))
            if len(fallback_periods)
            else 0.0
        ),
        "risk_off_total_cost": float(fallback_periods["cost"].sum()),
        "turnover": float(periods["turnover"].sum()),
        "maximum_name_absolute_contribution_share": (
            float(name_contribution.abs().max() / name_abs) if name_abs else 1.0
        ),
        "maximum_sector_absolute_contribution_share": (
            float(sector_contribution.abs().max() / sector_abs) if sector_abs else 1.0
        ),
        "top_contributor_name": (
            str(name_contribution.abs().idxmax()) if len(name_contribution) else ""
        ),
        "top_contributor_sector": (
            str(sector_contribution.abs().idxmax()) if len(sector_contribution) else ""
        ),
        "rebalance_count": int(len(periods)),
    }
    return summary, periods, holdings, window_results


def yearly_state_coverage(periods: pd.DataFrame) -> pd.DataFrame:
    frame = periods.copy()
    frame["year"] = pd.to_datetime(frame["datetime"]).dt.year
    rows: list[dict[str, Any]] = []
    for year, group in frame.groupby("year", sort=True):
        rows.append(
            {
                "year": int(year),
                "risk_on_count": int(group["risk_on"].sum()),
                "risk_off_count": int((~group["risk_on"]).sum()),
                "risk_on_share": float(group["risk_on"].mean()),
                "both_states_present": bool(group["risk_on"].any() and (~group["risk_on"]).any()),
            }
        )
    return pd.DataFrame(rows)
