"""Data contracts and schemas for Walk-Forward quantitative research.

Governed under Track B (#1296) and ADR-0005.
Enforces immutable receipts, strictly partitioned Out-of-Sample (OOS) folds,
purged margin execution, in-sample parameter selection, transaction cost sensitivity,
and cryptographic data hash bindings.

Boundaries:
- research_only=true, trade_ready=false, trade_signal=false.
- No live trading signals, no secondary storage engines, no background schedulers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_PIT_LIMITATIONS: tuple[str, ...] = (
    "Observation cutoff boundary verified (end_date <= as_of_cutoff); not certified under full PIT revision history (pit_certified: false).",
    "Candidate pool (8 equities) is fixed ex-post from us_selected_equities_v2; full historical point-in-time constituent reconstitution is not simulated (survivorship/selection bias acknowledged).",
    "Vendor availability timestamp (t_available) and restatement lineage are not individually verified for all historical bars.",
)


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
    cost_bps: float = 3.0  # 3 bps transaction commission per turnover
    slippage_bps: float = 5.0  # 5 bps slippage per turnover (total friction 8 bps)
    param_grid: dict[str, tuple[float, ...]] = field(
        default_factory=lambda: {
            "w_rev": (0.5, 1.0, 1.5),
            "w_vol": (0.5, 1.0, 1.5),
            "top_k": (2.0, 3.0),
        }
    )

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
            "cost_bps": self.cost_bps,
            "slippage_bps": self.slippage_bps,
            "param_grid": {k: list(v) for k, v in self.param_grid.items()},
            "folds": [f.to_dict() for f in self.folds],
        }


@dataclass(frozen=True)
class FoldResult:
    """Empirical realization metrics for one Out-of-Sample fold."""

    fold_id: str
    status: str
    blocked_reasons: tuple[str, ...] = ()
    train_data_hash: str = ""
    test_data_hash: str = ""
    train_row_count: int = 0
    test_row_count: int = 0
    purged_rows_count: int = 0
    selected_parameters: dict[str, Any] = field(default_factory=dict)
    in_sample_best_sharpe: float = 0.0
    in_sample_ic_mean: float = 0.0
    out_of_sample_gross_return: float = 0.0
    out_of_sample_net_return: float = 0.0
    benchmark_cumulative_return: float = 0.0
    out_of_sample_net_excess_return: float = 0.0
    annualized_volatility: float = 0.0
    sharpe_ratio: float = 0.0  # Net Sharpe
    gross_sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    turnover_ratio: float = 0.0
    total_cost_drag: float = 0.0
    cost_sensitivity: dict[str, float] = field(default_factory=dict)
    daily_net_returns: tuple[float, ...] = ()
    oos_sessions_count: int = 0
    pit_limitations: tuple[str, ...] = DEFAULT_PIT_LIMITATIONS
    trade_ready: bool = False
    research_only: bool = True

    @property
    def out_of_sample_cumulative_return(self) -> float:
        """Alias for backward compatibility."""
        return self.out_of_sample_net_return

    @property
    def out_of_sample_excess_return(self) -> float:
        """Alias for backward compatibility."""
        return self.out_of_sample_net_excess_return

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["out_of_sample_cumulative_return"] = self.out_of_sample_net_return
        d["out_of_sample_excess_return"] = self.out_of_sample_net_excess_return
        d["blocked_reasons"] = list(self.blocked_reasons)
        d["pit_limitations"] = list(self.pit_limitations)
        return d


@dataclass(frozen=True)
class WalkForwardStudyResult:
    """Immutable sealed study result containing all folds and overall OOS trajectory."""

    study_id: str
    status: str  # "ready" or "blocked"
    blocked_reasons: tuple[str, ...]
    hypothesis_name: str
    market: str
    pool_id: str
    symbols: list[str]
    benchmark: str
    folds: list[FoldResult]
    overall_oos_gross_return: float
    overall_oos_net_return: float
    overall_benchmark_cumulative_return: float
    overall_oos_net_excess_return: float
    overall_oos_sharpe_ratio: float
    overall_oos_max_drawdown: float
    cost_sensitivity_summary: dict[str, float]
    study_hash: str
    generated_at_utc: str
    git_commit: str = ""
    config_hash: str = ""
    code_source_sha256: dict[str, str] = field(default_factory=dict)
    experiment_receipt: dict[str, Any] = field(default_factory=dict)
    pit_limitations: tuple[str, ...] = DEFAULT_PIT_LIMITATIONS
    research_only: bool = True
    trade_ready: bool = False
    trade_signal: bool = False

    @property
    def overall_oos_cumulative_return(self) -> float:
        """Alias for backward compatibility."""
        return self.overall_oos_net_return

    @property
    def overall_oos_excess_return(self) -> float:
        """Alias for backward compatibility."""
        return self.overall_oos_net_excess_return

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "status": self.status,
            "blocked_reasons": list(self.blocked_reasons),
            "hypothesis_name": self.hypothesis_name,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": self.symbols,
            "benchmark": self.benchmark,
            "git_commit": self.git_commit,
            "config_hash": self.config_hash,
            "code_source_sha256": self.code_source_sha256,
            "experiment_receipt": self.experiment_receipt,
            "folds": [f.to_dict() for f in self.folds],
            "overall_oos_gross_return": self.overall_oos_gross_return,
            "overall_oos_net_return": self.overall_oos_net_return,
            "overall_oos_cumulative_return": self.overall_oos_net_return,
            "overall_benchmark_cumulative_return": self.overall_benchmark_cumulative_return,
            "overall_oos_net_excess_return": self.overall_oos_net_excess_return,
            "overall_oos_excess_return": self.overall_oos_net_excess_return,
            "overall_oos_sharpe_ratio": self.overall_oos_sharpe_ratio,
            "overall_oos_max_drawdown": self.overall_oos_max_drawdown,
            "cost_sensitivity_summary": self.cost_sensitivity_summary,
            "pit_limitations": list(self.pit_limitations),
            "study_hash": self.study_hash,
            "generated_at_utc": self.generated_at_utc,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "trade_signal": self.trade_signal,
        }
