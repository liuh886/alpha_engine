"""Fixed CN x1.1 sector-breadth portfolio model and validation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.research.cn130_cross_sectional_ranking import compound, max_drawdown
from src.research.cn130_ranking_pipeline import turnover
from src.research.cn130_tail_factor_discovery import PortfolioVariant, choose_holdings


@dataclass(frozen=True)
class SectorBreadthModelSpec:
    model_id: str = "cn_x1_1_sector_breadth_v1"
    ranking_id: str = "r0_cn_x1_0_raw_return_rank"
    feature_family: str = "current_cn_ohlcv"
    sectors: int = 4
    names_per_sector: int = 1
    sector_breadth_names: int = 3
    rebalance_sessions: int = 10
    execution_delay_sessions: int = 1
    cost_bps: int = 20
    benchmark: str = "000300"
    weighting: str = "equal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def variant(self) -> PortfolioVariant:
        return PortfolioVariant(
            variant_id=f"sector_{self.sectors}x{self.names_per_sector}",
            selector="sector_hierarchical",
            sectors=self.sectors,
            names_per_sector=self.names_per_sector,
        )


def run_sector_breadth_portfolio(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    variant: PortfolioVariant,
    *,
    windows: Sequence[str],
    rebalance_sessions: int,
    cost_bps: int,
    excluded_name: str | None = None,
    excluded_sector: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run a fixed sector-hierarchical portfolio on frozen score ledgers."""

    if rebalance_sessions <= 0:
        raise ValueError("rebalance_sessions must be positive")
    previous: dict[str, float] = {}
    period_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    for window in windows:
        part = ledger.loc[ledger["window"] == window].copy()
        dates = sorted(pd.to_datetime(part["datetime"].unique()))[::rebalance_sessions]
        for rebalance_date in dates:
            day = part.loc[pd.to_datetime(part["datetime"]) == rebalance_date]
            chosen = choose_holdings(
                day,
                variant,
                excluded_name=excluded_name,
                excluded_sector=excluded_sector,
            )
            if chosen.empty or rebalance_date not in benchmark_returns.index:
                continue
            weight = 1.0 / len(chosen)
            weights = {str(symbol): weight for symbol in chosen["instrument"]}
            period_turnover = turnover(previous, weights)
            cost = period_turnover * cost_bps / 10000.0
            gross_return = float(chosen["execution_forward_return"].mean())
            net_return = gross_return - cost
            benchmark_return = float(benchmark_returns.loc[rebalance_date])
            period_rows.append(
                {
                    "window": window,
                    "datetime": rebalance_date,
                    "gross_return": gross_return,
                    "net_return": net_return,
                    "benchmark_return": benchmark_return,
                    "relative_log_return": float(
                        np.log1p(net_return) - np.log1p(benchmark_return)
                    ),
                    "turnover": period_turnover,
                    "cost": cost,
                    "n_holdings": len(chosen),
                    "benchmark_hit": net_return > benchmark_return,
                }
            )
            for row in chosen.itertuples(index=False):
                holding_rows.append(
                    {
                        "window": window,
                        "datetime": rebalance_date,
                        "instrument": str(row.instrument),
                        "entity": row.entity,
                        "sector": row.sector,
                        "score": float(row.score),
                        "raw_return": float(row.execution_forward_return),
                        "benchmark_return": benchmark_return,
                        "weight": weight,
                        "net_contribution": (
                            weight * float(row.execution_forward_return)
                            - cost / len(chosen)
                        ),
                        "precision_hit": bool(
                            float(row.execution_forward_return) > benchmark_return
                        ),
                    }
                )
            previous = weights

    periods = pd.DataFrame(period_rows)
    holdings = pd.DataFrame(holding_rows)
    if periods.empty:
        raise ValueError(f"no periods for {variant.variant_id}: {tuple(windows)}")

    window_rows: list[dict[str, Any]] = []
    for window, group in periods.groupby("window", sort=False):
        total_return = compound(group["net_return"])
        benchmark_return = compound(group["benchmark_return"])
        window_rows.append(
            {
                "window": window,
                "total_return": total_return,
                "benchmark_return": benchmark_return,
                "relative_excess": (1.0 + total_return) / (1.0 + benchmark_return) - 1.0,
                "max_drawdown": max_drawdown(group["net_return"]),
                "benchmark_hit_rate": float(group["benchmark_hit"].mean()),
                "turnover": float(group["turnover"].sum()),
                "rebalance_count": int(len(group)),
            }
        )
    window_results = pd.DataFrame(window_rows)

    total_return = compound(periods["net_return"])
    benchmark_return = compound(periods["benchmark_return"])
    name_contribution = holdings.groupby("instrument")["net_contribution"].sum()
    sector_contribution = holdings.groupby("sector")["net_contribution"].sum()
    name_abs = float(name_contribution.abs().sum())
    sector_abs = float(sector_contribution.abs().sum())
    summary = {
        "variant_id": variant.variant_id,
        "rebalance_sessions": rebalance_sessions,
        "cost_bps": cost_bps,
        "windows": list(windows),
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "relative_excess": (1.0 + total_return) / (1.0 + benchmark_return) - 1.0,
        "max_drawdown": max_drawdown(periods["net_return"]),
        "turnover": float(periods["turnover"].sum()),
        "positive_excess_windows": int((window_results["relative_excess"] > 0.0).sum()),
        "portfolio_benchmark_hit_rate": float(periods["benchmark_hit"].mean()),
        "precision_at_k": float(holdings["precision_hit"].mean()),
        "maximum_name_absolute_contribution_share": (
            float(name_contribution.abs().max() / name_abs) if name_abs else 1.0
        ),
        "maximum_sector_absolute_contribution_share": (
            float(sector_contribution.abs().max() / sector_abs) if sector_abs else 1.0
        ),
        "top_contributor_name": str(name_contribution.abs().idxmax()),
        "top_contributor_sector": str(sector_contribution.abs().idxmax()),
        "rebalance_count": int(len(periods)),
    }
    return summary, periods, holdings, window_results


def block_bootstrap_relative_excess(
    periods: pd.DataFrame,
    *,
    samples: int = 5000,
    block_size: int = 3,
    seed: int = 20260805,
) -> dict[str, float | int]:
    """Deterministic moving-block bootstrap of compounded relative excess."""

    values = periods["relative_log_return"].to_numpy(dtype=float)
    if not len(values):
        raise ValueError("bootstrap requires non-empty periods")
    block_size = max(1, min(block_size, len(values)))
    starts = np.arange(0, len(values) - block_size + 1)
    rng = np.random.default_rng(seed)
    output = np.empty(samples, dtype=float)
    blocks_needed = int(np.ceil(len(values) / block_size))
    for index in range(samples):
        sampled = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            sampled.extend(values[start : start + block_size])
        output[index] = float(np.expm1(np.sum(sampled[: len(values)])))
    return {
        "samples": samples,
        "block_size": block_size,
        "seed": seed,
        "probability_positive": float(np.mean(output > 0.0)),
        "p05": float(np.quantile(output, 0.05)),
        "median": float(np.quantile(output, 0.50)),
        "p95": float(np.quantile(output, 0.95)),
    }
