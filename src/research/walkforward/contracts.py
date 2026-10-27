"""Data contracts and schemas for Walk-Forward quantitative research.

Governed under Track B (#1296) and ADR-0005.
Enforces immutable receipts, strictly partitioned Out-of-Sample (OOS) folds,
and cryptographic data hash bindings.

Boundaries:
- research_only=true, trade_ready=false, trade_signal=false.
- No live trading signals, no secondary storage engines, no background schedulers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WalkForwardFold:
    """Declared temporal partition for one Walk-Forward fold."""

    fold_id: str
    train_start: str
    train_end: str
    train_cutoff: str
    test_start: str
    test_end: str
    test_cutoff: str
    purged_margin_days: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalkForwardConfig:
    """Declared parameter specification for a complete Walk-Forward study."""

    study_id: str
    hypothesis_name: str
    hypothesis_description: str
    market: str
    pool_id: str
    symbols: tuple[str, ...]
    benchmark: str
    price_mode: str
    folds: tuple[WalkForwardFold, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "hypothesis_name": self.hypothesis_name,
            "hypothesis_description": self.hypothesis_description,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": list(self.symbols),
            "benchmark": self.benchmark,
            "price_mode": self.price_mode,
            "folds": [f.to_dict() for f in self.folds],
        }


@dataclass(frozen=True)
class FoldResult:
    """Empirical realization metrics for one Out-of-Sample fold."""

    fold_id: str
    status: str
    train_data_hash: str
    test_data_hash: str
    train_row_count: int
    test_row_count: int
    in_sample_ic_mean: float
    out_of_sample_cumulative_return: float
    benchmark_cumulative_return: float
    out_of_sample_excess_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    turnover_ratio: float
    trade_ready: bool = False
    research_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalkForwardStudyResult:
    """Immutable sealed study result containing all folds and overall OOS trajectory."""

    study_id: str
    hypothesis_name: str
    market: str
    pool_id: str
    symbols: list[str]
    benchmark: str
    folds: list[FoldResult]
    overall_oos_cumulative_return: float
    overall_benchmark_cumulative_return: float
    overall_oos_excess_return: float
    overall_oos_sharpe_ratio: float
    overall_oos_max_drawdown: float
    study_hash: str
    generated_at_utc: str
    research_only: bool = True
    trade_ready: bool = False
    trade_signal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "hypothesis_name": self.hypothesis_name,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": self.symbols,
            "benchmark": self.benchmark,
            "folds": [f.to_dict() for f in self.folds],
            "overall_oos_cumulative_return": self.overall_oos_cumulative_return,
            "overall_benchmark_cumulative_return": self.overall_benchmark_cumulative_return,
            "overall_oos_excess_return": self.overall_oos_excess_return,
            "overall_oos_sharpe_ratio": self.overall_oos_sharpe_ratio,
            "overall_oos_max_drawdown": self.overall_oos_max_drawdown,
            "study_hash": self.study_hash,
            "generated_at_utc": self.generated_at_utc,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "trade_signal": self.trade_signal,
        }
