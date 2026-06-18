"""Dual-Layer Strategy — combines stock-level decision engine with portfolio management.

Layer 1: StockDecisionEngine evaluates each stock independently → BUY / HOLD / SELL
Layer 2: Portfolio strategy uses those signals to construct and manage positions

This strategy extends BiweeklyTrendStrategy's logic by adding a decision engine
gate: only stocks where the engine returns BUY are eligible for purchase, and
stocks where the engine returns SELL are sold regardless of rank.

The decision engine provides human-readable reasoning for each trade, making
the strategy's actions explainable at the individual stock level.
"""

from __future__ import annotations

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


class DualLayerStrategy(BaseSignalStrategy):
    """Dual-layer strategy: stock-level decision engine + portfolio management.

    Compatible with all BiweeklyTrendStrategy parameters. Adds:
    - use_decision_engine: bool = True  — enable stock-level decision gating
    - decision_config: dict | None      — config overrides for StockDecisionEngine

    When enabled, the decision engine gates both buy and sell decisions:
    - BUY: only if engine returns BUY signal
    - SELL: if engine returns SELL signal (in addition to existing rules)
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
        # Dual-layer specific
        use_decision_engine: bool = True,
        decision_config: dict | None = None,
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
            logger.info("Risk manager enabled", config=cfg)

        # Decision engine
        self.use_decision_engine = use_decision_engine
        self._decision_engine = None
        if use_decision_engine:
            from src.strategies.stock_decision_engine import StockDecisionEngine

            self._decision_engine = StockDecisionEngine(config=decision_config)
            logger.info("Decision engine enabled", config=decision_config)

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
        try:
            cost = float(position.get_stock_cost(code))
            amount = float(position.get_stock_amount(code))
            if amount > 0 and cost > 0:
                return cost / amount
        except Exception:
            pass
        return 0.0

    def _detect_market(self, instruments: list[str]) -> str:
        if not instruments:
            return "us"
        return "cn" if instruments[0].endswith((".SH", ".SZ")) else "us"

    def _run_decision_engine(
        self,
        instruments: list[str],
        pred_score: pd.Series,
        rank_map: dict[str, int],
        market: str,
        held_positions: dict[str, dict] | None = None,
    ) -> dict[str, str]:
        """Run decision engine for a list of instruments.

        Returns {instrument: signal} where signal is "BUY", "HOLD", or "SELL".
        """
        if self._decision_engine is None:
            return {}

        results: dict[str, str] = {}
        for inst in instruments:
            try:
                decision = self._decision_engine.evaluate(
                    symbol=inst,
                    pred_score=pred_score,
                    rank_map=rank_map,
                    market=market,
                    held_positions=held_positions,
                    include_factors=False,  # skip factor analysis in backtest for speed
                )
                results[inst] = decision.signal
                if decision.signal != "HOLD":
                    logger.debug(
                        "decision_engine",
                        instrument=inst,
                        signal=decision.signal,
                        confidence=round(decision.confidence, 3),
                        score=round(decision.score, 4) if decision.score == decision.score else None,
                        rank=decision.rank,
                    )
            except Exception as exc:
                logger.debug("decision_engine_error", instrument=inst, error=str(exc))
                results[inst] = "HOLD"  # lenient fallback

        return results

    def generate_trade_decision(self, execute_result=None):
        """Generate trade decisions using dual-layer logic.

        Layer 1 (every step): Run decision engine on held stocks → SELL if engine says SELL
        Layer 2 (rebalance day): Run decision engine on candidates → BUY only if engine says BUY
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

        market = self._detect_market(current_stock_list or list(pred_score.index[:5]))

        # Build held positions dict for risk/decision checks
        held_positions: dict[str, dict] = {}
        if current_stock_list:
            total_value = float(current_temp.get_cash()) + sum(
                float(current_temp.get_stock_value(code))
                for code in current_stock_list
            )
            for code in current_stock_list:
                stock_val = float(current_temp.get_stock_value(code))
                held_positions[code] = {
                    "weight": stock_val / total_value if total_value > 0 else 0.0,
                    "entry_price": self._estimate_entry_price(code, current_temp),
                    "current_price": stock_val / max(1, float(current_temp.get_stock_amount(code))),
                    "peak_price": stock_val / max(1, float(current_temp.get_stock_amount(code))),
                }

        # --- Layer 1: Sell checks (every step) ---
        sell_candidates: set[str] = set()

        # 1a. Existing MA cross-under + min hold days logic
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

        # 1b. Risk manager stop-loss / trailing stop
        if self._risk_manager is not None and current_stock_list:
            from src.data.sector_map import get_sector_map
            from src.guardrails.position_risk import PositionInfo

            sample_inst = current_stock_list[0]
            mkt = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
            try:
                sector_map = get_sector_map(mkt)
            except Exception:
                sector_map = {}

            risk_positions: dict[str, PositionInfo] = {}
            for code in current_stock_list:
                hp = held_positions.get(code, {})
                risk_positions[code] = PositionInfo(
                    instrument=code,
                    weight=hp.get("weight", 0.0),
                    entry_price=hp.get("entry_price", 0.0),
                    current_price=hp.get("current_price", 0.0),
                    peak_price=hp.get("peak_price", 0.0),
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

        # 1c. Decision engine SELL signal
        if self._decision_engine is not None and current_stock_list:
            engine_signals = self._run_decision_engine(
                current_stock_list, pred_score, rank_map, market, held_positions
            )
            for inst, signal in engine_signals.items():
                if signal == "SELL" and inst not in sell_candidates:
                    entry_date = self.entry_dates.get(inst)
                    if can_sell(entry_date, current_date, self.min_hold_days):
                        sell_candidates.add(inst)
                        logger.info("Decision engine: SELL", instrument=inst)

        # 1d. Rebalance-day rank/score sell rules
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

        # --- Execute sells ---
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

        # --- Layer 2: Buy checks (rebalance day only) ---
        if rebalance_day:
            current_stock_list = current_temp.get_stock_list()
            desired_topk = list(pred_score.index[: self.topk])
            available_slots = max(0, self.topk - len(current_stock_list))
            buy_list = [code for code in desired_topk if code not in current_stock_list]

            # Score threshold filter
            if self.buy_score_threshold is not None:
                buy_list = [c for c in buy_list if pred_score.get(c, 0) > self.buy_score_threshold]

            # Decision engine BUY gate
            if self._decision_engine is not None and buy_list:
                engine_signals = self._run_decision_engine(
                    buy_list, pred_score, rank_map, market
                )
                # Only buy stocks where engine returns BUY
                buy_list = [c for c in buy_list if engine_signals.get(c) == "BUY"]
                for c in buy_list:
                    logger.info("Decision engine: BUY candidate", instrument=c)

            buy_list = buy_list[:available_slots]

            # Compute per-code target value (equal-weight or vol-adjusted)
            value_map: dict[str, float] = {}
            if buy_list:
                if self._risk_manager is not None:
                    try:
                        vol_fields = ["Std($close / Ref($close, 1) - 1, 20)"]
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
                        else:
                            raise ValueError("Empty vol data")
                    except Exception as exc:
                        logger.warning("Vol-adjusted sizing failed; falling back", error=str(exc))
                        value_map = {}

                if not value_map:
                    eq_value = cash * self.risk_degree / len(buy_list)
                    value_map = {code: eq_value for code in buy_list}

            # Risk manager: position limits
            position_limit_capped: set[str] = set()
            if self._risk_manager is not None and current_stock_list:
                from src.data.sector_map import get_sector_map
                from src.guardrails.position_risk import PositionInfo as _PI

                sample_inst = current_stock_list[0]
                mkt = "cn" if sample_inst.endswith((".SH", ".SZ")) else "us"
                try:
                    sector_map = get_sector_map(mkt)
                except Exception:
                    sector_map = {}
                total_value = float(current_temp.get_cash()) + sum(
                    float(current_temp.get_stock_value(c)) for c in current_stock_list
                )
                existing_positions: dict[str, _PI] = {}
                for code in current_stock_list:
                    stock_val = float(current_temp.get_stock_value(code))
                    existing_positions[code] = _PI(
                        instrument=code,
                        weight=stock_val / total_value if total_value > 0 else 0.0,
                        entry_price=self._estimate_entry_price(code, current_temp),
                        current_price=stock_val / max(1, float(current_temp.get_stock_amount(code))),
                        peak_price=stock_val / max(1, float(current_temp.get_stock_amount(code))),
                        sector=sector_map.get(code, "Unknown"),
                    )
                pos_limit_signals = self._risk_manager.check_position_limits(existing_positions)
                for sig in pos_limit_signals:
                    position_limit_capped.add(sig.instrument)

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

                if code in position_limit_capped:
                    target_value = min(target_value, max_allowed_buy_val * 0.5)

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
