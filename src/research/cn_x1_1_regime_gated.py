"""PIT regime gate for the fixed CN x1.1 sector-breadth sleeve."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.cn130_cross_sectional_ranking import compound, max_drawdown
from src.research.cn130_ranking_pipeline import turnover
from src.research.cn130_tail_factor_discovery import PortfolioVariant, choose_holdings


@dataclass(frozen=True)
class RegimeGateSpec:
    model_id: str = "cn_x1_1_regime_gated_sector_breadth_v1"
    benchmark: str = "000300"
    long_ma_sessions: int = 200
    momentum_sessions: int = 40
    breadth_ma_sessions: int = 60
    breadth_threshold: float = 0.55
    rule: str = "momentum_and_breadth"
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
    raise ValueError(f"unsupported regime rule: {rule}")


def run_regime_portfolio(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    state: pd.DataFrame,
    *,
    windows: Sequence[str],
    variant: PortfolioVariant,
    rule: str = "two_of_three",
    rebalance_sessions: int = 10,
    cost_bps: int = 20,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Allocate to sector breadth when risk-on and CSI300 when risk-off."""

    previous: dict[str, float] = {}
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
            risk_on = regime_signal(state, date, rule)
            if risk_on:
                day = part.loc[pd.to_datetime(part["datetime"]) == date]
                chosen = choose_holdings(
                    day,
                    variant,
                    excluded_name=excluded_name,
                    excluded_sector=excluded_sector,
                )
                if chosen.empty:
                    continue
                weight = 1.0 / len(chosen)
                weights = {str(symbol): weight for symbol in chosen["instrument"]}
                gross_return = float(chosen["execution_forward_return"].mean())
            else:
                chosen = part.iloc[0:0]
                weights = {"000300": 1.0}
                gross_return = benchmark_return
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000.0
            net_return = gross_return - cost
            relative_log_return = float(np.log1p(net_return) - np.log1p(benchmark_return))
            period_rows.append(
                {
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
            )
            if risk_on:
                for row in chosen.itertuples(index=False):
                    holding_rows.append(
                        {
                            "window": window,
                            "datetime": date,
                            "instrument": str(row.instrument),
                            "entity": row.entity,
                            "sector": row.sector,
                            "score": float(row.score),
                            "weight": weight,
                            "raw_return": float(row.execution_forward_return),
                            "benchmark_return": benchmark_return,
                            "net_contribution": (
                                weight * float(row.execution_forward_return) - cost / len(chosen)
                            ),
                            "precision_hit": (
                                float(row.execution_forward_return) > benchmark_return
                            ),
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
