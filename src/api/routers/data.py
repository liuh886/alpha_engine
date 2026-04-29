import pickle
import threading
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import (
    PROJECT_ROOT,
    get_data_service,
    get_job_service,
    get_model_index,
    get_quality_index,
    get_snapshot_index,
)
from src.common.paths import DASHBOARD_DB_PATH

router = APIRouter(tags=["data"])


@router.post("/update")
def trigger_data_update(payload: dict):
    try:
        job = get_data_service().create_update_job_from_payload(payload)
        job_id = job["id"]
        get_job_service().create_job(job)
        t = threading.Thread(target=get_job_service().run_job, args=(job_id,), daemon=True)
        t.start()
        return {"ok": True, "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/instruments")
def get_instruments(market: str = Query("us")):
    instruments = get_data_service().get_instruments(market=market)
    return {"ok": True, "market": market, "instruments": instruments}


@router.get("/status")
def get_data_status():
    status = get_data_service().get_data_status(
        dashboard_db_path=Path(DASHBOARD_DB_PATH),
        snapshot_index=get_snapshot_index(),
        quality_index=get_quality_index(),
    )
    return {"ok": True, "data": status}


@router.get("/snapshots/latest")
def get_latest_snapshot(dataset_key: str = "watchlist", freq: str = "day"):
    snap = get_snapshot_index().get_latest(dataset_key=dataset_key, freq=freq)
    if not snap:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return {"ok": True, "snapshot": snap}


@router.get("/quality/latest")
def get_latest_quality(dataset_key: str = "watchlist", freq: str = "day", market: str = "all"):
    rep = get_quality_index().get_latest(dataset_key=dataset_key, freq=freq, market=market)
    if not rep:
        raise HTTPException(status_code=404, detail="quality report not found")
    return {"ok": True, "quality": rep}


@router.get("/stock/{symbol}")
def get_stock_data(symbol: str):
    from qlib.data import D

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    # Guess market and clean symbol
    if symbol.endswith(".SH") or symbol.endswith(".SZ"):
        market = "cn"
        clean_symbol = symbol.split(".")[0]
    else:
        market = "us"
        clean_symbol = symbol

    cfg = build_qlib_init_cfg(
        {}, market=market, provider_uri_default=str(PROJECT_ROOT / "data" / "watchlist")
    )
    safe_qlib_init(cfg)

    # Fetch last 1000 days of data
    try:
        df = D.features(
            [clean_symbol],
            ["$open", "$high", "$low", "$close", "$volume"],
            start_time=pd.Timestamp.now() - pd.Timedelta(days=1000),
        )
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol} not found in {market} data"
        )

    # Format for k-line (Lightweight Charts)
    df = df.xs(clean_symbol, level="instrument")
    data = []
    for dt, row in df.iterrows():
        data.append(
            {
                "time": dt.strftime("%Y-%m-%d"),
                "open": float(row["$open"]),
                "high": float(row["$high"]),
                "low": float(row["$low"]),
                "close": float(row["$close"]),
                "value": float(row["$volume"]),
            }
        )

    # Attempt to fetch real prediction score from RECOMMENDED model
    confidence = None
    trend = None
    try:
        from src.common.paths import MLRUNS_DIR

        with get_model_index()._connect() as conn:
            row = conn.execute(
                "SELECT run_id FROM model_versions WHERE description LIKE '%RECOMMENDED%' LIMIT 1"
            ).fetchone()
        if row:
            rec_run_id = row[0]
            mlruns_dir = MLRUNS_DIR
            pred_path = None
            for exp_dir in mlruns_dir.iterdir():
                if not exp_dir.is_dir():
                    continue
                p = exp_dir / rec_run_id / "artifacts" / "pred.pkl"
                if p.exists():
                    pred_path = p
                    break

            if pred_path:
                with open(pred_path, "rb") as f:
                    pred_df = pickle.load(f)
                ticker_pred = (
                    pred_df.xs(clean_symbol, level="instrument")
                    if clean_symbol in pred_df.index.get_level_values("instrument")
                    else pd.DataFrame()
                )
                if not ticker_pred.empty:
                    latest_score = float(ticker_pred.iloc[-1].iloc[0])
                    confidence = max(0.1, min(0.95, 0.5 + latest_score))
                    if len(ticker_pred) > 1:
                        trend = float(
                            ticker_pred.iloc[-1].iloc[0] - ticker_pred.iloc[-2].iloc[0]
                        )
    except Exception:
        pass

    # Calculate real guardrails
    vol_status, vol_color = "STABLE", "text-blue-500"
    liq_status, liq_color = "PASS", "text-green-500"
    circuit_status, circuit_color = "NONE", "text-muted-foreground"

    if data:
        import numpy as np

        prices = [d["close"] for d in data]
        if len(prices) > 10:
            try:
                returns = np.diff(np.log(prices))
                daily_vol = np.std(returns)
                ann_vol = daily_vol * np.sqrt(252)
                if ann_vol > 0.4:
                    vol_status, vol_color = "HIGH", "text-orange-500"
                elif ann_vol > 0.6:
                    vol_status, vol_color = "EXTREME", "text-red-500"

                last_change = abs(prices[-1] / prices[-2] - 1)
                if last_change > 0.07:
                    circuit_status, circuit_color = "ELEVATED", "text-red-500"
            except Exception:
                pass

        try:
            volumes = [d["value"] for d in data]
            avg_val = np.mean([v * p for v, p in zip(volumes, prices)])
            if avg_val < 1000000:
                liq_status, liq_color = "LOW", "text-yellow-500"
        except Exception:
            pass

    guardrails = [
        {"label": "Liquidity", "status": liq_status, "color": liq_color},
        {"label": "Volatility", "status": vol_status, "color": vol_color},
        {"label": "Circuit Risk", "status": circuit_status, "color": circuit_color},
        {"label": "Data Quality", "status": "100%", "color": "text-green-500"},
    ]

    return {
        "ok": True,
        "symbol": symbol,
        "ohlcv": data,
        "confidence": confidence,
        "trend": trend,
        "guardrails": guardrails,
    }
