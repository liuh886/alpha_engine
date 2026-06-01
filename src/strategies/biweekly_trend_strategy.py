import copy
from datetime import date

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy
from qlib.data import D

from src.common.logging import get_logger
from src.strategies.biweekly_trend_rules import can_sell, is_rebalance_day

logger = get_logger(__name__)


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

        # Optional risk management (backward-compatible: disabled by default)
        self.use_risk_manager = use_risk_manager
        self._risk_manager = None
        if use_risk_manager:
            from src.guardrails.position_risk import (
                PositionRiskConfig,
                PositionRiskManager,
            )

            cfg = PositionRiskConfig(**(risk_config or {}))
            self._risk_manager = PositionRiskManager(cfg)
            logger.info("Risk manager enabled", config=cfg)

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

    def _estimate_entry_price(self, code: str, position) -> float:
        """Estimate entry price from position cost basis.

        Falls back to current price if cost basis is unavailable.
        """
        try:
            cost = float(position.get_stock_cost(code))
            amount = float(position.get_stock_amount(code))
            if amount > 0 and cost > 0:
                return cost / amount
        except Exception:
            pass
        return 0.0

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

            # --- Risk manager: stop-loss check (every step, not just rebalance) ---
            if self._risk_manager is not None:
                from src.data.sector_map import get_sector_map
                from src.guardrails.position_risk import PositionInfo

                # Detect market from instrument suffix
                sample_inst = current_stock_list[0] if current_stock_list else ""
                market = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
                try:
                    sector_map = get_sector_map(market)
                except Exception:
                    sector_map = {}

                total_value = float(current_temp.get_cash()) + sum(
                    float(current_temp.get_stock_value(code))
                    for code in current_stock_list
                )
                risk_positions: dict[str, PositionInfo] = {}
                for code in current_stock_list:
                    close_ma = ma_map.get(code)
                    cur_price = close_ma[0] if close_ma and close_ma[0] else 0.0
                    entry_px = self._estimate_entry_price(code, current_temp)
                    stock_val = float(current_temp.get_stock_value(code))
                    risk_positions[code] = PositionInfo(
                        instrument=code,
                        weight=stock_val / total_value if total_value > 0 else 0.0,
                        entry_price=entry_px,
                        current_price=cur_price,
                        peak_price=cur_price,
                        sector=sector_map.get(code, "Unknown"),
                    )

                stop_signals = self._risk_manager.check_stop_loss(risk_positions)
                for sig in stop_signals:
                    inst = sig.instrument
                    if inst not in sell_candidates:
                        entry_date = self.entry_dates.get(inst)
                        if can_sell(entry_date, current_date, self.min_hold_days):
                            sell_candidates.add(inst)
                            logger.info(
                                "Risk: stop-loss sell",
                                instrument=inst,
                                pnl=sig.current_value,
                            )

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

        # --- Risk manager: sector exposure check on rebalance day ---
        if rebalance_day and self._risk_manager is not None:
            remaining = current_temp.get_stock_list()
            if remaining:
                from src.data.sector_map import get_sector_map
                from src.guardrails.position_risk import PositionInfo

                sample_inst = remaining[0]
                market = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
                try:
                    sector_map = get_sector_map(market)
                except Exception:
                    sector_map = {}

                total_value = float(current_temp.get_cash()) + sum(
                    float(current_temp.get_stock_value(c)) for c in remaining
                )
                risk_positions: dict[str, PositionInfo] = {}
                for code in remaining:
                    stock_val = float(current_temp.get_stock_value(code))
                    risk_positions[code] = PositionInfo(
                        instrument=code,
                        weight=stock_val / total_value if total_value > 0 else 0.0,
                        entry_price=self._estimate_entry_price(code, current_temp),
                        current_price=stock_val / max(1, float(current_temp.get_stock_amount(code))),
                        peak_price=stock_val / max(1, float(current_temp.get_stock_amount(code))),
                        sector=sector_map.get(code, "Unknown"),
                    )

                sector_signals = self._risk_manager.check_sector_exposure(risk_positions)
                for sig in sector_signals:
                    # Sell the smallest position in the overweight sector
                    sector_name = sig.reason.split("'")[1] if "'" in sig.reason else ""
                    sector_positions = [
                        (c, float(current_temp.get_stock_value(c)))
                        for c in remaining
                        if (sector_map.get(c, "Unknown") == sector_name
                            and c not in sell_candidates)
                    ]
                    sector_positions.sort(key=lambda x: x[1])
                    for inst, _ in sector_positions[:1]:
                        entry_date = self.entry_dates.get(inst)
                        if can_sell(entry_date, current_date, self.min_hold_days):
                            sell_candidates.add(inst)
                            logger.info(
                                "Risk: sector limit sell",
                                instrument=inst,
                                sector=sector_name,
                            )

        if rebalance_day:
            current_stock_list = current_temp.get_stock_list()
            desired_topk = list(pred_score.index[: self.topk])
            available_slots = max(0, self.topk - len(current_stock_list))
            buy_list = [code for code in desired_topk if code not in current_stock_list]
            # Score-based buy rule: only buy if score > threshold
            if self.buy_score_threshold is not None:
                buy_list = [c for c in buy_list if pred_score.get(c, 0) > self.buy_score_threshold]
            buy_list = buy_list[:available_slots]

            # Compute per-code target value (equal-weight or vol-adjusted)
            value_map: dict[str, float] = {}
            if buy_list:
                if self._risk_manager is not None:
                    # Vol-adjusted sizing
                    try:
                        vol_fields = [f"Std($close / Ref($close, 1) - 1, 20)"]
                        vol_df = D.features(
                            buy_list, vol_fields,
                            start_time=trade_start_time, end_time=trade_end_time,
                        )
                        if not vol_df.empty:
                            vol_df.columns = ["vol_20d"]
                            volatilities = vol_df.groupby(level="instrument")["vol_20d"].last()
                            scores = pred_score.reindex(buy_list).dropna()
                            weights = self._risk_manager.compute_vol_adjusted_weights(
                                buy_list, scores, volatilities,
                            )
                            alloc = cash * self.risk_degree
                            for code in buy_list:
                                w = float(weights.get(code, 0.0))
                                value_map[code] = alloc * w if w > 0 else alloc / len(buy_list)
                            logger.info("Vol-adjusted sizing applied", n=len(buy_list))
                        else:
                            raise ValueError("Empty vol data")
                    except Exception as exc:
                        logger.warning(
                            "Vol-adjusted sizing failed; falling back to equal-weight",
                            error=str(exc),
                        )
                        value_map = {}

                # Fallback: equal-weight
                if not value_map:
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

                # [GUARDRAIL 2/2] - Hardcoded Position constraints (Max 15% allowed per tick)
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
