import json
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.logging import get_logger

logger = get_logger(__name__)


def load_qlib_pkl(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, "rb") as f:
        try:
            return pickle.load(f)
        except Exception:
            logger.warning("Failed to load pickle artifact", path=str(path), exc_info=True)
            return None


def parse_detailed_ledger(run_dir: Path) -> dict[str, Any]:
    """
    Extracts real holdings and trades from positions_normal_1day.pkl
    """
    pos_path = run_dir / "artifacts" / "portfolio_analysis" / "positions_normal_1day.pkl"
    positions = load_qlib_pkl(pos_path)

    if not positions:
        return {"holdings": [], "trades": []}

    all_holdings = []
    all_trades = []

    sorted_dates = sorted(positions.keys())
    if not sorted_dates:
        return {"holdings": [], "trades": []}

    # Get latest holdings
    latest_date = sorted_dates[-1]
    latest_pos_obj = positions[latest_date]

    pos_dict = {}
    if hasattr(latest_pos_obj, "position"):
        pos_dict = latest_pos_obj.position
    elif isinstance(latest_pos_obj, dict) and "position" in latest_pos_obj:
        pos_dict = latest_pos_obj["position"]

    for ticker, info in pos_dict.items():
        if ticker in ["cash", "now_account_value"]:
            continue
        all_holdings.append(
            {
                "symbol": str(ticker),
                "quantity": float(info.get("amount", 0)),
                "price": float(info.get("price", 0)),
                "value": float(info.get("amount", 0) * info.get("price", 0)),
                "pnl": 0.0,
            }
        )

    # Extract trades with PnL tracking
    prev_pos = {}
    avg_entry_price: dict[str, float] = {}  # tracks avg buy price per symbol
    for dt in sorted_dates:
        curr_pos_obj = positions[dt]
        curr_dict = (
            curr_pos_obj.position
            if hasattr(curr_pos_obj, "position")
            else (curr_pos_obj.get("position", {}) if isinstance(curr_pos_obj, dict) else {})
        )

        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]

        for ticker, info in curr_dict.items():
            if ticker in ["cash", "now_account_value"]:
                continue

            curr_amt = info.get("amount", 0)
            prev_amt = prev_pos.get(ticker, 0)
            price = float(info.get("price", 0))

            if curr_amt > prev_amt:
                # Buy: update average entry price
                buy_qty = curr_amt - prev_amt
                existing_qty = prev_amt
                existing_avg = avg_entry_price.get(ticker, price)
                if existing_qty + buy_qty > 0:
                    avg_entry_price[ticker] = (
                        existing_avg * existing_qty + price * buy_qty
                    ) / (existing_qty + buy_qty)
                all_trades.append(
                    {
                        "date": date_str,
                        "symbol": str(ticker),
                        "type": "BUY",
                        "quantity": float(buy_qty),
                        "price": price,
                        "pnl": 0.0,
                        "status": "FILLED",
                    }
                )
            elif curr_amt < prev_amt:
                # Sell: compute PnL against average entry
                sell_qty = prev_amt - curr_amt
                entry_px = avg_entry_price.get(ticker, price)
                pnl = (price - entry_px) * sell_qty
                all_trades.append(
                    {
                        "date": date_str,
                        "symbol": str(ticker),
                        "type": "SELL",
                        "quantity": float(sell_qty),
                        "price": price,
                        "pnl": round(pnl, 2),
                        "status": "FILLED",
                    }
                )
                # If fully exited, remove entry price tracking
                if curr_amt <= 0:
                    avg_entry_price.pop(ticker, None)

        prev_pos = {
            t: info.get("amount", 0)
            for t, info in curr_dict.items()
            if t not in ["cash", "now_account_value"]
        }

    # Compute per-symbol PnL summary
    pnl_by_symbol: dict[str, float] = {}
    for trade in all_trades:
        if trade["type"] == "SELL" and trade["pnl"] != 0:
            sym = trade["symbol"]
            pnl_by_symbol[sym] = pnl_by_symbol.get(sym, 0) + trade["pnl"]
    pnl_summary = sorted(
        [{"symbol": k, "pnl": round(v, 2)} for k, v in pnl_by_symbol.items()],
        key=lambda x: x["pnl"],
        reverse=True,
    )

    return {
        "holdings": all_holdings,
        "trades": sorted(all_trades, key=lambda x: x["date"], reverse=True),
        "pnl_by_symbol": pnl_summary,
    }


def parse_profit_attribution(run_dir: Path) -> dict[str, Any]:
    """
    Extracts attribution data from report_normal_1day.pkl and indicators.
    """
    report_path = run_dir / "artifacts" / "portfolio_analysis" / "report_normal_1day.pkl"
    report = load_qlib_pkl(report_path)

    if report is None:
        return {"summary": "No backtest report artifact found.", "metrics": {}, "sectors": []}

    # Calculate real descriptive metrics
    metrics = {}
    if isinstance(report, pd.DataFrame):
        try:
            desc = report.describe()
            metrics = json.loads(desc.to_json())
        except Exception:
            logger.debug("Failed to compute report description metrics", exc_info=True)
            metrics = {}

    # Real attribution requires Factor analysis (out of scope for pure artifact parsing)
    # But we remove the hardcoded fake percentages and provide a more honest summary.
    return {
        "summary": "Attribution based on cumulative returns and risk-adjusted metrics.",
        "metrics": metrics,
        "sectors": [
            {"name": "Systematic Alpha", "contribution": "See alpha decomposition"},
            {"name": "Market Beta", "contribution": "See alpha decomposition"},
            {"name": "Slippage & Cost", "contribution": "See execution ledger"},
        ],
    }


def compute_alpha_decomposition(run_dir: Path) -> dict[str, Any]:
    """
    Decomposes strategy alpha into: selection, timing, sizing, cost, and beta.
    Uses report_normal (NAV curve) and positions_normal (holdings over time).
    """
    report_path = run_dir / "artifacts" / "portfolio_analysis" / "report_normal_1day.pkl"
    pos_path = run_dir / "artifacts" / "portfolio_analysis" / "positions_normal_1day.pkl"

    report = load_qlib_pkl(report_path)
    positions = load_qlib_pkl(pos_path)

    if report is None:
        return {"error": "No backtest report found", "components": []}

    components = []
    total_return = 0.0
    market_return = 0.0

    if isinstance(report, pd.DataFrame) and "account" in report.columns:
        account = report["account"].dropna()
        if len(account) < 2:
            return {"error": "Insufficient data", "components": []}

        total_return = (account.iloc[-1] / account.iloc[0]) - 1

        # --- Beta contribution ---
        bench_col = None
        for col in ["bench_qqq", "bench_hs300", "bench"]:
            if col in report.columns and report[col].notna().any():
                bench_col = col
                break

        beta_contribution = 0.0
        if bench_col:
            bench_ret = report[bench_col].dropna()
            if len(bench_ret) > 1:
                port_daily = account.pct_change().dropna()
                mkt_daily = bench_ret.iloc[:len(port_daily)]
                if len(mkt_daily) == len(port_daily) and mkt_daily.std() > 0:
                    aligned = pd.DataFrame({"port": port_daily.values, "mkt": mkt_daily.values}).dropna()
                    if len(aligned) > 10:
                        beta = aligned["port"].cov(aligned["mkt"]) / aligned["mkt"].var()
                        market_return = (1 + mkt_daily).prod() - 1
                        beta_contribution = beta * market_return

        # --- Selection alpha ---
        selection_alpha = total_return - beta_contribution

        # --- Cost drag ---
        cost_drag = 0.0
        if "turnover" in report.columns:
            avg_turnover = report["turnover"].dropna().mean()
            cost_drag = -avg_turnover * 0.001 * len(account)

        # --- Sizing alpha ---
        sizing_alpha = 0.0
        if positions:
            sorted_dates = sorted(positions.keys())
            if len(sorted_dates) > 1:
                eq_returns = []
                actual_returns = []
                for i in range(1, len(sorted_dates)):
                    dt = sorted_dates[i]
                    prev_dt = sorted_dates[i - 1]
                    pos_obj = positions[dt]
                    prev_obj = positions[prev_dt]
                    curr_dict = pos_obj.position if hasattr(pos_obj, "position") else (pos_obj.get("position", {}) if isinstance(pos_obj, dict) else {})
                    prev_dict = prev_obj.position if hasattr(prev_obj, "position") else (prev_obj.get("position", {}) if isinstance(prev_obj, dict) else {})

                    held_returns = []
                    weight_returns = []
                    for ticker in curr_dict:
                        if ticker in ["cash", "now_account_value"]:
                            continue
                        curr_px = curr_dict[ticker].get("price", 0)
                        prev_px = prev_dict.get(ticker, {}).get("price", 0) if isinstance(prev_dict.get(ticker), dict) else 0
                        weight = curr_dict[ticker].get("amount", 0) * curr_px
                        if prev_px > 0 and curr_px > 0:
                            ret = (curr_px / prev_px) - 1
                            held_returns.append(ret)
                            weight_returns.append((ret, weight))

                    if held_returns:
                        eq_returns.append(sum(held_returns) / len(held_returns))
                        total_w = sum(w for _, w in weight_returns)
                        if total_w > 0:
                            actual_returns.append(sum(r * w / total_w for r, w in weight_returns))
                        else:
                            actual_returns.append(0)

                if eq_returns and actual_returns:
                    eq_cum = 1.0
                    actual_cum = 1.0
                    for eq_r, act_r in zip(eq_returns, actual_returns):
                        eq_cum *= (1 + eq_r)
                        actual_cum *= (1 + act_r)
                    sizing_alpha = actual_cum - eq_cum

        # --- Timing alpha (residual) ---
        timing_alpha = total_return - selection_alpha - beta_contribution - sizing_alpha - cost_drag

        components = [
            {"name": "Selection", "value": round(selection_alpha * 100, 2), "description": "Stock picking skill vs market"},
            {"name": "Timing", "value": round(timing_alpha * 100, 2), "description": "Entry/exit timing quality"},
            {"name": "Sizing", "value": round(sizing_alpha * 100, 2), "description": "Position weight optimization"},
            {"name": "Cost", "value": round(cost_drag * 100, 2), "description": "Transaction cost drag"},
            {"name": "Beta", "value": round(beta_contribution * 100, 2), "description": "Market exposure contribution"},
        ]

    return {
        "total_return": round(total_return * 100, 2),
        "market_return": round(market_return * 100, 2),
        "components": components,
    }
