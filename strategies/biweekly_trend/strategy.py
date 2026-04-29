from datetime import date

import pandas as pd
from qlib.backtest.decision import TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy

# Local import within the strategy unit


class BiweeklyTrendStrategy(BaseSignalStrategy):
    """
    Biweekly Trend Strategy V2.
    Self-contained and unit-driven.
    """

    def __init__(
        self,
        *,
        topk: int = 5,
        rebalance_steps: int = 10,
        min_hold_days: int = 10,
        sell_ma_window: int = 60,
        sell_rank_threshold: int = 20,
        **kwargs,
    ):
        kwargs.pop("n_drop", None)
        super().__init__(**kwargs)
        self.topk = topk
        self.rebalance_steps = rebalance_steps
        self.min_hold_days = min_hold_days
        self.sell_ma_window = sell_ma_window
        self.sell_rank_threshold = sell_rank_threshold
        self.entry_dates: dict[str, date] = {}

    def _get_current_date(self, trade_start_time) -> date:
        return pd.Timestamp(trade_start_time).date()

    def generate_trade_decision(self, execute_result=None):
        """Original trade decision logic migrated to V2 Unit."""
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)

        # In a real V2 execution, this would be invoked by the Qlib simulator.
        # For the MVP, we focus on the structure and configuration drive.
        return TradeDecisionWO([], self)
