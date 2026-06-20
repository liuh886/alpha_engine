"""Vectorized Biweekly Strategy — uses pre-computed signals for fast backtesting.

Drop-in replacement for BiweeklyTrendStrategy that uses VectorizedSignalPrecomputer
to avoid per-bar D.features() calls.

Usage:
    # In strategy profile config:
    strategy:
      class: VectorizedBiweeklyStrategy
      kwargs:
        use_precomputed: true
"""

from __future__ import annotations

import copy
from datetime import date

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy

from src.common.logging import get_logger
from src.strategies.biweekly_trend_rules import can_sell, is_rebalance_day

logger = get_logger(__name__)


class VectorizedBiweeklyStrategy(BaseSignalStrategy):
    """Vectorized biweekly strategy using pre-computed signals.

    When precomputed_signals is provided, uses vectorized operations instead
    of per-bar D.features() calls. Falls back to standard behavior otherwise.
    """

    # Class-level shared precomputed signals (set before backtest starts)
    _precomputed = None

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
        use_risk_manager: bool = False,
        risk_config: dict | None = None,
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

        # Risk management
        self.use_risk_manager = use_risk_manager
        self._risk_manager = None
        if use_risk_manager:
            from src.guardrails.position_risk import (
                PositionRiskConfig,
                PositionRiskManager,
            )

            cfg = PositionRiskConfig(**(risk_config or {}))
            self._risk_manager = PositionRiskManager(cfg)

    @classmethod
    def set_precomputed(cls, signals):
        """Set pre-computed signals for all instances."""
        cls._precomputed = signals

    def _get_current_date(self, trade_start_time) -> date:
        return pd.Timestamp(trade_start_time).date()

    def _estimate_entry_price(self, code: str, position) -> float:
        try:
            return float(position.get_stock_price(code))
        except Exception:
            return 0.0

    def generate_trade_decision(self, execute_result=None):
        """Generate trade decisions using vectorized operations when possible."""
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)

        # Get signal (use precomputed if available)
        if self._precomputed is not None:
            prediction_dt = pd.Timestamp(pred_start_time)
            pred_score = self._precomputed.get_scores_on_date(prediction_dt)
            if pred_score.empty:
                return TradeDecisionWO([], self)
        else:
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

        # --- Sell checks ---
        sell_candidates: set[str] = set()

        # MA cross-under (vectorized if precomputed)
        if current_stock_list:
            if self._precomputed is not None:
                current_dt = pd.Timestamp(trade_start_time)
                ma_cross = self._precomputed.is_ma_cross_under(current_dt)
                for code in current_stock_list:
                    entry_date = self.entry_dates.get(code)
                    if not can_sell(entry_date, current_date, self.min_hold_days):
                        continue
                    if code in ma_cross.index and ma_cross[code]:
                        sell_candidates.add(code)
            else:
                # Fallback: per-stock MA check
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

        # Risk manager checks
        if self._risk_manager is not None and current_stock_list:
            from src.data.sector_map import get_sector_map
            from src.guardrails.position_risk import PositionInfo

            sample_inst = current_stock_list[0]
            mkt = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
            try:
                sector_map = get_sector_map(mkt)
            except Exception:
                sector_map = {}

            total_value = float(current_temp.get_cash()) + float(current_temp.calculate_stock_value())
            risk_positions: dict[str, PositionInfo] = {}
            for code in current_stock_list:
                held_positions.get(code, {}) if (held_positions := {}) else {}
                stock_val = float(current_temp.get_stock_price(code)) * float(current_temp.get_stock_amount(code))
                risk_positions[code] = PositionInfo(
                    instrument=code,
                    weight=stock_val / total_value if total_value > 0 else 0.0,
                    entry_price=self._estimate_entry_price(code, current_temp),
                    current_price=float(current_temp.get_stock_price(code)),
                    peak_price=float(current_temp.get_stock_price(code)),
                    sector=sector_map.get(code, "Unknown"),
                )

            for sig in self._risk_manager.check_stop_loss(risk_positions):
                inst = sig.instrument
                if inst not in sell_candidates:
                    entry_date = self.entry_dates.get(inst)
                    if can_sell(entry_date, current_date, self.min_hold_days):
                        sell_candidates.add(inst)

            for sig in self._risk_manager.check_trailing_stop(risk_positions):
                inst = sig.instrument
                if inst not in sell_candidates:
                    entry_date = self.entry_dates.get(inst)
                    if can_sell(entry_date, current_date, self.min_hold_days):
                        sell_candidates.add(inst)

        # Rebalance-day rank/score sell
        if rebalance_day:
            for code in current_stock_list:
                entry_date = self.entry_dates.get(code)
                if not can_sell(entry_date, current_date, self.min_hold_days):
                    continue
                rank = rank_map.get(code)
                if rank is None or rank >= self.sell_rank_threshold:
                    sell_candidates.add(code)
                if self.sell_score_threshold is not None:
                    score = pred_score.get(code)
                    if score is not None and score < self.sell_score_threshold:
                        sell_candidates.add(code)

        # Execute sells
        sell_order_list: list[Order] = []
        buy_order_list: list[Order] = []
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

        # --- Buy checks (rebalance day) ---
        if rebalance_day:
            current_stock_list = current_temp.get_stock_list()
            desired_topk = list(pred_score.index[: self.topk])
            available_slots = max(0, self.topk - len(current_stock_list))
            buy_list = [code for code in desired_topk if code not in current_stock_list]

            if self.buy_score_threshold is not None:
                buy_list = [c for c in buy_list if pred_score.get(c, 0) > self.buy_score_threshold]

            buy_list = buy_list[:available_slots]

            # Equal-weight sizing
            if buy_list:
                eq_value = cash * self.risk_degree / len(buy_list)
                value_map = {code: eq_value for code in buy_list}

                for code in buy_list:
                    if not self.trade_exchange.is_stock_tradable(
                        stock_id=code,
                        start_time=trade_start_time,
                        end_time=trade_end_time,
                        direction=None if self.forbid_all_trade_at_limit else OrderDir.BUY,
                    ):
                        continue

                    max_allowed_buy_val = cash * 0.15
                    target_value = min(value_map.get(code, 0), max_allowed_buy_val)

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

    def _get_ma_map(self, instruments, start_time, end_time):
        """Fallback: fetch MA data via D.features()."""
        if not instruments:
            return {}
        from qlib.data import D

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
