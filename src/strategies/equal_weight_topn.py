"""Simple equal-weight TOP N strategy.

This strategy selects the top N stocks by prediction score and allocates
equal weight to each. It's designed for quick backtesting and validation
of model predictions without complex risk management.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy


class EqualWeightTopNStrategy(BaseSignalStrategy):
    """Select top N stocks by prediction score, equal weight allocation.

    Parameters
    ----------
    signal : str
        Signal column name (default: "<PRED>").
    topk : int
        Number of top stocks to hold.
    rebalance_steps : int
        Rebalance every N steps (trading days).
    """

    def __init__(
        self,
        signal: str = "<PRED>",
        topk: int = 15,
        rebalance_steps: int = 20,
        **kwargs: Any,
    ):
        super().__init__(signal=signal, **kwargs)
        self.topk = topk
        self.rebalance_steps = rebalance_steps
        self._last_rebalance = -999

    def generate_trade_decision(self, execute_result=None):
        """Generate trade decision for the current step."""
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)

        # Get prediction signal
        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)
        if isinstance(pred_score, pd.DataFrame):
            pred_score = pred_score.iloc[:, 0]
        if pred_score is None:
            return TradeDecisionWO([], self)

        # Check if rebalance day
        if trade_step - self._last_rebalance < self.rebalance_steps:
            return TradeDecisionWO([], self)

        self._last_rebalance = trade_step

        # Select top N stocks
        pred_score = pred_score.sort_values(ascending=False)
        top_stocks = pred_score.head(self.topk)

        if len(top_stocks) == 0:
            return TradeDecisionWO([], self)

        # Generate buy orders for top stocks
        # Use a small amount per stock (executor will handle sizing)
        amount_per_stock = 1000000.0  # Large enough to be filled

        orders = []
        for instrument in top_stocks.index:
            orders.append(
                Order(
                    stock_id=instrument,
                    amount=amount_per_stock,
                    direction=OrderDir.BUY,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                )
            )

        return TradeDecisionWO(orders, self)
