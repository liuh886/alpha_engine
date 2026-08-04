"""CN130 extreme-tail portfolio and factor-family discovery helpers.

The module keeps the CN130 universe, 10-session horizon, score cells and provider
identity fixed.  Portfolio diagnostics use frozen score ledgers; factor discovery
uses predeclared directions and cross-sectional evidence rather than final
portfolio return.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.cn130_cross_sectional_ranking import compound, max_drawdown
from src.research.cn130_ranking_pipeline import turnover

SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
REPORTING_WINDOWS = ("2026H1", "2026H2_PARTIAL")


@dataclass(frozen=True)
class PortfolioVariant:
    variant_id: str
    selector: str
    top_k: int | None = None
    sector_cap: int | None = None
    sectors: int | None = None
    names_per_sector: int | None = None


PORTFOLIO_VARIANTS: tuple[PortfolioVariant, ...] = (
    PortfolioVariant("global_top3", "global", top_k=3),
    PortfolioVariant("global_top5", "global", top_k=5),
    PortfolioVariant("global_top8", "global", top_k=8),
    PortfolioVariant("global_top10", "global", top_k=10),
    PortfolioVariant("global_top15", "global", top_k=15),
    PortfolioVariant("global_top5_sector_cap1", "global_sector_cap", top_k=5, sector_cap=1),
    PortfolioVariant("global_top5_sector_cap2", "global_sector_cap", top_k=5, sector_cap=2),
    PortfolioVariant("sector_3x1", "sector_hierarchical", sectors=3, names_per_sector=1),
    PortfolioVariant("sector_4x1", "sector_hierarchical", sectors=4, names_per_sector=1),
    PortfolioVariant("sector_5x1", "sector_hierarchical", sectors=5, names_per_sector=1),
    PortfolioVariant("sector_3x2", "sector_hierarchical", sectors=3, names_per_sector=2),
)


FACTOR_REGISTRY: tuple[dict[str, Any], ...] = (
    {"factor": "momentum_5", "family": "trend_momentum", "direction": 1},
    {"factor": "momentum_10", "family": "trend_momentum", "direction": 1},
    {"factor": "momentum_20", "family": "trend_momentum", "direction": 1},
    {"factor": "momentum_63", "family": "trend_momentum", "direction": 1},
    {"factor": "momentum_126", "family": "trend_momentum", "direction": 1},
    {"factor": "trend_efficiency_20", "family": "trend_momentum", "direction": 1},
    {"factor": "trend_efficiency_60", "family": "trend_momentum", "direction": 1},
    {"factor": "positive_day_ratio_20", "family": "trend_momentum", "direction": 1},
    {"factor": "positive_day_ratio_60", "family": "trend_momentum", "direction": 1},
    {"factor": "reversal_1", "family": "short_reversal", "direction": 1},
    {"factor": "reversal_3", "family": "short_reversal", "direction": 1},
    {"factor": "reversal_5", "family": "short_reversal", "direction": 1},
    {"factor": "distance_high_20", "family": "breakout_position", "direction": 1},
    {"factor": "distance_high_60", "family": "breakout_position", "direction": 1},
    {"factor": "distance_low_20", "family": "breakout_position", "direction": 1},
    {"factor": "price_to_ma20", "family": "breakout_position", "direction": 1},
    {"factor": "price_to_ma60", "family": "breakout_position", "direction": 1},
    {"factor": "volume_ratio_5", "family": "volume_price", "direction": 1},
    {"factor": "volume_ratio_20", "family": "volume_price", "direction": 1},
    {"factor": "amount_ratio_20", "family": "volume_price", "direction": 1},
    {"factor": "volume_price_confirmation_20", "family": "volume_price", "direction": 1},
    {"factor": "up_down_volume_ratio_20", "family": "volume_price", "direction": 1},
    {"factor": "volatility_10", "family": "risk_quality", "direction": -1},
    {"factor": "volatility_20", "family": "risk_quality", "direction": -1},
    {"factor": "volatility_60", "family": "risk_quality", "direction": -1},
    {"factor": "downside_volatility_20", "family": "risk_quality", "direction": -1},
    {"factor": "downside_volatility_60", "family": "risk_quality", "direction": -1},
    {"factor": "idiosyncratic_volatility_60", "family": "risk_quality", "direction": -1},
    {"factor": "intraday_range_20", "family": "risk_quality", "direction": -1},
    {"factor": "drawdown_20", "family": "drawdown_recovery", "direction": 1},
    {"factor": "drawdown_63", "family": "drawdown_recovery", "direction": 1},
    {"factor": "recovery_from_low_20", "family": "drawdown_recovery", "direction": 1},
    {"factor": "recovery_from_low_63", "family": "drawdown_recovery", "direction": 1},
    {"factor": "amihud_20", "family": "liquidity", "direction": -1},
    {"factor": "amount_stability_20", "family": "liquidity", "direction": -1},
    {"factor": "residual_momentum_20", "family": "relative_strength", "direction": 1},
    {"factor": "residual_momentum_60", "family": "relative_strength", "direction": 1},
)


def safe_divide(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    return (a / b.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def rolling_beta(stock_returns: pd.DataFrame, benchmark_returns: pd.Series, window: int = 60) -> pd.DataFrame:
    variance = benchmark_returns.rolling(window, min_periods=40).var()
    output: dict[str, pd.Series] = {}
    for symbol in stock_returns.columns:
        covariance = stock_returns[symbol].rolling(window, min_periods=40).cov(benchmark_returns)
        output[symbol] = covariance / variance.replace(0.0, np.nan)
    return pd.DataFrame(output, index=stock_returns.index)


def build_discovery_factors(fields: Mapping[str, pd.DataFrame], symbols: Sequence[str], benchmark: str) -> dict[str, pd.DataFrame]:
    close = fields["close"].loc[:, list(symbols)]
    high = fields["high"].loc[:, list(symbols)]
    low = fields["low"].loc[:, list(symbols)]
    volume = fields["volume"].loc[:, list(symbols)]
    amount = fields["amount"].loc[:, list(symbols)]
    benchmark_close = fields["close"][benchmark]
    returns = close.pct_change(fill_method=None)
    benchmark_returns = benchmark_close.pct_change(fill_method=None)
    beta60 = rolling_beta(returns, benchmark_returns, 60)

    abs_path = returns.abs()
    downside = returns.clip(upper=0.0)
    momentum20 = safe_divide(close, close.shift(20)) - 1.0
    momentum60 = safe_divide(close, close.shift(60)) - 1.0
    benchmark_momentum20 = benchmark_close / benchmark_close.shift(20) - 1.0
    benchmark_momentum60 = benchmark_close / benchmark_close.shift(60) - 1.0
    residual_daily = returns.sub(beta60.mul(benchmark_returns, axis=0))
    up_volume = volume.where(returns > 0.0, 0.0).rolling(20).sum()
    down_volume = volume.where(returns < 0.0, 0.0).rolling(20).sum()

    factors = {
        "momentum_5": safe_divide(close, close.shift(5)) - 1.0,
        "momentum_10": safe_divide(close, close.shift(10)) - 1.0,
        "momentum_20": momentum20,
        "momentum_63": safe_divide(close, close.shift(63)) - 1.0,
        "momentum_126": safe_divide(close, close.shift(126)) - 1.0,
        "trend_efficiency_20": safe_divide(momentum20.abs(), abs_path.rolling(20).sum()),
        "trend_efficiency_60": safe_divide(momentum60.abs(), abs_path.rolling(60).sum()),
        "positive_day_ratio_20": (returns > 0.0).rolling(20).mean(),
        "positive_day_ratio_60": (returns > 0.0).rolling(60).mean(),
        "reversal_1": safe_divide(close.shift(1), close) - 1.0,
        "reversal_3": safe_divide(close.shift(3), close) - 1.0,
        "reversal_5": safe_divide(close.shift(5), close) - 1.0,
        "distance_high_20": safe_divide(close, close.rolling(20).max()) - 1.0,
        "distance_high_60": safe_divide(close, close.rolling(60).max()) - 1.0,
        "distance_low_20": safe_divide(close, close.rolling(20).min()) - 1.0,
        "price_to_ma20": safe_divide(close, close.rolling(20).mean()) - 1.0,
        "price_to_ma60": safe_divide(close, close.rolling(60).mean()) - 1.0,
        "volume_ratio_5": safe_divide(volume, volume.rolling(5).mean()) - 1.0,
        "volume_ratio_20": safe_divide(volume, volume.rolling(20).mean()) - 1.0,
        "amount_ratio_20": safe_divide(amount, amount.rolling(20).mean()) - 1.0,
        "volume_price_confirmation_20": momentum20 * (safe_divide(volume, volume.rolling(20).mean()) - 1.0),
        "up_down_volume_ratio_20": safe_divide(up_volume, down_volume) - 1.0,
        "volatility_10": returns.rolling(10).std(),
        "volatility_20": returns.rolling(20).std(),
        "volatility_60": returns.rolling(60).std(),
        "downside_volatility_20": downside.rolling(20).std(),
        "downside_volatility_60": downside.rolling(60).std(),
        "idiosyncratic_volatility_60": residual_daily.rolling(60).std(),
        "intraday_range_20": safe_divide(high - low, close).rolling(20).mean(),
        "drawdown_20": safe_divide(close, close.rolling(20).max()) - 1.0,
        "drawdown_63": safe_divide(close, close.rolling(63).max()) - 1.0,
        "recovery_from_low_20": safe_divide(close, close.rolling(20).min()) - 1.0,
        "recovery_from_low_63": safe_divide(close, close.rolling(63).min()) - 1.0,
        "amihud_20": safe_divide(returns.abs(), amount.abs()).rolling(20).mean(),
        "amount_stability_20": safe_divide(amount.rolling(20).std(), amount.rolling(20).mean()),
        "residual_momentum_20": momentum20.sub(beta60.mul(benchmark_momentum20, axis=0)),
        "residual_momentum_60": momentum60.sub(beta60.mul(benchmark_momentum60, axis=0)),
    }
    return {name: frame.replace([np.inf, -np.inf], np.nan) for name, frame in factors.items()}


def stack_wide(frame: pd.DataFrame, name: str) -> pd.Series:
    series = frame.stack(future_stack=True)
    series.index = series.index.set_names(["datetime", "instrument"])
    return series.rename(name).sort_index()


def sector_relative_factor(values: pd.Series, sectors: pd.Series) -> pd.Series:
    joined = pd.DataFrame({"value": values, "sector": sectors}).dropna()
    result = joined.groupby(
        [joined.index.get_level_values("datetime"), "sector"], sort=False
    )["value"].rank(method="average", pct=True)
    result.index = joined.index
    return result.reindex(values.index)


def _rank_corr(a: pd.Series, b: pd.Series) -> float | None:
    pair = pd.concat([a, b], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 20 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return None
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
    return float(value) if pd.notna(value) else None


def factor_window_metrics(
    factor: pd.Series,
    forward_return: pd.Series,
    baseline_score: pd.Series,
    start: str,
    end: str,
) -> dict[str, float | int]:
    dates = factor.index.get_level_values("datetime")
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    joined = pd.DataFrame(
        {
            "factor": factor.loc[mask],
            "return": forward_return.reindex(factor.index[mask]),
            "baseline": baseline_score.reindex(factor.index[mask]),
        }
    ).dropna()
    daily_ic: list[float] = []
    daily_incremental: list[float] = []
    spreads: list[float] = []
    for _, group in joined.groupby(level="datetime", sort=True):
        if len(group) < 30:
            continue
        factor_rank = group["factor"].rank(method="average", pct=True)
        return_rank = group["return"].rank(method="average", pct=True)
        baseline_rank = group["baseline"].rank(method="average", pct=True)
        ic = factor_rank.corr(return_rank, method="pearson")
        design = np.column_stack([np.ones(len(group)), baseline_rank.to_numpy(dtype=float)])
        residual = factor_rank.to_numpy(dtype=float) - design @ np.linalg.lstsq(
            design, factor_rank.to_numpy(dtype=float), rcond=None
        )[0]
        inc = np.corrcoef(residual, return_rank.to_numpy(dtype=float))[0, 1]
        ordered = group.assign(factor_rank=factor_rank).sort_values(
            ["factor_rank"], ascending=False, kind="mergesort"
        )
        bucket = max(1, len(ordered) // 5)
        spread = float(ordered.head(bucket)["return"].mean() - ordered.tail(bucket)["return"].mean())
        if pd.notna(ic):
            daily_ic.append(float(ic))
        if np.isfinite(inc):
            daily_incremental.append(float(inc))
        spreads.append(spread)
    values = np.asarray(daily_ic, dtype=float)
    return {
        "n_dates": len(values),
        "mean_rank_ic": float(np.mean(values)) if len(values) else 0.0,
        "rank_icir": float(np.mean(values) / np.std(values, ddof=1)) if len(values) > 1 and np.std(values, ddof=1) > 0 else 0.0,
        "positive_daily_rank_ic_ratio": float(np.mean(values > 0.0)) if len(values) else 0.0,
        "mean_incremental_rank_ic": float(np.mean(daily_incremental)) if daily_incremental else 0.0,
        "mean_top_bottom_spread": float(np.mean(spreads)) if spreads else 0.0,
    }


def choose_holdings(day: pd.DataFrame, variant: PortfolioVariant, *, excluded_name: str | None = None, excluded_sector: str | None = None) -> pd.DataFrame:
    eligible = day.dropna(subset=["score", "execution_forward_return"]).copy()
    if excluded_name is not None:
        eligible = eligible.loc[eligible["instrument"] != excluded_name]
    if excluded_sector is not None:
        eligible = eligible.loc[eligible["sector"] != excluded_sector]
    eligible = eligible.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
    if variant.selector == "global":
        return eligible.head(int(variant.top_k)).copy()
    if variant.selector == "global_sector_cap":
        rows: list[pd.Series] = []
        counts: dict[str, int] = {}
        for _, row in eligible.iterrows():
            sector = str(row["sector"])
            if counts.get(sector, 0) >= int(variant.sector_cap):
                continue
            rows.append(row)
            counts[sector] = counts.get(sector, 0) + 1
            if len(rows) >= int(variant.top_k):
                break
        return pd.DataFrame(rows, columns=eligible.columns)
    if variant.selector == "sector_hierarchical":
        ranked = eligible.copy()
        ranked["score_pct"] = ranked["score"].rank(method="average", pct=True)
        sector_scores = ranked.groupby("sector", sort=True)["score_pct"].apply(
            lambda series: float(series.nlargest(min(3, len(series))).mean())
        )
        selected_sectors = list(
            sector_scores.sort_values(ascending=False, kind="mergesort")
            .head(int(variant.sectors))
            .index
        )
        pieces = [
            ranked.loc[ranked["sector"] == sector].head(int(variant.names_per_sector))
            for sector in selected_sectors
        ]
        return pd.concat(pieces, ignore_index=False) if pieces else ranked.head(0)
    raise ValueError(variant.selector)


def run_portfolio(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    variant: PortfolioVariant,
    cost_bps: int,
    *,
    windows: Sequence[str],
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    previous: dict[str, float] = {}
    period_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window].copy()
        dates = sorted(pd.to_datetime(part["datetime"].unique()))[::10]
        for date in dates:
            day = part.loc[pd.to_datetime(part["datetime"]) == date]
            chosen = choose_holdings(day, variant, excluded_name=excluded_name, excluded_sector=excluded_sector)
            if chosen.empty or date not in benchmark_returns.index:
                continue
            weight = 1.0 / len(chosen)
            weights = {str(symbol): weight for symbol in chosen["instrument"]}
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000.0
            gross = float(chosen["execution_forward_return"].mean())
            net = gross - cost
            benchmark = float(benchmark_returns.loc[date])
            period_rows.append(
                {
                    "window": window,
                    "datetime": date,
                    "gross_return": gross,
                    "net_return": net,
                    "benchmark_return": benchmark,
                    "turnover": period_turnover,
                    "cost": cost,
                    "n_holdings": len(chosen),
                    "benchmark_hit": net > benchmark,
                }
            )
            for row in chosen.itertuples(index=False):
                holding_rows.append(
                    {
                        "window": window,
                        "datetime": date,
                        "instrument": str(row.instrument),
                        "entity": row.entity,
                        "sector": row.sector,
                        "score": row.score,
                        "raw_return": row.execution_forward_return,
                        "benchmark_return": benchmark,
                        "weight": weight,
                        "net_contribution": weight * row.execution_forward_return - cost / len(chosen),
                        "precision_hit": row.execution_forward_return > benchmark,
                    }
                )
            previous = weights
    periods = pd.DataFrame(period_rows)
    holdings = pd.DataFrame(holding_rows)
    if periods.empty:
        raise ValueError(f"no periods for {variant.variant_id}")
    window_results: list[dict[str, Any]] = []
    for window, group in periods.groupby("window", sort=False):
        total = compound(group["net_return"])
        benchmark = compound(group["benchmark_return"])
        window_results.append(
            {
                "window": window,
                "total_return": total,
                "benchmark_return": benchmark,
                "relative_excess": (1.0 + total) / (1.0 + benchmark) - 1.0,
                "max_drawdown": max_drawdown(group["net_return"]),
            }
        )
    total = compound(periods["net_return"])
    benchmark = compound(periods["benchmark_return"])
    name_contribution = holdings.groupby("instrument")["net_contribution"].sum()
    sector_contribution = holdings.groupby("sector")["net_contribution"].sum()
    name_abs = float(name_contribution.abs().sum())
    sector_abs = float(sector_contribution.abs().sum())
    summary = {
        "variant_id": variant.variant_id,
        "cost_bps": cost_bps,
        "total_return": total,
        "benchmark_return": benchmark,
        "relative_excess": (1.0 + total) / (1.0 + benchmark) - 1.0,
        "max_drawdown": max_drawdown(periods["net_return"]),
        "turnover": float(periods["turnover"].sum()),
        "positive_excess_windows": int(sum(row["relative_excess"] > 0.0 for row in window_results)),
        "precision_at_k": float(holdings["precision_hit"].mean()),
        "portfolio_benchmark_hit_rate": float(periods["benchmark_hit"].mean()),
        "maximum_name_absolute_contribution_share": float(name_contribution.abs().max() / name_abs) if name_abs else 1.0,
        "maximum_sector_absolute_contribution_share": float(sector_contribution.abs().max() / sector_abs) if sector_abs else 1.0,
        "top_contributor_name": str(name_contribution.abs().idxmax()),
        "top_contributor_sector": str(sector_contribution.abs().idxmax()),
        "window_results": window_results,
    }
    return summary, periods, holdings


def factor_correlation_table(factor_frame: pd.DataFrame) -> pd.DataFrame:
    ranked = factor_frame.groupby(level="datetime", sort=False).rank(method="average", pct=True)
    ranked = ranked - ranked.groupby(level="datetime", sort=False).transform("mean")
    return ranked.corr(method="pearson")
