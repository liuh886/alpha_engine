from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import BaseSignalStrategy
from qlib.data import D

from src.common.logging import get_logger
from src.strategies.weekly_quant_rating_rules import (
    is_last_trading_day_of_week,
    select_target,
    select_top_fraction,
    update_streaks,
)

logger = get_logger(__name__)


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
        use_risk_manager: bool = False,
        risk_config: dict | None = None,
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
                logger.debug(
                    "Failed to resolve next trade date", trade_step=trade_step, exc_info=True
                )
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
                logger.debug("Failed to normalize multi-index signal", exc_info=True)
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
                logger.debug("Failed to fetch eligibility features", instrument=inst, exc_info=True)
                result[inst] = False
                continue
            if df is None or df.empty:
                result[inst] = False
                continue

            df.columns = ["close", "money_mean", "volume_min"]
            try:
                row = df.xs(inst, level="instrument").iloc[-1]
            except Exception:
                logger.debug(
                    "Failed to extract row from features dataframe", instrument=inst, exc_info=True
                )
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

        # --- Risk manager: stop-loss and trailing stop checks (every step) ---
        if self._risk_manager is not None:
            current_stock_list = self.trade_position.get_stock_list()
            if current_stock_list:
                from src.data.sector_map import get_sector_map
                from src.guardrails.position_risk import PositionInfo

                sample_inst = current_stock_list[0] if current_stock_list else ""
                market = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
                try:
                    sector_map = get_sector_map(market)
                except Exception:
                    sector_map = {}

                total_value = float(self.trade_position.get_cash()) + sum(
                    float(
                        float(self.trade_position.get_stock_price(c))
                        * float(self.trade_position.get_stock_amount(c))
                    )
                    for c in current_stock_list
                )

                # Fetch current prices for risk evaluation
                price_fields = ["$close"]
                try:
                    price_df = D.features(
                        current_stock_list,
                        price_fields,
                        start_time=pred_start_time,
                        end_time=pred_start_time,
                    )
                    if not price_df.empty:
                        price_df.columns = ["close"]
                        cur_prices = price_df.groupby(level="instrument")["close"].last()
                    else:
                        cur_prices = pd.Series(dtype=float)
                except Exception:
                    cur_prices = pd.Series(dtype=float)

                risk_positions: dict[str, PositionInfo] = {}
                for code in current_stock_list:
                    stock_val = float(
                        float(self.trade_position.get_stock_price(code))
                        * float(self.trade_position.get_stock_amount(code))
                    )
                    cur_price = float(cur_prices.get(code, 0.0))
                    risk_positions[code] = PositionInfo(
                        instrument=code,
                        weight=stock_val / total_value if total_value > 0 else 0.0,
                        entry_price=stock_val
                        / max(1, float(self.trade_position.get_stock_amount(code))),
                        current_price=cur_price,
                        peak_price=cur_price,
                        sector=sector_map.get(code, "Unknown"),
                    )

                stop_signals = self._risk_manager.check_stop_loss(risk_positions)
                for sig in stop_signals:
                    inst = sig.instrument
                    target_set.discard(inst)
                    # Add sell order if stock is in portfolio but not in target
                    if inst in [c for c in self.trade_position.get_stock_list()]:
                        if self.trade_exchange.is_stock_tradable(
                            stock_id=inst,
                            start_time=trade_start_time,
                            end_time=trade_end_time,
                            direction=OrderDir.SELL,
                        ):
                            amt = float(self.trade_position.get_stock_amount(inst))
                            if amt > 0:
                                sell_order = Order(
                                    stock_id=inst,
                                    amount=amt,
                                    start_time=trade_start_time,
                                    end_time=trade_end_time,
                                    direction=OrderDir.SELL,
                                )
                                if self.trade_exchange.check_order(sell_order):
                                    orders.append(sell_order)
                                    logger.info(
                                        "Risk: stop-loss sell",
                                        instrument=inst,
                                        pnl=sig.current_value,
                                    )

                trailing_signals = self._risk_manager.check_trailing_stop(risk_positions)
                for sig in trailing_signals:
                    inst = sig.instrument
                    target_set.discard(inst)
                    if inst in [c for c in self.trade_position.get_stock_list()]:
                        if self.trade_exchange.is_stock_tradable(
                            stock_id=inst,
                            start_time=trade_start_time,
                            end_time=trade_end_time,
                            direction=OrderDir.SELL,
                        ):
                            amt = float(self.trade_position.get_stock_amount(inst))
                            if amt > 0:
                                sell_order = Order(
                                    stock_id=inst,
                                    amount=amt,
                                    start_time=trade_start_time,
                                    end_time=trade_end_time,
                                    direction=OrderDir.SELL,
                                )
                                if self.trade_exchange.check_order(sell_order):
                                    orders.append(sell_order)
                                    logger.info(
                                        "Risk: trailing stop sell",
                                        instrument=inst,
                                        drawdown=sig.current_value,
                                    )

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

        # Compute per-code target value (equal-weight or vol-adjusted)
        value_map: dict[str, float] = {}
        if target:
            if self._risk_manager is not None:
                try:
                    vol_fields = ["Std($close / Ref($close, 1) - 1, 20)"]
                    vol_df = D.features(
                        target,
                        vol_fields,
                        start_time=pred_start_time,
                        end_time=pred_start_time,
                    )
                    if not vol_df.empty:
                        vol_df.columns = ["vol_20d"]
                        volatilities = vol_df.groupby(level="instrument")["vol_20d"].last()
                        scores = pred_score.reindex(target).dropna()
                        weights = self._risk_manager.compute_vol_adjusted_weights(
                            target,
                            scores,
                            volatilities,
                        )
                        alloc = cash * float(self.risk_degree)
                        for code in target:
                            w = float(weights.get(code, 0.0))
                            value_map[code] = alloc * w if w > 0 else alloc / len(target)
                        logger.info("Vol-adjusted sizing applied", n=len(target))
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
                eq_value = cash * float(self.risk_degree) / len(target)
                value_map = {code: eq_value for code in target}

        # Risk manager: position limits — cap buy value for existing overweight positions
        position_limit_capped: set[str] = set()
        if self._risk_manager is not None:
            existing_list = self.trade_position.get_stock_list()
            if existing_list:
                from src.data.sector_map import get_sector_map
                from src.guardrails.position_risk import PositionInfo as _PI

                sample_inst = existing_list[0]
                market = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
                try:
                    sector_map = get_sector_map(market)
                except Exception:
                    sector_map = {}
                total_value = float(self.trade_position.get_cash()) + sum(
                    float(
                        float(self.trade_position.get_stock_price(c))
                        * float(self.trade_position.get_stock_amount(c))
                    )
                    for c in existing_list
                )
                existing_positions: dict[str, _PI] = {}
                for code in existing_list:
                    stock_val = float(
                        float(self.trade_position.get_stock_price(code))
                        * float(self.trade_position.get_stock_amount(code))
                    )
                    existing_positions[code] = _PI(
                        instrument=code,
                        weight=stock_val / total_value if total_value > 0 else 0.0,
                        entry_price=stock_val
                        / max(1, float(self.trade_position.get_stock_amount(code))),
                        current_price=stock_val
                        / max(1, float(self.trade_position.get_stock_amount(code))),
                        peak_price=stock_val
                        / max(1, float(self.trade_position.get_stock_amount(code))),
                        sector=sector_map.get(code, "Unknown"),
                    )
                pos_limit_signals = self._risk_manager.check_position_limits(existing_positions)
                for sig in pos_limit_signals:
                    position_limit_capped.add(sig.instrument)
                    logger.info(
                        "Risk: position limit cap",
                        instrument=sig.instrument,
                        weight=sig.current_value,
                        limit=sig.threshold,
                    )

        for code in target:
            if not self.trade_exchange.is_stock_tradable(
                stock_id=code, start_time=trade_start_time, end_time=trade_end_time
            ):
                continue

            # Risk manager: reduce target for positions already at limit
            target_value = value_map.get(code, 0)
            if code in position_limit_capped:
                target_value = min(target_value, cash * 0.10)
                logger.info(
                    "Risk: reduced buy for capped position",
                    instrument=code,
                    target_value=target_value,
                )

            price = self.trade_exchange.get_deal_price(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.BUY,
            )
            if price is None or np.isnan(price) or price <= 0:
                continue
            amount = target_value / float(price)
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
