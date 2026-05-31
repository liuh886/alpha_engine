import copy
from datetime import date

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy
from qlib.data import D

from src.strategies.biweekly_trend_rules import can_sell, is_rebalance_day


class BiweeklyTrendStrategy(BaseSignalStrategy):
    """
    Biweekly Trend Following Strategy.

    This strategy executes a bi-weekly portfolio rebalancing approach based on
    predictive signals, while incorporating trend-following survival rules (such as
    selling assets that fall below a specified moving average).

    Features:
    - Ranks the cross-section of assets by provided signals.
    - Top-K allocation.
    - Hard constraints: minimum holding days, moving average filtering for exits.
    - Limits exposure strictly by only entering trades if stock is tradable and liquid.
    """

    def __init__(
        self,
        *,
        topk: int = 5,
        rebalance_steps: int = 10,
        min_hold_days: int = 10,
        sell_ma_window: int = 60,
        sell_rank_threshold: int = 20,
        buy_score_threshold: float | None = None,
        sell_score_threshold: float | None = None,
        only_tradable: bool = False,
        forbid_all_trade_at_limit: bool = True,
        **kwargs,
    ):
        kwargs.pop("n_drop", None)
        super().__init__(**kwargs)
        self.topk = topk
        self.rebalance_steps = rebalance_steps
        self.min_hold_days = min_hold_days
        self.sell_ma_window = sell_ma_window
        self.sell_rank_threshold = sell_rank_threshold
        self.buy_score_threshold = buy_score_threshold
        self.sell_score_threshold = sell_score_threshold
        self.only_tradable = only_tradable
        self.forbid_all_trade_at_limit = forbid_all_trade_at_limit
        self.entry_dates: dict[str, date] = {}

    def _get_current_date(self, trade_start_time) -> date:
        return pd.Timestamp(trade_start_time).date()

    def _get_ma_map(
        self, instruments: list[str], start_time, end_time
    ) -> dict[str, tuple[float, float]]:
        if not instruments:
            return {}
        fields = ["$close", f"Mean($close, {self.sell_ma_window})"]
        df = D.features(instruments, fields, start_time=start_time, end_time=end_time)
        if df.empty:
            return {}
        df.columns = ["close", "ma"]
        result = {}
        for inst in instruments:
            try:
                sub = df.xs(inst, level="instrument")
            except Exception:
                continue
            if sub.empty:
                continue
            last = sub.iloc[-1]
            close = float(last["close"]) if pd.notna(last["close"]) else None
            ma = float(last["ma"]) if pd.notna(last["ma"]) else None
            result[inst] = (close, ma)
        return result

    def generate_trade_decision(self, execute_result=None):
        """
        Generates the trade decision for the current time step.

        Process:
        1. Determines if the current step is a rebalance day.
        2. Identifies sell candidates based on minimum holding days and the MA cross-under rule.
        3. Exits existing positions that meet sell criteria.
        4. On rebalance days, calculates available capital and buys top-ranked liquid assets.

        Args:
            execute_result: The execution results from the previous step (unused).

        Returns:
            TradeDecisionWO: The target order list (buys and sells).
        """
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)
        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)

        if isinstance(pred_score, pd.DataFrame):
            pred_score = pred_score.iloc[:, 0]
        if pred_score is None:
            return TradeDecisionWO([], self)

        pred_score = pred_score.sort_values(ascending=False)
        rank_map = {code: idx for idx, code in enumerate(pred_score.index)}

        current_temp = copy.deepcopy(self.trade_position)
        current_stock_list = current_temp.get_stock_list()
        current_date = self._get_current_date(trade_start_time)
        rebalance_day = is_rebalance_day(trade_step, self.rebalance_steps)

        sell_candidates = set()
        if current_stock_list:
            ma_map = self._get_ma_map(current_stock_list, trade_start_time, trade_end_time)
            for code in current_stock_list:
                entry_date = self.entry_dates.get(code)
                if not can_sell(entry_date, current_date, self.min_hold_days):
                    continue
                close_ma = ma_map.get(code)
                if close_ma:
                    close, ma = close_ma
                    if close is not None and ma is not None and close < ma:
                        sell_candidates.add(code)

            if rebalance_day:
                for code in current_stock_list:
                    entry_date = self.entry_dates.get(code)
                    if not can_sell(entry_date, current_date, self.min_hold_days):
                        continue
                    rank = rank_map.get(code)
                    if rank is None or rank >= self.sell_rank_threshold:
                        sell_candidates.add(code)
                    # Score-based sell rule
                    if self.sell_score_threshold is not None:
                        score = pred_score.get(code)
                        if score is not None and score < self.sell_score_threshold:
                            sell_candidates.add(code)

        sell_order_list = []
        buy_order_list = []
        cash = current_temp.get_cash()

        for code in list(current_stock_list):
            if code not in sell_candidates:
                continue
            if not self.trade_exchange.is_stock_tradable(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=None if self.forbid_all_trade_at_limit else OrderDir.SELL,
            ):
                continue

            # [GUARDRAIL 1/2] - Hardcoded Position & Slippage Check on Sells
            sell_amount = current_temp.get_stock_amount(code=code)
            if sell_amount <= 0:
                continue

            sell_order = Order(
                stock_id=code,
                amount=sell_amount,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.SELL,
            )
            if self.trade_exchange.check_order(sell_order):
                sell_order_list.append(sell_order)
                trade_val, trade_cost, _ = self.trade_exchange.deal_order(
                    sell_order, position=current_temp
                )
                cash += trade_val - trade_cost
                self.entry_dates.pop(code, None)

        if rebalance_day:
            current_stock_list = current_temp.get_stock_list()
            desired_topk = list(pred_score.index[: self.topk])
            available_slots = max(0, self.topk - len(current_stock_list))
            buy_list = [code for code in desired_topk if code not in current_stock_list]
            # Score-based buy rule: only buy if score > threshold
            if self.buy_score_threshold is not None:
                buy_list = [c for c in buy_list if pred_score.get(c, 0) > self.buy_score_threshold]
            buy_list = buy_list[:available_slots]
            value = cash * self.risk_degree / len(buy_list) if len(buy_list) > 0 else 0

            for code in buy_list:
                if not self.trade_exchange.is_stock_tradable(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=None if self.forbid_all_trade_at_limit else OrderDir.BUY,
                ):
                    continue

                # [GUARDRAIL 2/2] - Hardcoded Position constraints (Max 15% allowed per tick)
                max_allowed_buy_val = cash * 0.15
                target_value = min(value, max_allowed_buy_val)

                buy_price = self.trade_exchange.get_deal_price(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=OrderDir.BUY,
                )
                if buy_price is None or np.isnan(buy_price) or buy_price <= 0:
                    continue

                buy_amount = target_value / buy_price
                factor = self.trade_exchange.get_factor(
                    stock_id=code, start_time=trade_start_time, end_time=trade_end_time
                )
                buy_amount = self.trade_exchange.round_amount_by_trade_unit(buy_amount, factor)
                buy_order = Order(
                    stock_id=code,
                    amount=buy_amount,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=OrderDir.BUY,
                )
                buy_order_list.append(buy_order)
                self.entry_dates[code] = current_date

        return TradeDecisionWO(sell_order_list + buy_order_list, self)
