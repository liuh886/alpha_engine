import datetime
import json
import os
import random

ARTIFACTS_DIR = "artifacts"


def generate_stocks():
    os.makedirs(f"{ARTIFACTS_DIR}/stocks", exist_ok=True)
    symbols = ["AAPL", "NVDA", "000300.SH", "600519.SH"]

    for sym in symbols:
        # Generate random OHLCV
        ohlcv = []
        base_price = (
            150.0
            if sym == "AAPL"
            else 800.0
            if sym == "NVDA"
            else 3500.0
            if sym == "000300.SH"
            else 1800.0
        )
        now = datetime.datetime.now()

        # Backtrack business days only
        days_generated = 0
        current_date = now - datetime.timedelta(days=150)
        while days_generated < 100:
            current_date += datetime.timedelta(days=1)
            if current_date.weekday() >= 5:  # Skip Sat/Sun (5/6)
                continue

            date_str = current_date.strftime("%Y-%m-%d")
            base_price += random.uniform(-10, 10)
            open_p = base_price + random.uniform(-2, 2)
            high_p = max(open_p, base_price) + random.uniform(0, 5)
            low_p = min(open_p, base_price) - random.uniform(0, 5)
            close_p = base_price
            ohlcv.append(
                {
                    "time": date_str,
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "close": round(close_p, 2),
                }
            )

        data = {
            "ok": True,
            "symbol": sym,
            "confidence": random.uniform(0.6, 0.95),
            "trend": random.uniform(-0.05, 0.1),
            "guardrails": [
                {"label": "Volatility Regime", "status": "SAFE", "color": "text-emerald-500"},
                {"label": "Liquidity Check", "status": "PASS", "color": "text-emerald-500"},
                {"label": "Tail Risk", "status": "ELEVATED", "color": "text-yellow-500"},
            ],
            "ohlcv": ohlcv,
        }
        with open(f"{ARTIFACTS_DIR}/stocks/{sym}.json", "w") as f:
            json.dump(data, f)


def generate_arenas():
    arenas = {
        "arenas": [
            {"id": "arena-us-main", "name": "US Main Arena", "market": "us"},
            {"id": "arena-cn-main", "name": "CN Main Arena", "market": "cn"},
        ]
    }
    with open(f"{ARTIFACTS_DIR}/arenas.json", "w") as f:
        json.dump(arenas, f)

    # US Leaderboard
    us_lb = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "leaderboard": [
            {
                "rank": 1,
                "participant_name": "LGBM Alpha Spec 1",
                "nav": 1.45,
                "daily_return": 0.012,
                "drawdown": 0.05,
                "run_id": "LGBM_v1",
                "edge_explanation": "Maintains superior risk-adjusted returns during high-volatility regimes due to deep momentum feature reliance.",
            },
            {
                "rank": 2,
                "participant_name": "Transformer Q-Learn",
                "nav": 1.32,
                "daily_return": -0.005,
                "drawdown": 0.08,
                "run_id": "TF_v1",
            },
        ],
    }
    with open(f"{ARTIFACTS_DIR}/arena_leaderboard_arena-us-main.json", "w") as f:
        json.dump(us_lb, f)

    cn_lb = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "leaderboard": [
            {
                "rank": 1,
                "participant_name": "CN XGBoost Base",
                "nav": 1.15,
                "daily_return": 0.008,
                "drawdown": 0.03,
                "run_id": "XGB_v1",
                "edge_explanation": "Exhibits exceptional Alpha capture during index rebalancing events, leveraging unique sector rotation factors.",
            }
        ],
    }
    with open(f"{ARTIFACTS_DIR}/arena_leaderboard_arena-cn-main.json", "w") as f:
        json.dump(cn_lb, f)


def generate_data_status():
    status = {
        "data": {
            "latest_calendar_day": datetime.datetime.now().strftime("%Y-%m-%d"),
            "latest_snapshot_id": "snap-2024-05-12-v1",
            "dashboard_db_generated_at": datetime.datetime.now().isoformat(),
            "quality_warnings": [],
            "quality_warnings_count": 0,
        }
    }
    with open(f"{ARTIFACTS_DIR}/data_status.json", "w") as f:
        json.dump(status, f)

    quality = {
        "quality": {
            "summary": {
                "snapshot_id": "snap-2024-05-12-v1",
                "markets": {
                    "us": {
                        "instruments": 8500,
                        "instrument_end_max": "2024-05-12",
                        "stale_instruments": 12,
                        "csv_parse_errors": 0,
                    },
                    "cn": {
                        "instruments": 5000,
                        "instrument_end_max": "2024-05-12",
                        "stale_instruments": 5,
                        "csv_parse_errors": 0,
                    },
                },
                "warnings": [],
            }
        }
    }
    with open(f"{ARTIFACTS_DIR}/data_quality.json", "w") as f:
        json.dump(quality, f)


def generate_models():
    models = {
        "versions": [
            {
                "id": "model_us_1",
                "tag": "US Transformer Base",
                "name": "US Transformer Base",
                "market": "us",
                "model_type": "transformer",
                "run_id": "LGBM_v1",
                "created_at": "2024-05-01",
                "description": "RECOMMENDED",
                "metrics_json": {"annualized_return": 0.25, "sharpe": 1.8},
                "params_json": {"learning_rate": 0.01, "max_depth": 6, "benchmark": "SPY"},
            },
            {
                "id": "model_cn_1",
                "tag": "CN XGBoost Base",
                "name": "CN XGBoost Base (CSI 300)",
                "market": "cn",
                "model_type": "xgboost",
                "run_id": "XGB_v1",
                "created_at": "2024-05-05",
                "description": "STAGING",
                "metrics_json": {"annualized_return": 0.18, "sharpe": 1.2},
                "params_json": {"trees": 500, "depth": 4, "benchmark": "000300.SH"},
            },
        ]
    }
    with open(f"{ARTIFACTS_DIR}/models.json", "w") as f:
        json.dump(models, f)


def generate_reports():
    reports = {
        "reports": [
            {
                "id": "rep_101",
                "type": "arena_daily",
                "ref_id": "arena-us-main",
                "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "paths": {"html": "/artifacts/reports/arena_us_latest.html"},
                "meta": {"market": "us"},
            },
            {
                "id": "rep_102",
                "type": "backtest",
                "ref_id": "LGBM_v1",
                "date": "2024-05-01",
                "paths": {"html": "/artifacts/reports/backtest_lgbm_v1.html"},
                "meta": {"market": "us", "model_type": "lgbm"},
            },
        ]
    }
    with open(f"{ARTIFACTS_DIR}/reports.json", "w") as f:
        json.dump(reports, f)

    os.makedirs(f"{ARTIFACTS_DIR}/reports", exist_ok=True)
    with open(f"{ARTIFACTS_DIR}/reports/arena_us_latest.html", "w") as f:
        f.write("<html><body><h1>Arena Daily Report US</h1></body></html>")
    with open(f"{ARTIFACTS_DIR}/reports/backtest_lgbm_v1.html", "w") as f:
        f.write("<html><body><h1>Backtest Report LGBM_v1</h1></body></html>")


def generate_dashboard_db():
    os.makedirs(f"{ARTIFACTS_DIR}/dashboard", exist_ok=True)

    # Generate ~100 trading days
    dates = []
    now = datetime.datetime.now()
    current_date = now - datetime.timedelta(days=150)
    for _ in range(150):
        current_date += datetime.timedelta(days=1)
        if current_date.weekday() < 5:
            dates.append(current_date.strftime("%Y-%m-%d"))
    dates = dates[-100:]

    def make_report(base_nav, vol):
        nav = base_nav
        report = []
        for i, dt in enumerate(dates):
            ret = random.gauss(0.0005, vol)
            nav *= 1 + ret
            report.append(
                {
                    "date": dt,
                    "account": nav,
                    "return": ret,
                    "turnover": random.uniform(0.01, 0.05),
                    "cost": 0.0001,
                }
            )
        return report

    def make_benchmark(dates, base_nav, vol, drift):
        nav = base_nav
        b_data = {}
        for dt in dates:
            ret = random.gauss(drift, vol)
            nav *= 1 + ret
            b_data[dt] = ret
        return b_data

    bench_spy = make_benchmark(dates, 1.0, 0.010, 0.0003)
    bench_hs300 = make_benchmark(dates, 1.0, 0.012, 0.0001)

    db = {
        "ok": True,
        "name_map": {"AAPL": "Apple", "000300.SH": "CSI 300 Index"},
        "models": [
            {
                "id": "model_us_1",
                "name": "US Transformer Base",
                "market": "us",
                "params": {"benchmark": "SPY"},
                "data": {
                    "report_normal": make_report(1.0, 0.012),
                    "positions_normal": [],
                    "benchmarks": {"SPY": bench_spy},
                    "indicators": {"information_ratio": 1.25},
                    "feature_importance": {
                        "Momentum_20d": 0.35,
                        "RSI_14": 0.22,
                        "Volatility_30d": 0.18,
                        "MACD_Signal": 0.15,
                        "Volume_Trend": 0.10,
                    },
                },
            },
            {
                "id": "model_cn_1",
                "name": "CN XGBoost Base (CSI 300)",
                "market": "cn",
                "params": {"benchmark": "000300.SH"},
                "data": {
                    "report_normal": make_report(1.0, 0.015),
                    "positions_normal": [],
                    "benchmarks": {"000300.SH": bench_hs300, "000300": bench_hs300},
                    "indicators": {"information_ratio": 1.45},
                    "feature_importance": {
                        "Price_Reversion_5d": 0.40,
                        "Liquidity_Shock": 0.25,
                        "Momentum_10d": 0.15,
                        "Beta_Sensitivity": 0.12,
                        "Sector_Rotation": 0.08,
                    },
                },
            },
        ],
    }

    with open(f"{ARTIFACTS_DIR}/dashboard/dashboard_db.json", "w") as f:
        json.dump(db, f)


if __name__ == "__main__":
    generate_stocks()
    generate_arenas()
    generate_data_status()
    generate_models()
    generate_reports()
    generate_dashboard_db()
    print("Successfully generated static artifacts.")
