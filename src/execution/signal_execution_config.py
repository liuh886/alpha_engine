"""Frozen configuration for the standalone signal execution engine.

Replaces Qlib strategy kwargs with a flat, type-safe, immutable config.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalExecutionConfig:
    """Frozen configuration for the standalone signal execution engine.

    All validation happens in ``__post_init__`` so misconfiguration is caught
    early, before any data is loaded or computation runs.
    """

    # ------------------------------------------------------------------
    # Market identity
    # ------------------------------------------------------------------
    market: str = "cn"
    """Market identifier: ``"cn"`` or ``"us"``. Affects benchmark symbol
    resolution and Qlib init paths."""

    # ------------------------------------------------------------------
    # Grade-based position sizing
    # ------------------------------------------------------------------
    step_size: int = 10
    """Number of stocks per grade tier. AAA = top N, AA = top 2N,
    A = top 3N, V = bottom 3N, VV = bottom 2N, VVV = bottom N."""

    grade_weights: dict[str, float] = field(default_factory=lambda: {
        "AAA": 3.0,
        "AA": 2.0,
        "A": 1.0,
        "V": -1.0,
        "VV": -2.0,
        "VVV": -3.0,
    })
    """Raw weight multiplier per grade. Positive = long, negative = short.
    Higher absolute value = stronger conviction position."""

    # ------------------------------------------------------------------
    # Long / short allocation
    # ------------------------------------------------------------------
    long_fraction: float = 0.8
    """Fraction of capital allocated to the long basket. Must be in (0, 1]."""

    short_fraction: float = 0.2
    """Fraction of capital allocated to the short basket. 0.0 = long-only."""

    max_single_position_weight: float = 0.15
    """Hard cap on any single stock's portfolio weight (post-normalization)."""

    min_stocks_per_side: int = 3
    """If a side (long or short) has fewer than this many graded stocks,
    that side is skipped entirely (zero allocation)."""

    # ------------------------------------------------------------------
    # Market regime filter
    # ------------------------------------------------------------------
    enable_regime_filter: bool = True
    """When True, the three-pillar regime filter scales exposure dynamically."""

    ic_lookback_days: int = 60
    """Trading days of IC history used for decay detection."""

    ic_decay_threshold: float = -0.01
    """Rolling IC slope below this value triggers 'decaying signal' regime.
    Exposure scales linearly from 1.0 at threshold to 0.0 at 2× threshold."""

    vol_ratio_threshold: float = 2.0
    """Short-term / long-term volatility ratio threshold (reuses
    ``check_volatility_regime`` from ``src/guardrails/rules.py``)."""

    trend_ma_window: int = 60
    """Benchmark simple moving average window for bear-market detection."""

    # ------------------------------------------------------------------
    # Execution mechanics
    # ------------------------------------------------------------------
    rebalance_days: int = 10
    """Rebalance interval in trading days. Should match the model's
    prediction horizon."""

    initial_capital: float = 10000.0
    """Starting portfolio value."""

    buy_cost_bps: float = 10.0
    """Per-transaction cost for buy orders in basis points."""

    sell_cost_bps: float = 10.0
    """Per-transaction cost for sell orders in basis points."""

    # ------------------------------------------------------------------
    # Benchmark
    # ------------------------------------------------------------------
    benchmark_symbol: str = "000300"
    """Qlib instrument identifier for the benchmark index."""

    benchmark_label_expr: str = "Ref($close, -10) / Ref($close, -1) - 1"
    """Qlib label expression for benchmark returns."""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        if self.market not in ("cn", "us"):
            raise ValueError(f"market must be 'cn' or 'us', got {self.market!r}")
        if self.long_fraction <= 0 or self.long_fraction > 1:
            raise ValueError(
                f"long_fraction must be in (0, 1], got {self.long_fraction}"
            )
        if self.short_fraction < 0 or self.short_fraction > 1:
            raise ValueError(
                f"short_fraction must be in [0, 1], got {self.short_fraction}"
            )
        if self.long_fraction + self.short_fraction > 1.0:
            raise ValueError(
                "long_fraction + short_fraction must not exceed 1.0, "
                f"got {self.long_fraction} + {self.short_fraction}"
            )
        if self.rebalance_days <= 0:
            raise ValueError(
                f"rebalance_days must be positive, got {self.rebalance_days}"
            )
        if self.step_size <= 0:
            raise ValueError(
                f"step_size must be positive, got {self.step_size}"
            )
        if self.max_single_position_weight <= 0:
            raise ValueError(
                "max_single_position_weight must be positive, "
                f"got {self.max_single_position_weight}"
            )
        if self.min_stocks_per_side < 1:
            raise ValueError(
                f"min_stocks_per_side must be >= 1, got {self.min_stocks_per_side}"
            )
        if self.ic_lookback_days < 10:
            raise ValueError(
                f"ic_lookback_days must be >= 10, got {self.ic_lookback_days}"
            )
        if self.buy_cost_bps < 0 or self.sell_cost_bps < 0:
            raise ValueError("cost_bps must be non-negative")
