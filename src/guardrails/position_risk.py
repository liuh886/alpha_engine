"""Position-level risk management: stop-loss, trailing stop, position/sector limits,
and volatility-adjusted sizing.

All risk controls are opt-in via PositionRiskConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd
import structlog

log = structlog.get_logger()


class SignalType(str, Enum):
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    POSITION_LIMIT = "position_limit"
    SECTOR_LIMIT = "sector_limit"


class ActionType(str, Enum):
    SELL = "sell"
    REDUCE = "reduce"
    BLOCK_BUY = "block_buy"


@dataclass
class PositionRiskConfig:
    """All thresholds are configurable; no magic numbers."""

    stop_loss_pct: float = -0.10
    trailing_stop_pct: float = -0.15
    max_position_weight: float = 0.20
    max_sector_weight: float = 0.35
    target_portfolio_vol: float = 0.15


@dataclass
class PositionInfo:
    """Snapshot of a single position for risk evaluation."""

    instrument: str
    weight: float
    entry_price: float
    current_price: float
    peak_price: float
    sector: str = ""


@dataclass
class PositionRiskSignal:
    """A single risk signal emitted by the risk manager."""

    instrument: str
    signal_type: SignalType
    current_value: float
    threshold: float
    action: ActionType
    reason: str

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "signal_type": self.signal_type.value,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "action": self.action.value,
            "reason": self.reason,
        }


class PositionRiskManager:
    """Evaluates portfolio positions against configurable risk limits.

    All checks are pure functions — they inspect positions and return signals
    without side effects. The caller decides what to do with each signal.
    """

    def __init__(self, config: PositionRiskConfig | None = None):
        self.config = config or PositionRiskConfig()

    def check_stop_loss(self, positions: dict[str, PositionInfo]) -> list[PositionRiskSignal]:
        """Check simple stop-loss: current_price vs entry_price."""
        signals: list[PositionRiskSignal] = []
        threshold = self.config.stop_loss_pct

        for inst, pos in positions.items():
            if pos.entry_price <= 0:
                continue
            pnl_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            if pnl_pct <= threshold:
                signals.append(
                    PositionRiskSignal(
                        instrument=inst,
                        signal_type=SignalType.STOP_LOSS,
                        current_value=round(pnl_pct, 4),
                        threshold=threshold,
                        action=ActionType.SELL,
                        reason=(f"Stop-loss triggered: {pnl_pct:.2%} (threshold {threshold:.2%})"),
                    )
                )

        return signals

    def check_trailing_stop(self, positions: dict[str, PositionInfo]) -> list[PositionRiskSignal]:
        """Check trailing stop: current_price vs peak_price."""
        signals: list[PositionRiskSignal] = []
        threshold = self.config.trailing_stop_pct

        for inst, pos in positions.items():
            if pos.peak_price <= 0:
                continue
            drawdown = (pos.current_price - pos.peak_price) / pos.peak_price
            if drawdown <= threshold:
                signals.append(
                    PositionRiskSignal(
                        instrument=inst,
                        signal_type=SignalType.TRAILING_STOP,
                        current_value=round(drawdown, 4),
                        threshold=threshold,
                        action=ActionType.SELL,
                        reason=(
                            f"Trailing stop triggered: {drawdown:.2%} from peak "
                            f"(threshold {threshold:.2%})"
                        ),
                    )
                )

        return signals

    def check_position_limits(self, positions: dict[str, PositionInfo]) -> list[PositionRiskSignal]:
        """Check if any single position exceeds max_position_weight."""
        signals: list[PositionRiskSignal] = []
        threshold = self.config.max_position_weight

        for inst, pos in positions.items():
            if pos.weight > threshold:
                signals.append(
                    PositionRiskSignal(
                        instrument=inst,
                        signal_type=SignalType.POSITION_LIMIT,
                        current_value=round(pos.weight, 4),
                        threshold=threshold,
                        action=ActionType.REDUCE,
                        reason=(f"Position weight {pos.weight:.2%} exceeds limit {threshold:.2%}"),
                    )
                )

        return signals

    def check_sector_exposure(self, positions: dict[str, PositionInfo]) -> list[PositionRiskSignal]:
        """Check if any sector exceeds max_sector_weight."""
        signals: list[PositionRiskSignal] = []
        threshold = self.config.max_sector_weight

        sector_weights: dict[str, float] = {}
        for pos in positions.values():
            sector = pos.sector or "Unknown"
            sector_weights[sector] = sector_weights.get(sector, 0.0) + pos.weight

        for sector, weight in sector_weights.items():
            if weight > threshold:
                instruments_in_sector = [
                    inst for inst, pos in positions.items() if (pos.sector or "Unknown") == sector
                ]
                signals.append(
                    PositionRiskSignal(
                        instrument=", ".join(instruments_in_sector),
                        signal_type=SignalType.SECTOR_LIMIT,
                        current_value=round(weight, 4),
                        threshold=threshold,
                        action=ActionType.REDUCE,
                        reason=(
                            f"Sector '{sector}' weight {weight:.2%} exceeds limit {threshold:.2%}"
                        ),
                    )
                )

        return signals

    def compute_vol_adjusted_weights(
        self,
        instruments: list[str],
        scores: pd.Series,
        volatilities: pd.Series,
    ) -> pd.Series:
        """Inverse-volatility weighting.

        Lower vol -> higher weight.  Weights sum to 1.0.
        Formula: w_i = (1/vol_i) / sum(1/vol_j)

        Only instruments present in both ``scores`` and ``volatilities`` with
        positive volatility are included.
        """
        if not instruments:
            return pd.Series(dtype=float)

        common = [i for i in instruments if i in volatilities.index and i in scores.index]
        if not common:
            log.warning("No common instruments for vol-adjusted weighting")
            return pd.Series(dtype=float)

        vols = volatilities.loc[common]
        # Filter out zero/negative/NaN volatilities
        valid_mask = (vols > 0) & vols.notna()
        vols = vols[valid_mask]
        if vols.empty:
            log.warning("All volatilities invalid; falling back to equal weight")
            return pd.Series(1.0 / len(common), index=common)

        inv_vol = 1.0 / vols
        weights = inv_vol / inv_vol.sum()

        # Reindex to full instrument list (0 for excluded)
        result = pd.Series(0.0, index=common)
        result.loc[weights.index] = weights.values

        log.debug(
            "Vol-adjusted weights computed",
            n_instruments=len(weights),
            min_vol=round(float(vols.min()), 4),
            max_vol=round(float(vols.max()), 4),
        )
        return result

    def evaluate_portfolio(self, positions: dict[str, PositionInfo]) -> list[PositionRiskSignal]:
        """Run ALL risk checks and return aggregated signals."""
        signals: list[PositionRiskSignal] = []
        signals.extend(self.check_stop_loss(positions))
        signals.extend(self.check_trailing_stop(positions))
        signals.extend(self.check_position_limits(positions))
        signals.extend(self.check_sector_exposure(positions))

        if signals:
            log.info(
                "Risk signals generated",
                n_signals=len(signals),
                types=[s.signal_type.value for s in signals],
            )
        return signals
