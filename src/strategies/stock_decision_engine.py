"""Stock Decision Engine — generates BUY / HOLD / SELL signals for individual stocks
with human-readable reasoning, factor exposure snapshots, and guardrail status.

This engine is designed to be used standalone (via API) or embedded inside
a portfolio strategy (DualLayerStrategy).

Decision priority (highest first):
1. Guardrail hard blocks (liquidity, volatility regime, extension)
2. Risk signals (stop-loss, trailing stop)
3. Technical signals (MA cross-under)
4. Model signal (score rank, score threshold)
5. Factor analysis (extreme values, consistency) → affects confidence only
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
import structlog

from src.guardrails.rules import (
    check_extension,
    check_liquidity,
    check_volatility_regime,
)

logger = structlog.get_logger()

__all__ = [
    "StockDecision",
    "FactorSnapshot",
    "StockDecisionEngine",
    "DEFAULT_DECISION_CONFIG",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DECISION_CONFIG: dict[str, Any] = {
    # Guardrail thresholds
    "extension_threshold": 0.20,
    "vol_threshold": 2.0,
    "min_liquidity": 1_000_000,
    # MA signals
    "sell_ma_window": 60,
    # Model signal thresholds
    "buy_rank_topk": 20,       # rank < this → BUY candidate
    "sell_rank_threshold": 50,  # rank >= this → SELL candidate
    "buy_score_threshold": 0.0,
    "sell_score_threshold": -0.1,
    # Factor extremes
    "factor_z_extreme": 2.0,    # |z-score| > this → flagged
    # Confidence weights (must sum to 1.0)
    "weight_model": 0.50,
    "weight_guardrail": 0.20,
    "weight_factor": 0.15,
    "weight_trend": 0.15,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FactorSnapshot:
    """A single factor's value, z-score, and percentile for a stock."""

    name: str
    expression: str
    value: float | None = None
    z_score: float | None = None
    percentile: float | None = None
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expression": self.expression,
            "value": self.value,
            "z_score": self.z_score,
            "percentile": self.percentile,
            "category": self.category,
        }


@dataclass
class PriceTargets:
    """Actionable price levels for a stock."""

    current_price: float | None = None
    buy_range_low: float | None = None   # 建议买入区间下限
    buy_range_high: float | None = None  # 建议买入区间上限
    stop_loss_price: float | None = None # 止损价
    target_price: float | None = None    # 目标价
    atr_20: float | None = None          # 20日 ATR（波动率参考）
    support: float | None = None         # 近期支撑位
    resistance: float | None = None      # 近期阻力位

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_price": _round_price(self.current_price),
            "buy_range_low": _round_price(self.buy_range_low),
            "buy_range_high": _round_price(self.buy_range_high),
            "stop_loss_price": _round_price(self.stop_loss_price),
            "target_price": _round_price(self.target_price),
            "atr_20": _round_price(self.atr_20),
            "support": _round_price(self.support),
            "resistance": _round_price(self.resistance),
        }


def _round_price(v: float | None) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(v, 2)


@dataclass
class StrategyRecommendation:
    """Recommended strategy for a stock with reasoning."""

    name: str           # e.g. "biweekly_trend", "dual_layer", "weekly_quant_rating"
    display_name: str   # human-readable name
    reason: str         # why this strategy fits
    confidence: float   # 0-1 how well the stock fits this strategy

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class StockDecision:
    """Complete decision output for a single stock."""

    symbol: str
    signal: Literal["BUY", "HOLD", "SELL"]
    confidence: float  # 0-1
    score: float  # model prediction score
    rank: int | None  # rank in the full universe (0-based)
    reasons: list[str] = field(default_factory=list)
    factor_snapshot: dict[str, Any] = field(default_factory=dict)
    guardrail_status: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    timestamp: str = ""
    # P1-1: Strategy recommendation
    recommended_strategy: StrategyRecommendation | None = None
    # P1-2: Price targets
    price_targets: PriceTargets | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "symbol": self.symbol,
            "signal": self.signal,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 4) if not math.isnan(self.score) else None,
            "rank": self.rank,
            "reasons": self.reasons,
            "factor_snapshot": {
                k: v.to_dict() if isinstance(v, FactorSnapshot) else v
                for k, v in self.factor_snapshot.items()
            },
            "guardrail_status": self.guardrail_status,
            "risk_flags": self.risk_flags,
            "timestamp": self.timestamp,
        }
        if self.recommended_strategy is not None:
            result["recommended_strategy"] = self.recommended_strategy.to_dict()
        if self.price_targets is not None:
            result["price_targets"] = self.price_targets.to_dict()
        return result


def _round_price(val: float | None) -> float | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return round(val, 2)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class StockDecisionEngine:
    """Evaluates a single stock and produces a BUY / HOLD / SELL decision
    with human-readable reasoning.

    Usage::

        engine = StockDecisionEngine()
        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=pred_series,   # pd.Series indexed by instrument
            rank_map={"AAPL": 2, ...},
            market="us",
        )
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = {**DEFAULT_DECISION_CONFIG, **(config or {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        pred_score: pd.Series,
        rank_map: dict[str, int],
        market: str = "us",
        *,
        held_positions: dict[str, Any] | None = None,
        trade_date: str | None = None,
        include_factors: bool = True,
    ) -> StockDecision:
        """Generate a decision for *symbol*.

        Parameters
        ----------
        symbol : str
            Clean instrument symbol (e.g. ``"AAPL"`` or ``"600519"``).
        pred_score : pd.Series
            Cross-sectional model scores indexed by instrument.
        rank_map : dict
            Mapping ``{instrument: rank_index}`` (0 = best).
        market : str
            ``"us"`` or ``"cn"``.
        held_positions : dict, optional
            Current portfolio positions for risk checks.
        trade_date : str, optional
            ISO date string for the decision timestamp.
        include_factors : bool
            Whether to compute factor snapshots (slower).

        Returns
        -------
        StockDecision
        """
        symbol = str(symbol).strip().upper()
        cfg = self.config

        # --- 0. Basic score and rank ---
        score = float(pred_score.get(symbol, float("nan")))
        rank = rank_map.get(symbol)
        total_stocks = len(rank_map)
        reasons: list[str] = []
        risk_flags: list[str] = []

        # --- 1. Guardrail checks ---
        guardrail_status = self._check_guardrails(symbol, market)
        guardrail_passed = guardrail_status.get("overall_passed", True)

        for name, detail in guardrail_status.items():
            if name == "overall_passed":
                continue
            if isinstance(detail, dict) and not detail.get("passed", True):
                reasons.append(f"⚠ 护栏拦截 — {name}: {detail.get('reason', 'failed')}")

        # --- 2. Risk checks (for held positions) ---
        if held_positions and symbol in held_positions:
            risk_signals = self._check_risk(symbol, held_positions)
            for sig in risk_signals:
                risk_flags.append(sig["signal_type"])
                reasons.append(f"🔴 风险触发 — {sig['reason']}")

        # --- 3. Technical signals ---
        ma_signal = self._check_ma_signal(symbol, market)
        if ma_signal:
            reasons.append(ma_signal)

        # --- 4. Model signal analysis ---
        model_reason = self._analyze_model_signal(score, rank, total_stocks)
        if model_reason:
            reasons.append(model_reason)

        # --- 5. Factor analysis ---
        factor_snapshot: dict[str, FactorSnapshot] = {}
        factor_reasons: list[str] = []
        if include_factors:
            factor_snapshot, factor_reasons = self._analyze_factors(symbol, market)
            reasons.extend(factor_reasons)

        # --- 6. Determine signal ---
        signal = self._determine_signal(
            score=score,
            rank=rank,
            total_stocks=total_stocks,
            guardrail_passed=guardrail_passed,
            risk_flags=risk_flags,
            ma_signal=ma_signal,
        )

        # --- 7. Compute confidence ---
        confidence = self._compute_confidence(
            score=score,
            rank=rank,
            total_stocks=total_stocks,
            guardrail_passed=guardrail_passed,
            factor_snapshot=factor_snapshot,
            ma_signal=ma_signal,
        )

        # --- 8. Positive reasons for BUY ---
        if signal == "BUY":
            positive = self._generate_positive_reasons(score, rank, total_stocks, guardrail_status, factor_snapshot)
            reasons = positive + reasons  # positive first, then warnings

        # --- 9. Strategy recommendation (P1-1) ---
        recommended_strategy = self._recommend_strategy(
            symbol=symbol,
            market=market,
            signal=signal,
            score=score,
            rank=rank,
            total_stocks=total_stocks,
            factor_snapshot=factor_snapshot,
            guardrail_status=guardrail_status,
        )
        if recommended_strategy is not None:
            reasons.append(
                f"📋 推荐策略: {recommended_strategy.display_name} — {recommended_strategy.reason}"
            )

        # --- 10. Price targets (P1-2) ---
        price_targets = self._compute_price_targets(symbol, market, signal)
        if price_targets is not None and signal == "BUY":
            pt = price_targets
            if pt.buy_range_low is not None and pt.buy_range_high is not None:
                reasons.append(
                    f"💰 建议买入区间: {pt.buy_range_low:.2f} - {pt.buy_range_high:.2f}"
                )
            if pt.stop_loss_price is not None:
                reasons.append(f"🛑 止损参考价: {pt.stop_loss_price:.2f}")
            if pt.target_price is not None:
                reasons.append(f"🎯 目标价: {pt.target_price:.2f}")

        decision = StockDecision(
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            score=score,
            rank=rank,
            reasons=reasons,
            factor_snapshot={k: v.to_dict() for k, v in factor_snapshot.items()},
            guardrail_status=guardrail_status,
            risk_flags=risk_flags,
            timestamp=trade_date or pd.Timestamp.now().strftime("%Y-%m-%d"),
            recommended_strategy=recommended_strategy,
            price_targets=price_targets,
        )

        logger.info(
            "stock_decision",
            symbol=symbol,
            signal=signal,
            confidence=round(confidence, 3),
            score=round(score, 4) if not math.isnan(score) else None,
            rank=rank,
            n_reasons=len(reasons),
        )
        return decision

    # ------------------------------------------------------------------
    # Universe loading
    # ------------------------------------------------------------------

    def _load_universe_tickers(self, market: str) -> list[str]:
        """Load watchlist tickers for the given market."""
        try:
            from pathlib import Path
            import yaml

            watchlist_path = Path(__file__).resolve().parents[2] / "configs" / "watchlist.yaml"
            if not watchlist_path.exists():
                return []

            with watchlist_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                return []

            market_data = data.get(market.lower(), data.get("us", []))
            if isinstance(market_data, dict):
                tickers = market_data.get("tickers", [])
            elif isinstance(market_data, list):
                tickers = market_data
            else:
                tickers = []

            return [str(t) for t in tickers if isinstance(t, str)]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Guardrail checks
    # ------------------------------------------------------------------

    def _check_guardrails(self, symbol: str, market: str) -> dict[str, Any]:
        """Run guardrail rules using Qlib data."""
        cfg = self.config
        result: dict[str, Any] = {"overall_passed": True}

        try:
            from qlib.data import D
            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            fields = [
                "$close",
                f"Mean($close, 20)",
                f"Std($close/Ref($close,1)-1, 20)",
                f"Std($close/Ref($close,1)-1, 252)",
                "$amount",
            ]
            df = D.features(
                [symbol],
                fields,
                start_time=pd.Timestamp.now() - pd.Timedelta(days=400),
            )

            if df.empty:
                result["overall_passed"] = False
                result["data"] = {"passed": False, "reason": "No data available"}
                return result

            last = df.iloc[-1]
            close = float(last.iloc[0]) if pd.notna(last.iloc[0]) else 0.0
            ma20 = float(last.iloc[1]) if pd.notna(last.iloc[1]) else 0.0
            vol20 = float(last.iloc[2]) if pd.notna(last.iloc[2]) else 0.0
            vol252 = float(last.iloc[3]) if pd.notna(last.iloc[3]) else 0.0
            amount = float(last.iloc[4]) if pd.notna(last.iloc[4]) else 0.0

            ext = check_extension(close, ma20, cfg["extension_threshold"])
            result["extension"] = ext

            vol = check_volatility_regime(vol20, vol252, cfg["vol_threshold"])
            result["volatility_regime"] = vol

            liq = check_liquidity(amount, cfg["min_liquidity"])
            result["liquidity"] = liq

            result["overall_passed"] = all(
                r["passed"] for r in [ext, vol, liq]
            )

        except Exception as exc:
            logger.warning("guardrail_check_failed", symbol=symbol, error=str(exc))
            result["overall_passed"] = True  # lenient fallback
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Risk checks
    # ------------------------------------------------------------------

    def _check_risk(
        self, symbol: str, held_positions: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Check stop-loss and trailing stop for a held position."""
        from src.guardrails.position_risk import (
            PositionInfo,
            PositionRiskConfig,
            PositionRiskManager,
        )

        pos = held_positions.get(symbol)
        if pos is None:
            return []

        # Build PositionInfo from held position data
        if isinstance(pos, dict):
            pi = PositionInfo(
                instrument=symbol,
                weight=pos.get("weight", 0.0),
                entry_price=pos.get("entry_price", 0.0),
                current_price=pos.get("current_price", 0.0),
                peak_price=pos.get("peak_price", 0.0),
                sector=pos.get("sector", ""),
            )
        else:
            pi = pos

        manager = PositionRiskManager(PositionRiskConfig())
        signals: list[dict[str, Any]] = []

        for sig in manager.check_stop_loss({symbol: pi}):
            signals.append(sig.to_dict())
        for sig in manager.check_trailing_stop({symbol: pi}):
            signals.append(sig.to_dict())

        return signals

    # ------------------------------------------------------------------
    # Technical signals
    # ------------------------------------------------------------------

    def _check_ma_signal(self, symbol: str, market: str) -> str | None:
        """Check MA cross-under signal."""
        cfg = self.config
        ma_window = cfg["sell_ma_window"]

        try:
            from qlib.data import D
            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            df = D.features(
                [symbol],
                ["$close", f"Mean($close, {ma_window})"],
                start_time=pd.Timestamp.now() - pd.Timedelta(days=400),
            )
            if df.empty:
                return None

            last = df.iloc[-1]
            close = float(last.iloc[0]) if pd.notna(last.iloc[0]) else 0.0
            ma = float(last.iloc[1]) if pd.notna(last.iloc[1]) else 0.0

            if close > 0 and ma > 0:
                deviation = (close - ma) / ma
                if close < ma:
                    return f"📉 MA{ma_window} 死叉 — 价格 {close:.2f} < MA{ma_window} {ma:.2f}（偏离 {deviation:.1%}）"
                elif deviation > 0.10:
                    return f"📈 MA{ma_window} 趋势向上 — 价格偏离 +{deviation:.1%}"

        except Exception as exc:
            logger.debug("ma_check_failed", symbol=symbol, error=str(exc))

        return None

    # ------------------------------------------------------------------
    # Model signal analysis
    # ------------------------------------------------------------------

    def _analyze_model_signal(
        self, score: float, rank: int | None, total_stocks: int
    ) -> str | None:
        """Generate a human-readable model signal reason."""
        if math.isnan(score):
            return "⚠ 无模型预测数据"

        parts: list[str] = []
        parts.append(f"模型分数 {score:+.4f}")

        if rank is not None and total_stocks > 1:
            # Clamp rank to valid range
            effective_rank = min(rank, total_stocks - 1)
            pct = (effective_rank + 1) / total_stocks * 100
            if pct <= 10:
                parts.append(f"排名 {effective_rank + 1}/{total_stocks}（Top {pct:.1f}%）⭐")
            elif pct <= 25:
                parts.append(f"排名 {effective_rank + 1}/{total_stocks}（Top {pct:.1f}%）")
            elif pct >= 90:
                parts.append(f"排名 {effective_rank + 1}/{total_stocks}（Bottom {100 - pct:.1f}%）⚠")
            else:
                parts.append(f"排名 {effective_rank + 1}/{total_stocks}（{pct:.1f}%）")

        return " — ".join(parts)

    # ------------------------------------------------------------------
    # Factor analysis
    # ------------------------------------------------------------------

    def _analyze_factors(
        self, symbol: str, market: str
    ) -> tuple[dict[str, FactorSnapshot], list[str]]:
        """Compute factor values for the stock using the Active factor registry."""
        snapshots: dict[str, FactorSnapshot] = {}
        reasons: list[str] = []
        cfg = self.config
        z_extreme = cfg["factor_z_extreme"]

        try:
            from src.research.factor_registry import FactorRegistry, STAGE_ACTIVE

            registry = FactorRegistry()
            active_factors = registry.list_factors(stage=STAGE_ACTIVE)

            if not active_factors:
                return snapshots, reasons

            # Limit to top 20 factors to avoid performance issues
            factors_to_eval = active_factors[:20]

            from qlib.data import D
            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            expressions = [f["expression"] for f in factors_to_eval]
            names = [f["name"] for f in factors_to_eval]
            categories = [f["category"] for f in factors_to_eval]

            # Fetch factor values for this stock
            stock_df = D.features(
                [symbol],
                expressions,
                start_time=pd.Timestamp.now() - pd.Timedelta(days=60),
            )

            # Load universe tickers for z-score calculation
            universe_tickers = self._load_universe_tickers(market)
            # Remove the target stock from universe to avoid double-counting
            universe_tickers = [t for t in universe_tickers if t != symbol][:50]  # limit for performance

            universe_df = pd.DataFrame()
            if universe_tickers:
                try:
                    universe_df = D.features(
                        universe_tickers,
                        expressions,
                        start_time=pd.Timestamp.now() - pd.Timedelta(days=60),
                    )
                except Exception as exc:
                    logger.debug("universe_fetch_failed", error=str(exc))

            if stock_df.empty:
                return snapshots, reasons

            # Latest values for this stock
            stock_latest = stock_df.iloc[-1] if not stock_df.empty else None

            for i, (name, expr, cat) in enumerate(zip(names, expressions, categories)):
                try:
                    val = float(stock_latest.iloc[i]) if stock_latest is not None and pd.notna(stock_latest.iloc[i]) else None

                    z_score = None
                    percentile = None

                    if val is not None and not universe_df.empty:
                        # Compute cross-sectional z-score from latest universe data
                        col = universe_df.iloc[:, i].dropna()
                        if len(col) > 1:
                            # Group by instrument to get latest per stock
                            latest_per_stock = col.groupby(level="instrument").last()
                            mean_val = float(latest_per_stock.mean())
                            std_val = float(latest_per_stock.std())
                            if std_val > 1e-10:
                                z_score = (val - mean_val) / std_val
                            # Percentile
                            percentile = float((latest_per_stock < val).sum() / len(latest_per_stock) * 100)

                    snapshots[name] = FactorSnapshot(
                        name=name,
                        expression=expr,
                        value=val,
                        z_score=z_score,
                        percentile=percentile,
                        category=cat,
                    )

                    # Flag extreme values
                    if z_score is not None and abs(z_score) > z_extreme:
                        direction = "高" if z_score > 0 else "低"
                        reasons.append(
                            f"⚡ 因子极端值 — {name}: z-score={z_score:+.2f}（{direction}于 {z_extreme}σ）"
                        )

                except Exception:
                    continue

            # Factor consistency check
            if snapshots:
                z_scores = [s.z_score for s in snapshots.values() if s.z_score is not None]
                if len(z_scores) >= 3:
                    positive = sum(1 for z in z_scores if z > 0.5)
                    negative = sum(1 for z in z_scores if z < -0.5)
                    if positive > len(z_scores) * 0.7:
                        reasons.append(f"✅ 因子一致性高 — {positive}/{len(z_scores)} 个因子同向看多")
                    elif negative > len(z_scores) * 0.7:
                        reasons.append(f"⚠ 因子一致性高 — {negative}/{len(z_scores)} 个因子同向看空")

        except Exception as exc:
            logger.warning("factor_analysis_failed", symbol=symbol, error=str(exc))

        return snapshots, reasons

    # ------------------------------------------------------------------
    # Signal determination
    # ------------------------------------------------------------------

    def _determine_signal(
        self,
        *,
        score: float,
        rank: int | None,
        total_stocks: int,
        guardrail_passed: bool,
        risk_flags: list[str],
        ma_signal: str | None,
    ) -> Literal["BUY", "HOLD", "SELL"]:
        """Determine the final signal based on all inputs.

        Priority:
        1. Risk flags (stop-loss, trailing stop) → SELL
        2. Guardrail failure → SELL
        3. MA cross-under → SELL
        4. Model signal: top rank + positive score → BUY
        5. Model signal: bottom rank or negative score → SELL
        6. Otherwise → HOLD
        """
        cfg = self.config

        # 1. Risk flags → SELL
        if "stop_loss" in risk_flags or "trailing_stop" in risk_flags:
            return "SELL"

        # 2. Guardrail failure → SELL
        if not guardrail_passed:
            return "SELL"

        # 3. MA cross-under → SELL
        if ma_signal and "死叉" in ma_signal:
            return "SELL"

        # 4. Model signal
        if not math.isnan(score) and rank is not None:
            # BUY: top rank + positive score
            if rank < cfg["buy_rank_topk"] and score > cfg["buy_score_threshold"]:
                return "BUY"

            # SELL: bottom rank or very negative score
            if rank >= cfg["sell_rank_threshold"]:
                return "SELL"
            if score < cfg["sell_score_threshold"]:
                return "SELL"

        # 5. Default
        return "HOLD"

    # ------------------------------------------------------------------
    # Confidence computation
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        *,
        score: float,
        rank: int | None,
        total_stocks: int,
        guardrail_passed: bool,
        factor_snapshot: dict[str, FactorSnapshot],
        ma_signal: str | None,
    ) -> float:
        """Compute a 0-1 confidence score weighted across dimensions."""
        cfg = self.config

        # Model confidence: based on score magnitude and rank
        model_conf = 0.5
        if not math.isnan(score):
            # Map score to 0-1 using sigmoid-like mapping
            model_conf = max(0.1, min(0.95, 0.5 + score))
            if rank is not None and total_stocks > 0:
                rank_pct = rank / total_stocks
                # Boost for top ranks, penalize for bottom
                model_conf *= (1.0 - rank_pct * 0.5)

        # Guardrail confidence
        guardrail_conf = 1.0 if guardrail_passed else 0.2

        # Factor confidence: based on consistency and extremes
        factor_conf = 0.5
        if factor_snapshot:
            z_scores = [s.z_score for s in factor_snapshot.values() if s.z_score is not None]
            if z_scores:
                # High consistency → high confidence
                positive = sum(1 for z in z_scores if z > 0.5)
                negative = sum(1 for z in z_scores if z < -0.5)
                consistency = max(positive, negative) / len(z_scores)
                factor_conf = 0.3 + 0.5 * consistency

        # Trend confidence
        trend_conf = 0.5
        if ma_signal:
            if "趋势向上" in ma_signal:
                trend_conf = 0.8
            elif "死叉" in ma_signal:
                trend_conf = 0.2

        # Weighted average
        confidence = (
            cfg["weight_model"] * model_conf
            + cfg["weight_guardrail"] * guardrail_conf
            + cfg["weight_factor"] * factor_conf
            + cfg["weight_trend"] * trend_conf
        )

        return max(0.1, min(0.95, confidence))

    # ------------------------------------------------------------------
    # Strategy recommendation (P1-1)
    # ------------------------------------------------------------------

    def _recommend_strategy(
        self,
        *,
        symbol: str,
        market: str,
        signal: str,
        score: float,
        rank: int | None,
        total_stocks: int,
        factor_snapshot: dict[str, FactorSnapshot],
        guardrail_status: dict[str, Any],
    ) -> StrategyRecommendation | None:
        """Recommend the best strategy for this stock based on its characteristics.

        Strategy fit logic:
        - WeeklyQuantRating: high momentum, strong consecutive signals, large-cap
        - DualLayer: moderate volatility, mixed signals, needs factor decomposition
        - BiweeklyTrend: stable large-cap, clear trend, simple signal
        """
        if signal == "HOLD":
            return None  # no recommendation for HOLD signals

        try:
            # Gather stock characteristics
            vol_regime = "normal"
            vol_detail = guardrail_status.get("volatility_regime", {})
            if isinstance(vol_detail, dict) and not vol_detail.get("passed", True):
                vol_regime = "high"

            # Factor momentum strength
            momentum_z = 0.0
            vol_z = 0.0
            for name, snap in factor_snapshot.items():
                if snap.z_score is None:
                    continue
                if "momentum" in name.lower() or "ret" in name.lower():
                    momentum_z = max(momentum_z, abs(snap.z_score))
                if "vol" in name.lower():
                    vol_z = max(vol_z, abs(snap.z_score))

            # Score strength
            score_strong = abs(score) > 0.3
            top_rank = rank is not None and total_stocks > 0 and (rank / total_stocks) < 0.1

            # Decision logic
            candidates: list[tuple[str, str, str, float]] = []  # (name, display, reason, fit_score)

            # WeeklyQuantRating: best for strong momentum + top rank
            if score_strong and top_rank and momentum_z > 1.0:
                candidates.append((
                    "weekly_quant_rating",
                    "Weekly Quant Rating",
                    f"强动量信号（z-score={momentum_z:.1f}）+ Top 排名，适合周度评级策略的连续买入逻辑",
                    min(0.95, 0.6 + momentum_z * 0.1),
                ))

            # DualLayer: best for complex factor profiles or high volatility
            if len(factor_snapshot) >= 5 or vol_regime == "high":
                vol_note = "，波动率偏高需要个股级风控" if vol_regime == "high" else "，多因子信号适合个股决策引擎分解"
                candidates.append((
                    "dual_layer",
                    "Dual Layer Strategy",
                    f"因子暴露丰富（{len(factor_snapshot)} 个 Active 因子）{vol_note}",
                    min(0.9, 0.5 + len(factor_snapshot) * 0.03),
                ))

            # BiweeklyTrend: default for stable, clear-signal stocks
            if signal == "BUY":
                candidates.append((
                    "biweekly_trend",
                    "Biweekly Trend",
                    "双周调仓策略，适合趋势明确的大盘股",
                    0.5,
                ))

            if not candidates:
                return None

            # Pick the best candidate
            candidates.sort(key=lambda x: x[3], reverse=True)
            best = candidates[0]

            return StrategyRecommendation(
                name=best[0],
                display_name=best[1],
                reason=best[2],
                confidence=best[3],
            )

        except Exception as exc:
            logger.debug("strategy_recommendation_failed", symbol=symbol, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Price targets (P1-2)
    # ------------------------------------------------------------------

    def _compute_price_targets(
        self, symbol: str, market: str, signal: str
    ) -> PriceTargets | None:
        """Compute actionable price levels using ATR, MA, and recent highs/lows.

        For BUY signals:
            buy_range = [MA20 - 0.5*ATR, MA20 + 0.5*ATR]
            stop_loss = current_price - 2*ATR
            target = current_price + 3*ATR (1.5:1 reward-risk)

        For SELL signals:
            stop_loss = current_price (exit immediately)
            target = N/A

        For HOLD:
            stop_loss = MA20 - 2*ATR (trailing reference)
        """
        try:
            from qlib.data import D
            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            # Fetch price data for ATR and support/resistance calculation
            fields = [
                "$close",                          # 0
                "$high",                           # 1
                "$low",                            # 2
                "Mean($close, 20)",                # 3: MA20
                "Mean($close, 60)",                # 4: MA60
                "Max($high, 20)",                  # 5: 20-day high (resistance)
                "Min($low, 20)",                   # 6: 20-day low (support)
            ]
            df = D.features(
                [symbol],
                fields,
                start_time=pd.Timestamp.now() - pd.Timedelta(days=60),
            )

            if df.empty:
                return None

            last = df.iloc[-1]
            close = float(last.iloc[0]) if pd.notna(last.iloc[0]) else None
            high = float(last.iloc[1]) if pd.notna(last.iloc[1]) else None
            low = float(last.iloc[2]) if pd.notna(last.iloc[2]) else None
            ma20 = float(last.iloc[3]) if pd.notna(last.iloc[3]) else None
            ma60 = float(last.iloc[4]) if pd.notna(last.iloc[4]) else None
            high_20d = float(last.iloc[5]) if pd.notna(last.iloc[5]) else None
            low_20d = float(last.iloc[6]) if pd.notna(last.iloc[6]) else None

            if close is None or close <= 0:
                return None

            # Compute ATR (Average True Range) over 20 days
            atr = self._compute_atr(df, period=20)
            if atr is None or atr <= 0:
                # Fallback: use daily range as rough ATR estimate
                if high is not None and low is not None:
                    atr = high - low
                else:
                    atr = close * 0.02  # 2% fallback

            targets = PriceTargets(current_price=close, atr_20=_round_price(atr))

            if signal == "BUY":
                # Buy range: around MA20 ± 0.5*ATR
                if ma20 is not None:
                    targets.buy_range_low = ma20 - 0.5 * atr
                    targets.buy_range_high = ma20 + 0.5 * atr
                else:
                    targets.buy_range_low = close - 0.5 * atr
                    targets.buy_range_high = close + 0.5 * atr

                # Stop loss: 2*ATR below current price
                targets.stop_loss_price = close - 2.0 * atr

                # Target: 3*ATR above (1.5:1 reward-risk ratio)
                targets.target_price = close + 3.0 * atr

            elif signal == "SELL":
                # For SELL, stop_loss is the current price (exit point)
                targets.stop_loss_price = close

            else:  # HOLD
                # Trailing reference: MA20 - 2*ATR
                if ma20 is not None:
                    targets.stop_loss_price = ma20 - 2.0 * atr

            # Support/resistance from recent range
            targets.support = low_20d
            targets.resistance = high_20d

            return targets

        except Exception as exc:
            logger.debug("price_targets_failed", symbol=symbol, error=str(exc))
            return None

    def _compute_atr(self, df: pd.DataFrame, period: int = 20) -> float | None:
        """Compute Average True Range from OHLC DataFrame.

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = SMA(TR, period)
        """
        try:
            if len(df) < period + 1:
                return None

            highs = df.iloc[:, 1].astype(float)  # $high
            lows = df.iloc[:, 2].astype(float)    # $low
            closes = df.iloc[:, 0].astype(float)  # $close

            tr_values = []
            for i in range(1, len(df)):
                h = highs.iloc[i]
                l = lows.iloc[i]
                pc = closes.iloc[i - 1]
                if any(pd.isna(v) for v in [h, l, pc]):
                    continue
                tr = max(h - l, abs(h - pc), abs(l - pc))
                tr_values.append(tr)

            if len(tr_values) < period:
                return None

            # Simple moving average of last `period` TR values
            atr = sum(tr_values[-period:]) / period
            return float(atr)

        except Exception:
            return None

    # ------------------------------------------------------------------
    # Positive reasons (for BUY signals)
    # ------------------------------------------------------------------

    def _generate_positive_reasons(
        self,
        score: float,
        rank: int | None,
        total_stocks: int,
        guardrail_status: dict[str, Any],
        factor_snapshot: dict[str, FactorSnapshot],
    ) -> list[str]:
        """Generate positive confirmation reasons for BUY signals."""
        reasons: list[str] = []

        # Model score
        if not math.isnan(score) and score > 0:
            reasons.append(f"✅ 模型分数 {score:+.4f} 为正")

        # Rank
        if rank is not None and total_stocks > 0:
            pct = (rank + 1) / total_stocks * 100
            if pct <= 10:
                reasons.append(f"✅ 排名 Top {pct:.1f}%（{rank + 1}/{total_stocks}）")

        # Guardrails passed
        if guardrail_status.get("overall_passed", True):
            reasons.append("✅ 护栏检查全部通过")

        # Positive factors
        for name, snap in factor_snapshot.items():
            if snap.z_score is not None and snap.z_score > 1.0:
                reasons.append(f"✅ {name} 因子 z-score={snap.z_score:+.2f}，处于强势区间")

        return reasons
