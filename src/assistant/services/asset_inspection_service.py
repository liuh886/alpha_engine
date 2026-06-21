from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any


class AssetInspectionService:
    def __init__(self, *, project_root: str | Path, model_index: Any | None = None):
        self._project_root = Path(project_root)
        self._model_index = model_index

    def inspect(self, symbol: str) -> dict:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")

        market, clean_symbol = self.infer_market_symbol(symbol)
        ohlcv = self._load_ohlcv(market=market, clean_symbol=clean_symbol)
        if not ohlcv:
            raise ValueError(f"symbol {symbol} not found in {market} data")

        confidence, trend = self._load_recommended_prediction(clean_symbol)
        return {
            "ok": True,
            "symbol": symbol,
            "market": market,
            "ohlcv": ohlcv,
            "confidence": confidence,
            "trend": trend,
            "guardrails": self.calculate_guardrails(ohlcv),
        }

    @staticmethod
    def infer_market_symbol(symbol: str) -> tuple[str, str]:
        symbol = str(symbol or "").strip().upper()

        # Explicit suffix
        if symbol.endswith(".SH") or symbol.endswith(".SZ"):
            return "cn", symbol.split(".")[0]

        # Chinese A-share numeric codes (no suffix):
        # 600xxx, 601xxx, 603xxx, 605xxx → Shanghai
        # 000xxx, 001xxx, 002xxx, 003xxx → Shenzhen
        # 300xxx, 301xxx → ChiNext (Shenzhen)
        # 688xxx → STAR Market (Shanghai)
        if symbol.isdigit() and len(symbol) == 6:
            prefix = symbol[:3]
            if prefix in ("600", "601", "603", "605", "688"):
                return "cn", symbol
            if prefix in ("000", "001", "002", "003", "300", "301"):
                return "cn", symbol

        return "us", symbol

    @staticmethod
    def format_ohlcv_frame(df: Any, clean_symbol: str) -> list[dict]:
        if df.empty:
            return []

        import math

        symbol_df = df.xs(clean_symbol, level="instrument")
        rows = []
        for dt, row in symbol_df.iterrows():
            o = float(row["$open"]) if not math.isnan(row["$open"]) else None
            h = float(row["$high"]) if not math.isnan(row["$high"]) else None
            low = float(row["$low"]) if not math.isnan(row["$low"]) else None
            c = float(row["$close"]) if not math.isnan(row["$close"]) else None
            v = float(row["$volume"]) if not math.isnan(row["$volume"]) else None

            # Skip rows with NaN values (incomplete data)
            if any(x is None for x in [o, h, low, c, v]):
                continue

            rows.append(
                {
                    "time": dt.strftime("%Y-%m-%d"),
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "value": v,
                }
            )
        return rows

    @staticmethod
    def calculate_guardrails(ohlcv: list[dict]) -> list[dict]:
        vol_status, vol_color = "STABLE", "text-blue-500"
        liq_status, liq_color = "PASS", "text-green-500"
        circuit_status, circuit_color = "NONE", "text-muted-foreground"

        prices = [float(d["close"]) for d in ohlcv if d.get("close") is not None]
        volumes = [float(d.get("value") or 0.0) for d in ohlcv]

        if len(prices) > 10:
            returns = []
            for prev, curr in zip(prices, prices[1:]):
                if prev > 0 and curr > 0:
                    returns.append(math.log(curr / prev))

            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((ret - mean_ret) ** 2 for ret in returns) / len(returns)
                ann_vol = math.sqrt(variance) * math.sqrt(252)
                if ann_vol > 0.6:
                    vol_status, vol_color = "EXTREME", "text-red-500"
                elif ann_vol > 0.4:
                    vol_status, vol_color = "HIGH", "text-orange-500"

            last_change = abs(prices[-1] / prices[-2] - 1) if prices[-2] else 0.0
            if last_change > 0.07:
                circuit_status, circuit_color = "ELEVATED", "text-red-500"

        if prices and volumes and len(prices) == len(volumes):
            avg_value = sum(v * p for v, p in zip(volumes, prices)) / len(prices)
            if avg_value < 1_000_000:
                liq_status, liq_color = "LOW", "text-yellow-500"

        return [
            {"label": "Liquidity", "status": liq_status, "color": liq_color},
            {"label": "Volatility", "status": vol_status, "color": vol_color},
            {"label": "Circuit Risk", "status": circuit_status, "color": circuit_color},
            {"label": "Data Quality", "status": "REAL", "color": "text-green-500"},
        ]

    def _load_ohlcv(self, *, market: str, clean_symbol: str) -> list[dict]:
        import pandas as pd
        from qlib.data import D

        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        cfg = build_qlib_init_cfg(
            {}, market=market, provider_uri_default=str(self._project_root / "data" / "watchlist")
        )
        safe_qlib_init(cfg)

        try:
            df = D.features(
                [clean_symbol],
                ["$open", "$high", "$low", "$close", "$volume"],
                start_time=pd.Timestamp.now() - pd.Timedelta(days=1000),
            )
        except Exception:
            return []

        return self.format_ohlcv_frame(df, clean_symbol)

    def _load_recommended_prediction(self, clean_symbol: str) -> tuple[float | None, float | None]:
        try:
            # Strategy 1: Look up recommended run_id from model index
            run_id = self._get_recommended_run_id()
            pred_path = self._find_prediction_path(run_id) if run_id else None

            # Strategy 2: Fallback to latest pred.pkl if no recommended model
            if not pred_path:
                pred_path = self._find_latest_prediction_path()

            if not pred_path:
                return None, None

            with pred_path.open("rb") as f:
                pred_df = pickle.load(f)

            if not isinstance(pred_df, type(None)) and hasattr(pred_df.index, 'get_level_values'):
                instruments = pred_df.index.get_level_values("instrument")
            else:
                return None, None

            if clean_symbol not in instruments:
                return None, None

            ticker_pred = pred_df.xs(clean_symbol, level="instrument")
            if ticker_pred.empty:
                return None, None

            latest_score = float(ticker_pred.iloc[-1].iloc[0])
            confidence = max(0.1, min(0.95, 0.5 + latest_score))
            trend = None
            if len(ticker_pred) > 1:
                trend = float(ticker_pred.iloc[-1].iloc[0] - ticker_pred.iloc[-2].iloc[0])
            return confidence, trend
        except Exception:
            return None, None

    def _get_recommended_run_id(self) -> str | None:
        if self._model_index is None:
            return None
        try:
            with self._model_index._connect() as conn:
                row = conn.execute(
                    "SELECT run_id FROM model_versions WHERE description LIKE '%RECOMMENDED%' LIMIT 1"
                ).fetchone()
            return str(row[0]) if row else None
        except Exception:
            return None

    def _find_prediction_path(self, run_id: str) -> Path | None:
        from src.common.paths import MLRUNS_DIR

        for mlruns_dir in [
            MLRUNS_DIR,
            self._project_root / "mlruns",
            self._project_root / "artifacts" / "mlruns",
        ]:
            if not mlruns_dir.exists():
                continue
            for exp_dir in mlruns_dir.iterdir():
                if not exp_dir.is_dir():
                    continue
                pred_path = exp_dir / run_id / "artifacts" / "pred.pkl"
                if pred_path.exists():
                    return pred_path
        return None

    def _find_latest_prediction_path(self) -> Path | None:
        """Fallback: find the most recently modified pred.pkl across all mlruns."""
        from src.common.paths import MLRUNS_DIR

        best_path = None
        best_mtime = 0.0
        for mlruns_dir in [
            MLRUNS_DIR,
            self._project_root / "mlruns",
            self._project_root / "artifacts" / "mlruns",
        ]:
            if not mlruns_dir.exists():
                continue
            for pred_file in mlruns_dir.rglob("pred.pkl"):
                mt = pred_file.stat().st_mtime
                if mt > best_mtime:
                    best_mtime = mt
                    best_path = pred_file
            # Also check for 'pred' without extension (Qlib output)
            for pred_file in mlruns_dir.rglob("pred"):
                if pred_file.is_file() and pred_file.suffix == "":
                    mt = pred_file.stat().st_mtime
                    if mt > best_mtime:
                        best_mtime = mt
                        best_path = pred_file
        return best_path
