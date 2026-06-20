"""Stock Analysis API — per-stock decision support with factor exposure,
guardrail status, and watchlist signal overview.

Endpoints:
    GET /{symbol}/decision      — BUY/HOLD/SELL decision with reasoning
    GET /{symbol}/factors       — factor values for a single stock
    GET /{symbol}/history       — signal history for a single stock
    GET /watchlist/summary      — signal overview for the full watchlist
    POST /portfolio/analysis    — batch analysis for a list of symbols
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/stock-analysis", tags=["stock-analysis"])


def _infer_market(symbol: str) -> str:
    """Infer market from symbol suffix or numeric pattern."""
    s = symbol.strip().upper()
    if s.endswith(".SH") or s.endswith(".SZ"):
        return "cn"
    # CN A-share codes are 6-digit numbers
    if s.isdigit() and len(s) == 6:
        return "cn"
    return "us"


def _clean_symbol(symbol: str) -> str:
    """Strip suffix for Qlib lookup (CN symbols keep numeric part only)."""
    s = symbol.strip().upper()
    if s.endswith(".SH") or s.endswith(".SZ"):
        return s.split(".")[0]
    return s


def _get_engine():
    """Lazy import to avoid circular dependencies."""
    from src.strategies.stock_decision_engine import StockDecisionEngine

    return StockDecisionEngine()


def _load_predictions_and_ranks(market: str):
    """Load model predictions and compute rank_map for the given market.

    Returns (pred_score: pd.Series, rank_map: dict, freshness: dict) or (None, None, None).
    """
    try:
        import pickle
        from pathlib import Path

        from src.common.paths import ARTIFACTS_DIR, MLRUNS_DIR

        # Search in multiple directories including root mlruns
        project_root = Path(__file__).resolve().parents[3]
        search_dirs = [MLRUNS_DIR, ARTIFACTS_DIR, project_root / "mlruns"]

        # Try to find the recommended model's predictions matching the market
        pred_df = None
        pred_path = None
        pred_mtime = 0.0

        # Strategy 1: look for latest pred.pkl in mlruns that matches market
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            pred_files = sorted(
                search_dir.rglob("pred.pkl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for pf in pred_files:
                try:
                    with pf.open("rb") as f:
                        candidate = pickle.load(f)
                    if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                        # Validate market match
                        if _validate_market(candidate, market):
                            pred_df = candidate
                            pred_path = pf
                            pred_mtime = pf.stat().st_mtime
                            break
                except Exception:
                    continue
            if pred_df is not None:
                break

        # Also check for 'pred' files without extension (Qlib output)
        if pred_df is None:
            for search_dir in search_dirs:
                if not search_dir.exists():
                    continue
                for pred_file in sorted(
                    search_dir.rglob("pred"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )[:5]:
                    try:
                        with pred_file.open("rb") as f:
                            candidate = pickle.load(f)
                        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                            if hasattr(candidate.index, 'get_level_values') and 'datetime' in candidate.index.names:
                                pred_df = candidate
                                pred_path = pred_file
                                pred_mtime = pred_file.stat().st_mtime
                                break
                    except Exception:
                        continue
                if pred_df is not None:
                    break

        if pred_df is None or pred_df.empty:
            return None, None, None

        # Compute freshness info
        from datetime import datetime
        pred_age_days = (datetime.now().timestamp() - pred_mtime) / 86400 if pred_mtime > 0 else None
        freshness = {
            "pred_age_days": round(pred_age_days, 1) if pred_age_days is not None else None,
            "is_stale": pred_age_days is not None and pred_age_days > 7,
            "pred_path": str(pred_path) if pred_path else None,
        }

        # Get the latest date's cross-section
        if isinstance(pred_df.index, pd.MultiIndex) and "datetime" in pred_df.index.names:
            latest_date = pred_df.index.get_level_values("datetime").max()
            pred_latest = pred_df.xs(latest_date, level="datetime")
        else:
            pred_latest = pred_df

        if isinstance(pred_latest, pd.DataFrame):
            pred_score = pred_latest.iloc[:, 0]
        else:
            pred_score = pred_latest

        pred_score = pred_score.sort_values(ascending=False)
        rank_map = {inst: idx for idx, inst in enumerate(pred_score.index)}

        return pred_score, rank_map, freshness

    except Exception as exc:
        logger.warning("load_predictions_failed", error=str(exc))
        return None, None, None


def _load_watchlist(market: str) -> list[str]:
    """Load watchlist tickers for the given market."""
    try:
        from pathlib import Path

        import yaml

        watchlist_path = Path(__file__).resolve().parents[3] / "configs" / "watchlist.yaml"
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

        # Filter out ETFs and non-stock entries
        stocks = [t for t in tickers if isinstance(t, str) and not t.startswith("SPY") and not t.startswith("QQQ")]
        return stocks

    except Exception as exc:
        logger.warning("load_watchlist_failed", error=str(exc))
        return []


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/{symbol}/decision")
def get_stock_decision(
    symbol: str,
    market: str = Query(None, description="us or cn (auto-detected if omitted)"),
    include_factors: bool = Query(True, description="Include factor exposure snapshot"),
):
    """Get a BUY / HOLD / SELL decision for a single stock with reasoning."""
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    # Load predictions
    pred_score, rank_map, freshness = _load_predictions_and_ranks(resolved_market)
    if pred_score is None:
        raise HTTPException(
            status_code=404,
            detail="No model predictions found. Run training or backtest first.",
        )

    if clean not in rank_map:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{symbol}' not found in model predictions for market '{resolved_market}'.",
        )

    engine = _get_engine()
    try:
        decision = engine.evaluate(
            symbol=clean,
            pred_score=pred_score,
            rank_map=rank_map,
            market=resolved_market,
            include_factors=include_factors,
        )
    except Exception as exc:
        logger.error("stock_decision_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    result = {"ok": True, "decision": decision.to_dict()}
    if freshness:
        result["data_freshness"] = freshness
    return result


@router.get("/{symbol}/factors")
def get_stock_factors(
    symbol: str,
    market: str = Query(None, description="us or cn"),
):
    """Get factor values for a single stock (Active factors from registry)."""
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    try:
        from qlib.data import D

        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
        from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

        safe_qlib_init(build_qlib_init_cfg({}, market=resolved_market))

        registry = FactorRegistry()
        active_factors = registry.list_factors(stage=STAGE_ACTIVE)

        if not active_factors:
            return {"ok": True, "symbol": symbol, "factors": [], "message": "No Active factors in registry"}

        factors_to_eval = active_factors[:30]  # limit for performance
        expressions = [f["expression"] for f in factors_to_eval]

        # Fetch stock values
        stock_df = D.features(
            [clean],
            expressions,
            start_time=pd.Timestamp.now() - pd.Timedelta(days=60),
        )

        # Fetch universe values for z-score
        universe_df = D.features(
            "$all",
            expressions,
            start_time=pd.Timestamp.now() - pd.Timedelta(days=60),
        )

        result = []
        if not stock_df.empty:
            stock_latest = stock_df.iloc[-1]
            for i, factor in enumerate(factors_to_eval):
                val = None
                z_score = None
                percentile = None

                if pd.notna(stock_latest.iloc[i]):
                    val = float(stock_latest.iloc[i])

                    if not universe_df.empty:
                        col = universe_df.iloc[:, i].dropna()
                        if len(col) > 1:
                            latest_per_stock = col.groupby(level="instrument").last()
                            mean_val = float(latest_per_stock.mean())
                            std_val = float(latest_per_stock.std())
                            if std_val > 1e-10:
                                z_score = (val - mean_val) / std_val
                            percentile = float((latest_per_stock < val).sum() / len(latest_per_stock) * 100)

                result.append({
                    "name": factor["name"],
                    "expression": factor["expression"],
                    "category": factor["category"],
                    "value": val,
                    "z_score": round(z_score, 4) if z_score is not None else None,
                    "percentile": round(percentile, 1) if percentile is not None else None,
                })

        return {"ok": True, "symbol": symbol, "market": resolved_market, "factors": result}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("stock_factors_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/summary")
def get_watchlist_summary(
    market: str = Query("us", description="us or cn"),
    include_factors: bool = Query(False, description="Include factor snapshots (slower)"),
):
    """Get signal overview for all stocks in the watchlist."""
    tickers = _load_watchlist(market)
    if not tickers:
        raise HTTPException(
            status_code=404,
            detail=f"No watchlist found for market '{market}'. Check configs/watchlist.yaml.",
        )

    pred_score, rank_map, freshness = _load_predictions_and_ranks(market)
    if pred_score is None:
        raise HTTPException(
            status_code=404,
            detail="No model predictions found. Run training or backtest first.",
        )

    engine = _get_engine()
    summary = []

    # G3: Batch-fetch price data for all tickers
    price_map: dict[str, dict] = {}
    try:
        from qlib.data import D

        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        safe_qlib_init(build_qlib_init_cfg({}, market=market))

        clean_tickers = [_clean_symbol(t) for t in tickers if _clean_symbol(t) in rank_map]
        if clean_tickers:
            price_df = D.features(
                clean_tickers,
                ["$close", "Ref($close, 1)", "Ref($close, 5)"],
                start_time=pd.Timestamp.now() - pd.Timedelta(days=10),
            )
            if not price_df.empty:
                for inst in clean_tickers:
                    try:
                        sub = price_df.xs(inst, level="instrument")
                        if not sub.empty:
                            last = sub.iloc[-1]
                            close = float(last.iloc[0]) if pd.notna(last.iloc[0]) else None
                            prev_close = float(last.iloc[1]) if pd.notna(last.iloc[1]) else None
                            close_5d = float(last.iloc[2]) if pd.notna(last.iloc[2]) else None
                            change_pct = ((close - prev_close) / prev_close * 100) if close and prev_close and prev_close > 0 else None
                            change_5d_pct = ((close - close_5d) / close_5d * 100) if close and close_5d and close_5d > 0 else None
                            price_map[inst] = {
                                "price": round(close, 2) if close else None,
                                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                                "change_5d_pct": round(change_5d_pct, 2) if change_5d_pct is not None else None,
                            }
                    except Exception:
                        continue
    except Exception as exc:
        logger.debug("watchlist_price_fetch_failed", error=str(exc))

    for ticker in tickers:
        clean = _clean_symbol(ticker)
        if clean not in rank_map:
            continue

        try:
            decision = engine.evaluate(
                symbol=clean,
                pred_score=pred_score,
                rank_map=rank_map,
                market=market,
                include_factors=include_factors,
            )
            item = {
                "symbol": ticker,
                "signal": decision.signal,
                "confidence": round(decision.confidence, 3),
                "score": round(decision.score, 4) if not math.isnan(decision.score) else None,
                "rank": decision.rank,
                "risk_flags": decision.risk_flags,
            }
            # G3: Add price data
            px = price_map.get(clean)
            if px:
                item["price"] = px["price"]
                item["change_pct"] = px["change_pct"]
                item["change_5d_pct"] = px["change_5d_pct"]

            # G3: Add strategy recommendation
            if decision.recommended_strategy:
                item["recommended_strategy"] = decision.recommended_strategy.display_name

            summary.append(item)
        except Exception as exc:
            logger.debug("watchlist_summary_skip", symbol=ticker, error=str(exc))
            continue

    # Sort by signal priority: BUY first, then HOLD, then SELL
    signal_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    summary.sort(key=lambda x: (signal_order.get(x["signal"], 1), -(x["confidence"] or 0)))

    result = {
        "ok": True,
        "market": market,
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "total": len(summary),
        "summary": summary,
    }
    if freshness:
        result["data_freshness"] = freshness
    return result


# ------------------------------------------------------------------
# P2-5: Data freshness check
# ------------------------------------------------------------------


@router.get("/data/freshness")
def get_data_freshness(market: str = Query("us", description="us or cn")):
    """Check data freshness for the given market.

    Returns the latest data date for each data source, staleness warnings,
    and overall data health status.
    """
    try:

        result: dict = {
            "ok": True,
            "market": market,
            "checked_at": pd.Timestamp.now().isoformat(),
            "sources": {},
            "warnings": [],
        }

        # Check Qlib data
        try:
            from qlib.data import D

            from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

            safe_qlib_init(build_qlib_init_cfg({}, market=market))

            # Get latest date from Qlib
            df = D.features(["AAPL"], ["$close"], start_time="2024-01-01")
            if not df.empty:
                latest_date = df.index.get_level_values("datetime").max()
                age_days = (pd.Timestamp.now() - latest_date).days
                result["sources"]["qlib"] = {
                    "available": True,
                    "latest_date": latest_date.strftime("%Y-%m-%d"),
                    "age_days": age_days,
                }
                if age_days > 3:
                    result["warnings"].append(f"Qlib data is {age_days} days old (latest: {latest_date.strftime('%Y-%m-%d')})")
            else:
                result["sources"]["qlib"] = {"available": False}
                result["warnings"].append("No Qlib data found")
        except Exception as exc:
            result["sources"]["qlib"] = {"available": False, "error": str(exc)}

        # Check predictions
        from datetime import datetime as _dt

        from src.common.paths import ARTIFACTS_DIR as _ar
        from src.common.paths import MLRUNS_DIR as _ml

        best_pred_age = None
        for search_dir in [_ml, _ar]:
            if not search_dir.exists():
                continue
            for pred_file in search_dir.rglob("pred.pkl"):
                mt = _dt.fromtimestamp(pred_file.stat().st_mtime)
                age = (_dt.now() - mt).days
                if best_pred_age is None or age < best_pred_age:
                    best_pred_age = age

        if best_pred_age is not None:
            result["sources"]["predictions"] = {
                "available": True,
                "age_days": best_pred_age,
            }
            if best_pred_age > 7:
                result["warnings"].append(f"Predictions are {best_pred_age} days old")
        else:
            result["sources"]["predictions"] = {"available": False}
            result["warnings"].append("No prediction files found")

        # Overall status
        if not result["warnings"]:
            result["status"] = "fresh"
        elif len(result["warnings"]) <= 1:
            result["status"] = "stale"
        else:
            result["status"] = "outdated"

        return result

    except Exception as exc:
        logger.error("data_freshness_check_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# P1-3: Portfolio analysis (batch decisions)
# ------------------------------------------------------------------


class PortfolioAnalysisRequest(BaseModel):
    """Request body for portfolio analysis."""

    symbols: list[str]
    market: str = "us"
    include_factors: bool = False


@router.post("/portfolio/analysis")
def analyze_portfolio(req: PortfolioAnalysisRequest):
    """Run decision engine on a batch of symbols (portfolio holdings).

    Returns per-symbol decisions with signal, confidence, price targets,
    and strategy recommendations.
    """
    if not req.symbols:
        raise HTTPException(status_code=400, detail="symbols list is empty")

    pred_score, rank_map, freshness = _load_predictions_and_ranks(req.market)
    if pred_score is None:
        raise HTTPException(
            status_code=404,
            detail="No model predictions found. Run training or backtest first.",
        )

    engine = _get_engine()
    results: list[dict[str, Any]] = []
    stats = {"BUY": 0, "HOLD": 0, "SELL": 0, "error": 0}

    for symbol in req.symbols:
        clean = _clean_symbol(symbol)
        if clean not in rank_map:
            results.append({
                "symbol": symbol,
                "error": f"Symbol not found in model predictions for market '{req.market}'",
            })
            stats["error"] += 1
            continue

        try:
            decision = engine.evaluate(
                symbol=clean,
                pred_score=pred_score,
                rank_map=rank_map,
                market=req.market,
                include_factors=req.include_factors,
            )
            results.append(decision.to_dict())
            stats[decision.signal] += 1
        except Exception as exc:
            logger.error("portfolio_analysis_failed", symbol=symbol, error=str(exc))
            results.append({"symbol": symbol, "error": str(exc)})
            stats["error"] += 1

    result = {
        "ok": True,
        "market": req.market,
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "total": len(results),
        "stats": stats,
        "decisions": results,
    }
    if freshness:
        result["data_freshness"] = freshness
    return result


# ------------------------------------------------------------------
# P1-4: Signal history (persistent SQLite store)
# ------------------------------------------------------------------


class _SignalHistoryStore:
    """Lightweight SQLite store for persisting stock decisions over time."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from src.common.paths import ARTIFACTS_DIR

            db_path = str(ARTIFACTS_DIR / "signal_history.db")
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self):
        import sqlite3

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence REAL,
                    score REAL,
                    rank INTEGER,
                    price_targets TEXT,
                    recommended_strategy TEXT,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_history_symbol ON signal_history(symbol, market)"
            )

    def record(self, symbol: str, market: str, decision: dict[str, Any]) -> None:
        """Persist a decision to the history store."""
        import json
        from datetime import datetime

        now = datetime.now().isoformat()
        pt = decision.get("price_targets")
        rec = decision.get("recommended_strategy")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_history
                    (symbol, market, signal, confidence, score, rank,
                     price_targets, recommended_strategy, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.upper(),
                    market.lower(),
                    decision.get("signal"),
                    decision.get("confidence"),
                    decision.get("score"),
                    decision.get("rank"),
                    json.dumps(pt) if pt else None,
                    json.dumps(rec) if rec else None,
                    now,
                ),
            )

    def get_history(
        self, symbol: str, market: str = "us", days: int = 30
    ) -> list[dict[str, Any]]:
        """Retrieve signal history for a symbol."""
        import json
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signal_history
                WHERE symbol = ? AND market = ? AND recorded_at >= ?
                ORDER BY recorded_at DESC
                """,
                (symbol.upper(), market.lower(), cutoff),
            ).fetchall()

        results = []
        for row in rows:
            d = {
                "signal": row["signal"],
                "confidence": row["confidence"],
                "score": row["score"],
                "rank": row["rank"],
                "recorded_at": row["recorded_at"],
            }
            if row["price_targets"]:
                d["price_targets"] = json.loads(row["price_targets"])
            if row["recommended_strategy"]:
                d["recommended_strategy"] = json.loads(row["recommended_strategy"])
            results.append(d)

        return results


_history_store: _SignalHistoryStore | None = None


def _get_history_store() -> _SignalHistoryStore:
    global _history_store
    if _history_store is None:
        _history_store = _SignalHistoryStore()
    return _history_store


@router.get("/{symbol}/history")
def get_signal_history(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    days: int = Query(30, description="Number of days of history to return"),
):
    """Get signal history for a single stock.

    Returns the historical record of BUY/HOLD/SELL signals over time,
    including price targets and strategy recommendations at each point.
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    store = _get_history_store()

    try:
        history = store.get_history(symbol, resolved_market, days)
    except Exception as exc:
        logger.error("signal_history_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "market": resolved_market,
        "days": days,
        "count": len(history),
        "history": history,
    }


# ------------------------------------------------------------------
# P4-1: Natural language strategy compilation
# ---------------------------------------------------------------------------

# Keyword → factor category mapping (supports both Chinese and English)
_KEYWORD_CATEGORY_MAP: dict[str, list[str]] = {
    # English keywords
    "momentum": ["momentum"],
    "trend": ["momentum"],
    "volatility": ["volatility"],
    "risk": ["volatility"],
    "volume": ["volume"],
    "liquidity": ["volume"],
    "mean reversion": ["mean_reversion"],
    "reversion": ["mean_reversion"],
    "technical": ["technical"],
    "value": ["technical"],
    "composite": ["composite"],
    # Chinese keywords
    "动量": ["momentum"],
    "趋势": ["momentum"],
    "波动": ["volatility"],
    "风险": ["volatility"],
    "成交量": ["volume"],
    "量能": ["volume"],
    "流动性": ["volume"],
    "均值回归": ["mean_reversion"],
    "回归": ["mean_reversion"],
    "技术": ["technical"],
    "综合": ["composite"],
    "低波动": ["volatility"],
    "高动量": ["momentum"],
    "强势": ["momentum"],
    "放量": ["volume"],
}


class NLStrategyRequest(BaseModel):
    """Natural language strategy description."""

    description: str  # e.g. "低波动率、高动量" or "low volatility, strong momentum"
    market: str = "us"
    max_factors: int = 10


@router.post("/nl-compile")
def compile_nl_strategy(req: NLStrategyRequest):
    """Compile a natural language strategy description into factor recommendations.

    Accepts Chinese or English descriptions like:
    - "低波动率、高动量"
    - "low volatility, strong momentum, high volume"
    - "均值回归、技术面强势"

    Returns:
    - Matched factor categories
    - Recommended Active factors from the registry
    - Suggested strategy based on factor profile
    """
    description = req.description.strip().lower()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    # Parse keywords into categories
    matched_categories: list[str] = []
    matched_keywords: list[str] = []

    for keyword, categories in _KEYWORD_CATEGORY_MAP.items():
        if keyword in description:
            matched_categories.extend(categories)
            matched_keywords.append(keyword)

    # Deduplicate
    matched_categories = list(dict.fromkeys(matched_categories))
    matched_keywords = list(dict.fromkeys(matched_keywords))

    if not matched_categories:
        # Fallback: try to match against factor names in registry
        matched_categories = ["momentum", "technical"]  # sensible default

    # Query factor registry for matching Active factors
    recommended_factors: list[dict] = []
    try:
        from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

        registry = FactorRegistry()
        all_active = registry.list_factors(stage=STAGE_ACTIVE)

        # Filter by matched categories
        for factor in all_active:
            if factor["category"] in matched_categories:
                recommended_factors.append({
                    "name": factor["name"],
                    "expression": factor["expression"],
                    "category": factor["category"],
                    "direction": factor.get("direction", "long"),
                })

        # If not enough, add top factors from other categories
        if len(recommended_factors) < req.max_factors:
            for factor in all_active:
                if factor["name"] not in {f["name"] for f in recommended_factors}:
                    recommended_factors.append({
                        "name": factor["name"],
                        "expression": factor["expression"],
                        "category": factor["category"],
                        "direction": factor.get("direction", "long"),
                    })
                if len(recommended_factors) >= req.max_factors:
                    break

    except Exception as exc:
        logger.warning("nl_compile_registry_failed", error=str(exc))

    # Recommend strategy based on factor profile
    strategy_recommendation = _recommend_strategy_from_categories(matched_categories)

    return {
        "ok": True,
        "input": req.description,
        "matched_keywords": matched_keywords,
        "matched_categories": matched_categories,
        "recommended_factors": recommended_factors[:req.max_factors],
        "strategy_recommendation": strategy_recommendation,
        "message": f"Found {len(recommended_factors)} factors matching '{req.description}'",
    }


def _recommend_strategy_from_categories(categories: list[str]) -> dict:
    """Recommend a strategy based on the factor categories in the profile."""
    category_set = set(categories)

    # Multi-factor with volatility → DualLayer
    if len(category_set) >= 2 and "volatility" in category_set:
        return {
            "name": "dual_layer",
            "display_name": "Dual Layer Strategy",
            "reason": "多因子 + 波动率信号适合双层策略的个股决策引擎分解",
            "confidence": 0.8,
        }

    # Pure momentum → WeeklyQuantRating
    if category_set == {"momentum"}:
        return {
            "name": "weekly_quant_rating",
            "display_name": "Weekly Quant Rating",
            "reason": "纯动量信号适合周度评级策略的连续买入逻辑",
            "confidence": 0.75,
        }

    # Default → BiweeklyTrend
    return {
        "name": "biweekly_trend",
        "display_name": "Biweekly Trend",
        "reason": "双周调仓策略适合大多数因子组合",
        "confidence": 0.6,
    }


@router.post("/{symbol}/record")
def record_decision(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    include_factors: bool = Query(False),
):
    """Run the decision engine and record the result to signal history.

    This is the endpoint to call for daily/periodic signal recording.
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    pred_score, rank_map, freshness = _load_predictions_and_ranks(resolved_market)
    if pred_score is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    if clean not in rank_map:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in predictions.")

    engine = _get_engine()
    try:
        decision = engine.evaluate(
            symbol=clean,
            pred_score=pred_score,
            rank_map=rank_map,
            market=resolved_market,
            include_factors=include_factors,
        )
        decision_dict = decision.to_dict()

        # Persist to history
        store = _get_history_store()
        store.record(clean, resolved_market, decision_dict)

        return {"ok": True, "decision": decision_dict}
    except Exception as exc:
        logger.error("record_decision_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Signal Grade endpoints (AAA/AA/A/V/VV/VVV)
# ------------------------------------------------------------------


def _validate_market(pred_df: pd.DataFrame, expected_market: str) -> bool:
    """Check if predictions match the expected market.

    CN stocks have 6-digit numeric codes, US stocks have alphabetic codes.
    Returns True if predictions seem to match the market.
    """
    try:
        instruments = pred_df.index.get_level_values("instrument").unique()
        if len(instruments) == 0:
            return False

        sample = list(instruments)[:10]
        cn_count = sum(1 for s in sample if str(s).isdigit() and len(str(s)) == 6)
        us_count = sum(1 for s in sample if not str(s).isdigit())

        if expected_market == "cn":
            return cn_count > len(sample) * 0.5
        else:
            return us_count > len(sample) * 0.5
    except Exception:
        return True  # Assume valid if can't check


# Cache for loaded predictions: {cache_key: (pred_df, timestamp)}
_pred_cache: dict[str, tuple[pd.DataFrame, float]] = {}
_PRED_CACHE_TTL = 300  # 5 minutes


def _load_full_predictions(market: str, run_id: str | None = None):
    """Load the full prediction DataFrame (not just latest cross-section).

    Parameters
    ----------
    market : str
        Market identifier (us/cn).
    run_id : str, optional
        Specific MLflow run ID to load predictions from. If None, loads the latest.

    Returns pred_df with MultiIndex (datetime, instrument) or None.
    """
    try:
        import pickle

        from src.common.paths import ARTIFACTS_DIR, MLRUNS_DIR

        # If specific run_id requested, find it directly
        if run_id:
            for search_dir in [MLRUNS_DIR]:
                if not search_dir.exists():
                    continue
                for exp_dir in search_dir.iterdir():
                    if not exp_dir.is_dir():
                        continue
                    pred_path = exp_dir / run_id / "artifacts" / "pred.pkl"
                    if pred_path.exists():
                        try:
                            with pred_path.open("rb") as f:
                                candidate = pickle.load(f)
                            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                                return candidate
                        except Exception:
                            continue
                    # Also check without extension
                    pred_path = exp_dir / run_id / "artifacts" / "pred"
                    if pred_path.exists():
                        try:
                            with pred_path.open("rb") as f:
                                candidate = pickle.load(f)
                            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                                return candidate
                        except Exception:
                            continue

        # Default: find the latest pred.pkl that matches the market
        from pathlib import Path as _Path
        project_root = _Path(__file__).resolve().parents[3]
        search_dirs = [MLRUNS_DIR, ARTIFACTS_DIR, project_root / "mlruns"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            pred_files = sorted(
                search_dir.rglob("pred.pkl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for pf in pred_files:
                try:
                    with pf.open("rb") as f:
                        candidate = pickle.load(f)
                    if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                        # Validate market match
                        if _validate_market(candidate, market):
                            return candidate
                        logger.debug("pred_market_mismatch", path=str(pf), expected=market)
                except Exception:
                    continue

        # Also check for 'pred' files without extension (Qlib output)
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for pred_file in sorted(
                search_dir.rglob("pred"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:5]:
                try:
                    with pred_file.open("rb") as f:
                        candidate = pickle.load(f)
                    if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                        if hasattr(candidate.index, 'get_level_values') and 'datetime' in candidate.index.names:
                            if _validate_market(candidate, market):
                                return candidate
                except Exception:
                    continue

        return None
    except Exception as exc:
        logger.warning("load_full_predictions_failed", error=str(exc))
        return None


def _load_predictions_with_cache(market: str, run_id: str | None = None):
    """Load predictions with caching wrapper."""
    import time

    cache_key = f"{market}:{run_id or 'latest'}"
    now = time.time()

    # Check cache
    if cache_key in _pred_cache:
        pred_df, cached_at = _pred_cache[cache_key]
        if now - cached_at < _PRED_CACHE_TTL:
            return pred_df

    # Load fresh
    pred_df = _load_full_predictions(market, run_id)

    # Cache result
    if pred_df is not None:
        _pred_cache[cache_key] = (pred_df, now)
        # Evict old entries
        if len(_pred_cache) > 10:
            oldest_key = min(_pred_cache, key=lambda k: _pred_cache[k][1])
            del _pred_cache[oldest_key]

    return pred_df


@router.get("/{symbol}/signal-grade")
def get_signal_grade(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    step_size: int = Query(10, description="Grade tier size (default 10: AAA=Top10, AA=Top20, A=Top30)"),
    include_history: bool = Query(False, description="Include historical grades"),
):
    """Get the current signal grade (AAA/AA/A/V/VV/VVV) for a stock.

    The grade is based on the stock's cross-sectional rank in the latest
    model prediction. Configurable step_size changes the tier boundaries.
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    from src.strategies.signal_grade_engine import SignalGradeEngine

    pred_df = _load_predictions_with_cache(resolved_market)
    if pred_df is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    engine = SignalGradeEngine(step_size=step_size)

    # Get latest date's grade
    grade = engine.get_grade_for_date(clean, pred_df, pd.Timestamp.now().strftime("%Y-%m-%d"))

    result = {
        "ok": True,
        "symbol": symbol.upper(),
        "market": resolved_market,
        "step_size": step_size,
        "grade": grade.to_dict(),
    }

    # Optionally include historical grades
    if include_history:
        history = engine.get_historical_grades(clean, pred_df)
        result["history"] = [g.to_dict() for g in history[-50:]]  # Last 50

    return result


@router.get("/{symbol}/signal-performance")
def get_signal_performance(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    step_size: int = Query(10, description="Grade tier size"),
    forward_days: int = Query(10, description="Forward return period in days"),
    run_id: str = Query(None, description="Specific model run ID (optional)"),
    model_version_id: str = Query("", description="Model version identifier"),
    policy_version: str = Query("", description="Grade policy version"),
):
    """Get historical signal performance for a stock.

    Returns cumulative returns for each signal grade (AAA/AA/A/V/VV/VVV)
    based on actual price movements after each signal occurrence.

    Now includes evidence fields: model_version_id, policy_version,
    direction_adjusted_hit_rate, benchmark_excess_return, cost_adjusted_return,
    confidence_interval_95, qualification_status, failure_reasons.
    Also returns per-grade screener counts and evaluation period.
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    from src.strategies.signal_grade_engine import GRADES, SignalGradeEngine

    pred_df = _load_predictions_with_cache(resolved_market, run_id=run_id)
    if pred_df is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    engine = SignalGradeEngine(step_size=step_size)

    try:
        performance = engine.compute_performance(
            symbol=clean,
            pred_df=pred_df,
            market=resolved_market,
            forward_days=forward_days,
            model_version_id=model_version_id or (run_id or ""),
            policy_version=policy_version or f"step{step_size}",
        )

        # Compute total score
        total_score = engine.compute_total_score(performance)

        # Compute evaluation period from pred_df
        eval_start = None
        eval_end = None
        if isinstance(pred_df.index, pd.MultiIndex) and "datetime" in pred_df.index.names:
            dates = pred_df.index.get_level_values("datetime")
            eval_start = dates.min().strftime("%Y-%m-%d")
            eval_end = dates.max().strftime("%Y-%m-%d")

        # Per-grade screener counts
        grade_counts: dict[str, dict[str, int]] = {}
        total_count = 0
        eligible_count = 0
        graded_count = 0
        neutral_count = 0
        unqualified_count = 0
        excluded_count = 0
        failed_count = 0

        for g in GRADES:
            p = performance.get(g)
            if p is None:
                grade_counts[g] = {"occurrences": 0, "qualified": 0, "unqualified": 0}
                continue
            occ = p.total_occurrences
            total_count += occ
            is_qualified = p.qualification_status == "qualified"
            is_unqualified = p.qualification_status == "unqualified"
            is_excluded = p.qualification_status == "excluded"
            is_failed = p.qualification_status == "failed"

            grade_counts[g] = {
                "occurrences": occ,
                "qualified": 1 if is_qualified else 0,
                "unqualified": 1 if is_unqualified else 0,
                "excluded": 1 if is_excluded else 0,
                "failed": 1 if is_failed else 0,
            }
            if occ > 0:
                eligible_count += 1
            if is_qualified:
                graded_count += occ
            elif is_unqualified:
                unqualified_count += occ
            elif is_excluded:
                excluded_count += occ
            elif is_failed:
                failed_count += occ

        # Stocks with no grade get "neutral"
        # Count neutral as total - (graded + unqualified + excluded + failed)
        neutral_count = max(0, total_count - graded_count - unqualified_count - excluded_count - failed_count)

        screener_counts = {
            "total": total_count,
            "eligible": eligible_count,
            "graded": graded_count,
            "neutral": neutral_count,
            "unqualified": unqualified_count,
            "excluded": excluded_count,
            "failed": failed_count,
        }

        return {
            "ok": True,
            "symbol": symbol.upper(),
            "market": resolved_market,
            "step_size": step_size,
            "forward_days": forward_days,
            "model_version_id": model_version_id or (run_id or "latest"),
            "policy_version": policy_version or f"step{step_size}",
            "evaluation_period": {
                "start": eval_start,
                "end": eval_end,
            },
            "screener_counts": screener_counts,
            "grade_counts": grade_counts,
            "performance": {k: v.to_dict() for k, v in performance.items()},
            "total_score": total_score,
        }
    except Exception as exc:
        logger.error("signal_performance_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/signal-markers")
def get_signal_markers(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    step_size: int = Query(10, description="Grade tier size"),
    start_date: str = Query(None, description="Start date for markers (ISO format)"),
    run_id: str = Query(None, description="Specific model run ID (optional)"),
    forward_days: int = Query(10, description="Forward return period for tooltips"),
    include_returns: bool = Query(True, description="Include forward returns in tooltips"),
):
    """Get K-line chart markers for all historical signal grades.

    Returns a list of markers compatible with lightweight-charts addMarkers API.
    Each marker has: time, position, color, shape, text (grade), size, tooltip.
    The tooltip includes identity, timestamp, rank, score, grade, qualification,
    and forward return (when available).
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    from src.strategies.signal_grade_engine import SignalGradeEngine

    pred_df = _load_predictions_with_cache(resolved_market, run_id=run_id)
    if pred_df is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    engine = SignalGradeEngine(step_size=step_size)

    try:
        # Optionally fetch price data for forward return tooltips
        price_df = None
        if include_returns:
            try:
                from qlib.data import D

                from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

                safe_qlib_init(build_qlib_init_cfg({}, market=resolved_market))
                price_df = D.features(
                    [clean],
                    ["$close"],
                    start_time=pd.Timestamp.now() - pd.Timedelta(days=365 * 3),
                )
                if hasattr(price_df.index, 'get_level_values') and 'instrument' in price_df.index.names:
                    price_df = price_df.xs(clean, level="instrument")
            except Exception:
                price_df = None

        markers = engine.get_kline_markers(
            clean, pred_df, start_date=start_date,
            price_df=price_df, market=resolved_market, forward_days=forward_days,
        )

        return {
            "ok": True,
            "symbol": symbol.upper(),
            "market": resolved_market,
            "step_size": step_size,
            "total_markers": len(markers),
            "markers": markers,
        }
    except Exception as exc:
        logger.error("signal_markers_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/signal-daily")
def get_daily_signal_series(
    symbol: str,
    market: str = Query(None, description="us or cn"),
    step_size: int = Query(10, description="Grade tier size"),
    days: int = Query(120, description="Number of calendar days to return"),
    run_id: str = Query(None, description="Specific model run ID (optional)"),
):
    """Get daily signal series for chart overlay.

    Returns percentile rank and grade for every trading day, designed for
    rendering as a colored area below the price chart.
    """
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")

    resolved_market = market or _infer_market(symbol)
    clean = _clean_symbol(symbol)

    from src.strategies.signal_grade_engine import SignalGradeEngine

    pred_df = _load_predictions_with_cache(resolved_market, run_id=run_id)
    if pred_df is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    engine = SignalGradeEngine(step_size=step_size)

    try:
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
        series = engine.get_daily_signal_series(clean, pred_df, start_date=start_date)

        return {
            "ok": True,
            "symbol": symbol.upper(),
            "market": resolved_market,
            "step_size": step_size,
            "total_points": len(series),
            "series": series,
        }
    except Exception as exc:
        logger.error("daily_signal_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Stock Ranking endpoint (model effectiveness per stock)
# ------------------------------------------------------------------


@router.get("/ranking")
def get_stock_ranking(
    market: str = Query("us", description="us or cn"),
    step_size: int = Query(10, description="Grade tier size"),
    forward_days: int = Query(10, description="Holding period in days"),
    sort_by: str = Query("weighted_score", description="Sort by: weighted_score, win_rate, mean_return, cumulative_return"),
    sort_grade: str = Query("AAA", description="For grade-specific sorting: AAA, AA, A, V, VV, VVV"),
    limit: int = Query(50, description="Max stocks to return"),
    run_id: str = Query(None, description="Specific model run ID"),
):
    """Rank stocks by model prediction effectiveness.

    Returns all stocks in the universe ranked by how well the model's
    signals predict their actual price movements.

    Scoring logic:
    - AAA/AA/A (buy signals): positive cumulative return → positive contribution
    - V/VV/VVV (sell signals): negative cumulative return → positive contribution
    - Weighted by signal strength (AAA=3, AA=2, A=1, V=-1, VV=-2, VVV=-3)

    Sort options:
    - weighted_score: Overall model effectiveness (default)
    - win_rate: Sort by win rate of a specific grade
    - mean_return: Sort by mean return of a specific grade
    - cumulative_return: Sort by cumulative return of a specific grade
    """
    from src.strategies.signal_grade_engine import GRADES, SignalGradeEngine

    pred_df = _load_predictions_with_cache(market, run_id=run_id)
    if pred_df is None:
        raise HTTPException(status_code=404, detail="No model predictions found.")

    engine = SignalGradeEngine(step_size=step_size)

    try:
        # Compute scores for all stocks
        scores = engine.compute_universe_scores(
            pred_df=pred_df,
            market=market,
            forward_days=forward_days,
            top_n=limit * 2,  # Compute more than needed for sorting
        )

        # Apply sorting
        if sort_by == "weighted_score":
            scores.sort(key=lambda s: s.weighted_score, reverse=True)
        elif sort_by in ("win_rate", "mean_return", "cumulative_return"):
            grade = sort_grade if sort_grade in GRADES else "AAA"
            # For V/VV/VVV cumulative_return, more negative is better
            if sort_by == "cumulative_return" and grade in ("V", "VV", "VVV"):
                scores.sort(
                    key=lambda s: s.grade_details.get(grade, {}).get(sort_by, 0),
                    reverse=False,  # More negative = better
                )
            else:
                scores.sort(
                    key=lambda s: s.grade_details.get(grade, {}).get(sort_by, 0),
                    reverse=True,
                )

        # Limit results
        scores = scores[:limit]

        return {
            "ok": True,
            "market": market,
            "step_size": step_size,
            "forward_days": forward_days,
            "sort_by": sort_by,
            "sort_grade": sort_grade,
            "total_stocks": len(scores),
            "ranking": [s.to_dict() for s in scores],
        }
    except Exception as exc:
        logger.error("stock_ranking_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
