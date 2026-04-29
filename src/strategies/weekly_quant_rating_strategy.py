from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy
from qlib.data import D

from src.strategies.weekly_quant_rating_rules import (
    is_last_trading_day_of_week,
    select_target,
    select_top_fraction,
    update_streaks,
)


class WeeklyQuantRatingStrategy(BaseSignalStrategy):
    """
    Placeholder implementation for a weekly-only quant-rating strategy.
    Full trading logic is implemented incrementally with tests.
    """

    def __init__(
        self,
        *,
        universe_size: int = 30,
        strongbuy_consecutive_days: int = 3,
        strongbuy_fraction: float = 0.2,
        lookback_days: int = 20,
        min_dollar_vol_20d: float = 10_000_000,
        price_cap: float = 10_000,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.universe_size = universe_size
        self.strongbuy_consecutive_days = strongbuy_consecutive_days
        self.strongbuy_fraction = strongbuy_fraction
        self.lookback_days = lookback_days
        self.min_dollar_vol_20d = min_dollar_vol_20d
        self.price_cap = price_cap
        self._streaks: dict[str, int] = {}

    def _get_current_date(self, trade_start_time) -> date:
        return pd.Timestamp(trade_start_time).date()

    def _get_next_trade_date(self, trade_step: int) -> date | None:
        try:
            t, _ = self.trade_calendar.get_step_time(trade_step, shift=-1)
            return pd.Timestamp(t).date()
        except Exception:
            try:
                # Fallback: try qlib calendar for next trading day
                cur, _ = self.trade_calendar.get_step_time(trade_step)
                cur_date = pd.Timestamp(cur).date()
                cal = D.calendar(start_time=cur_date, end_time=cur_date + pd.Timedelta(days=10))
                cal = [pd.Timestamp(x).date() for x in cal]
                future = [d for d in cal if d > cur_date]
                return future[0] if future else None
            except Exception:
                return None

    def _normalize_signal(self, pred_score):
        if pred_score is None:
            return None
        if isinstance(pred_score, pd.DataFrame):
            if pred_score.shape[1] >= 1:
                pred_score = pred_score.iloc[:, 0]
            else:
                return None
        if isinstance(pred_score, pd.Series) and isinstance(pred_score.index, pd.MultiIndex):
            # If (datetime, instrument) or (instrument, datetime), slice to the last datetime
            # and return a series indexed by instrument. Some Signal implementations may drop
            # MultiIndex names, so we detect the datetime level by dtype/value shape.
            try:
                if "datetime" in pred_score.index.names:
                    last_dt = max(pred_score.index.get_level_values("datetime"))
                    pred_score = pred_score.xs(last_dt, level="datetime")
                elif pred_score.index.nlevels == 2:
                    lv0 = pred_score.index.get_level_values(0)
                    lv1 = pred_score.index.get_level_values(1)

                    def looks_like_dt(values) -> bool:
                        if len(values) == 0:
                            return False
                        v = values[0]
                        return isinstance(v, (pd.Timestamp, datetime, np.datetime64))

                    dt_level = None
                    if looks_like_dt(lv0):
                        dt_level = 0
                    elif looks_like_dt(lv1):
                        dt_level = 1

                    if dt_level is not None:
                        last_dt = max(pred_score.index.get_level_values(dt_level))
                        pred_score = pred_score.xs(last_dt, level=dt_level)
            except Exception:
                pass
        return pred_score

    def _compute_eligibility(self, instruments, asof_time) -> dict[str, bool]:
        """
        Note: calling `D.features` with many instruments can be very slow.
        We intentionally fetch per-instrument here (weekly cadence only).
        """
        instruments = [str(x) for x in (instruments or []) if str(x)]
        if not instruments:
            return {}

        lookback = max(1, int(self.lookback_days))
        fields = ["$close", f"Mean($money, {lookback})", f"Min($volume, {lookback})"]

        result: dict[str, bool] = {}
        for inst in instruments:
            try:
                df = D.features([inst], fields, start_time=asof_time, end_time=asof_time)
            except Exception:
                result[inst] = False
                continue
            if df is None or df.empty:
                result[inst] = False
                continue

            df.columns = ["close", "money_mean", "volume_min"]
            try:
                row = df.xs(inst, level="instrument").iloc[-1]
            except Exception:
                result[inst] = False
                continue

            close = float(row["close"]) if pd.notna(row["close"]) else np.nan
            money_mean = float(row["money_mean"]) if pd.notna(row["money_mean"]) else np.nan
            vol_min = float(row["volume_min"]) if pd.notna(row["volume_min"]) else np.nan

            ok = True
            if not (close < float(self.price_cap)):
                ok = False
            if not (money_mean >= float(self.min_dollar_vol_20d)):
                ok = False
            if not (vol_min > 0):
                ok = False

            result[inst] = ok

        return result

    def generate_trade_decision(self, execute_result=None):
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)

        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)
        pred_score = self._normalize_signal(pred_score)
        if pred_score is None or len(pred_score) == 0:
            return TradeDecisionWO([], self)

        # Update streaks based on StrongBuy = top fraction of the universe by score
        items = [(str(k), float(v)) for k, v in pred_score.items()]
        strongbuy_today = select_top_fraction(items, self.strongbuy_fraction)
        self._streaks = update_streaks(self._streaks, strongbuy_today)

        current_date = self._get_current_date(trade_start_time)
        next_trade_date = self._get_next_trade_date(trade_step)
        rebalance_day = is_last_trading_day_of_week(current_date, next_trade_date)
        if not rebalance_day:
            return TradeDecisionWO([], self)

        min_streak = max(1, int(self.strongbuy_consecutive_days))
        candidates = [inst for inst, v in self._streaks.items() if int(v) >= min_streak]
        if not candidates:
            return TradeDecisionWO([], self)

        # Only evaluate tradability filters for streak-qualified candidates (weekly cadence)
        # NOTE: `pred_end_time` is the right endpoint of the interval and can fall on
        # non-trading days (e.g., Fri interval ends on Sun when next trading day is Mon).
        # Use `pred_start_time` (a trading timestamp) for any point-in-time market data queries.
        eligibility = self._compute_eligibility(candidates, pred_start_time)
        target = select_target(
            scores_by_instrument={
                inst: float(pred_score.get(inst)) for inst in candidates if inst in pred_score.index
            },
            streaks=self._streaks,
            eligible_by_instrument=eligibility,
            strongbuy_consecutive_days=self.strongbuy_consecutive_days,
            universe_size=self.universe_size,
        )
        if not target:
            return TradeDecisionWO([], self)

        target_set = set(target)
        orders = []

        # Sell anything not in target (weekly-only turnover rule)
        for code in list(self.trade_position.get_stock_list()):
            if code in target_set:
                continue
            if not self.trade_exchange.is_stock_tradable(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.SELL,
            ):
                continue
            amt = float(self.trade_position.get_stock_amount(code))
            if amt <= 0:
                continue
            sell_order = Order(
                stock_id=code,
                amount=amt,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.SELL,
            )
            if self.trade_exchange.check_order(sell_order):
                orders.append(sell_order)

        cash = float(self.trade_position.get_cash())
        value_per = cash * float(self.risk_degree) / len(target)

        for code in target:
            if not self.trade_exchange.is_stock_tradable(
                stock_id=code, start_time=trade_start_time, end_time=trade_end_time
            ):
                continue
            price = self.trade_exchange.get_deal_price(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.BUY,
            )
            if price is None or np.isnan(price) or price <= 0:
                continue
            amount = value_per / float(price)
            factor = self.trade_exchange.get_factor(
                stock_id=code, start_time=trade_start_time, end_time=trade_end_time
            )
            amount = self.trade_exchange.round_amount_by_trade_unit(amount, factor)
            if amount is None or np.isnan(amount) or amount <= 0:
                continue
            order = Order(
                stock_id=code,
                amount=amount,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.BUY,
            )
            if self.trade_exchange.check_order(order):
                orders.append(order)

        return TradeDecisionWO(orders, self)
