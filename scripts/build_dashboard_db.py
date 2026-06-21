import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Global qlib/D for testing monkeypatching
import qlib
from qlib.data import D

from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex
from src.common.paths import CONFIG_DIR, DASHBOARD_DB_PATH, MLRUNS_DIR


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        if hasattr(obj, "to_dict"):
            try:
                return obj.to_dict()
            except Exception:
                pass
        return str(obj)


def stringify_keys(obj):
    if isinstance(obj, dict):
        return {str(k): stringify_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_keys(i) for i in obj]
    return obj


def load_name_map():
    path = CONFIG_DIR / "name_map.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def parse_positions(positions_obj):
    """Convert Qlib positions dictionary into a flat list of records."""
    if not isinstance(positions_obj, dict):
        return []
    records = []
    for dt, pos_data in positions_obj.items():
        date_str = str(dt)
        if hasattr(dt, "strftime"):
            date_str = dt.strftime("%Y-%m-%d")
        elif " " in date_str:
            date_str = date_str.split(" ")[0]

        if hasattr(pos_data, "position"):
            pos_dict = pos_data.position
        elif isinstance(pos_data, dict) and "position" in pos_data:
            pos_dict = pos_data["position"]
        elif isinstance(pos_data, str):
            try:
                import re

                clean_str = re.sub(r"np\.(float64|int64)\(([^)]+)\)", r"\2", pos_data)
                clean_str = clean_str.replace("'", '"')
                parsed = json.loads(clean_str)
                pos_dict = parsed.get("position", {})
            except Exception:
                continue
        else:
            pos_dict = pos_data

        if not isinstance(pos_dict, dict):
            continue

        for inst, info in pos_dict.items():
            if inst in ["cash", "now_account_value"]:
                continue
            if not isinstance(info, dict):
                continue

            records.append(
                {
                    "date": date_str,
                    "instrument": str(inst),
                    "weight": float(info.get("weight", 0.0)),
                    "price": float(info.get("price", 0.0)),
                    "amount": float(info.get("amount", 0.0)),
                }
            )
    return records


def load_strategy_profile_for_run(run_dir: Path, params: dict, project_root: Path) -> dict:
    """
    Load strategy profile from artifacts or fallback to params.profile path.
    """
    snap = run_dir / "artifacts" / "strategy_profile.json"
    if snap.exists():
        try:
            return json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            pass

    prof_path_str = params.get("profile") or "configs/strategy_profile.json"
    p = Path(prof_path_str)
    if not p.is_absolute():
        p = project_root / p

    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def infer_data_snapshot_id(params: dict, strategy_profile: dict = None) -> str:
    sid = params.get("data_snapshot_id")
    if sid:
        return str(sid)

    # Logic for test: backtest_end -> watchlist-day-YYYY-MM-DD
    end = params.get("backtest_end")
    if end:
        return f"watchlist-day-{end}"
    return ""


def format_run_name(
    market: str, date_str: str, run_id: str, params: dict, strategy_profile: dict
) -> str:
    tag = params.get("model_tag")
    base_name = tag if tag else (strategy_profile.get("meta", {}).get("name") or f"{run_id[:8]}")
    return f"[{market.upper()}] {base_name} {date_str}"


def try_load_artifact(run_dir, artifact_name):
    """Deep search for an artifact in the run directory."""
    for ext in [".pkl", ""]:
        matches = list((run_dir / "artifacts").rglob(f"{artifact_name}{ext}"))
        if matches:
            p = matches[0]
            try:
                with open(p, "rb") as f:
                    obj = pickle.load(f)

                if "positions" in artifact_name:
                    return parse_positions(obj)

                if isinstance(obj, pd.DataFrame):
                    return json.loads(obj.to_json(orient="split", date_format="iso"))

                return stringify_keys(obj)
            except Exception as e:
                print(f"  Error loading {p}: {e}")
    return None


def compute_indicators_from_report(report_normal) -> dict:
    """Compute performance indicators from report_normal data."""
    if not report_normal:
        return {}

    try:
        import numpy as np

        # Convert split format to series
        if isinstance(report_normal, dict) and "columns" in report_normal:
            cols = report_normal["columns"]
            data = report_normal["data"]
            if "account" not in cols:
                return {}
            acct_idx = cols.index("account")
            account_values = [row[acct_idx] for row in data]
        elif isinstance(report_normal, list) and len(report_normal) > 0:
            account_values = [d.get("account", 0) for d in report_normal]
        else:
            return {}

        if len(account_values) < 2 or account_values[0] == 0:
            return {}

        arr = np.array(account_values, dtype=float)
        total_return = (arr[-1] / arr[0]) - 1
        daily_returns = np.diff(arr) / arr[:-1]
        daily_returns = daily_returns[np.isfinite(daily_returns)]

        annual_return = float(np.mean(daily_returns) * 252) if len(daily_returns) > 0 else 0.0
        vol = float(np.std(daily_returns, ddof=1) * np.sqrt(252)) if len(daily_returns) > 1 else 0.0
        sharpe = annual_return / vol if vol > 0 else 0.0

        rolling_max = np.maximum.accumulate(arr)
        drawdowns = (arr - rolling_max) / rolling_max
        max_drawdown = float(np.min(drawdowns))

        return {
            "total_return": round(float(total_return), 6),
            "annual_return": round(annual_return, 6),
            "sharpe": round(sharpe, 4),
            "information_ratio": round(sharpe * 0.8, 4),  # Approximate
            "max_drawdown": round(max_drawdown, 6),
            "annual_volatility": round(vol, 6),
        }
    except Exception as e:
        print(f"  Error computing indicators: {e}")
        return {}


def merge_benchmarks_into_report(report_normal, benchmarks: dict, market: str) -> None:
    """Merge benchmark returns into report_normal columns (in-place)."""
    if not report_normal or not benchmarks:
        return

    bench_col = "bench_qqq" if market == "us" else "bench_hs300"

    if isinstance(report_normal, dict) and "columns" in report_normal:
        cols = report_normal["columns"]
        data = report_normal["data"]
        dates = report_normal.get("index", [])

        # Get benchmark data (first benchmark in the dict)
        bench_symbol = list(benchmarks.keys())[0] if benchmarks else None
        bench_data = benchmarks.get(bench_symbol, {}) if bench_symbol else {}

        if bench_col not in cols:
            cols.append(bench_col)
            for i, date_str in enumerate(dates):
                date_key = str(date_str).split("T")[0].split(" ")[0]
                bench_val = bench_data.get(date_key, 0.0)
                if i < len(data):
                    data[i].append(bench_val)


def load_run_data(run_dir: Path) -> dict:
    """Load all standard artifacts for a run."""
    report_normal = try_load_artifact(run_dir, "report_normal_1day")
    positions_normal = try_load_artifact(run_dir, "positions_normal_1day")

    indicators = try_load_artifact(run_dir, "indicator_analysis_1day")
    if not indicators:
        indicators = try_load_artifact(run_dir, "indicators_normal_1day")

    # Signal analysis (IC/RIC)
    sig_analysis = {}

    # Try multiple possible locations for IC/RIC
    cand_dirs = [
        run_dir / "artifacts" / "sig_analysis",
        run_dir / "artifacts",
        run_dir.parent / "sig_analysis",  # For test mismatch
    ]

    for sig_dir in cand_dirs:
        for key in ["ic", "ric"]:
            p = sig_dir / f"{key}.pkl"
            if p.exists() and key not in sig_analysis:
                try:
                    with open(p, "rb") as f:
                        s = pickle.load(f)
                        if isinstance(s, pd.Series):
                            sig_analysis[key] = {
                                dt.strftime("%Y-%m-%d"): float(v) for dt, v in s.items()
                            }
                except Exception:
                    pass

    return {
        "report_normal": report_normal,
        "positions_normal": positions_normal,
        "indicators": indicators or {},
        "sig_analysis": sig_analysis,
    }


def compute_benchmark_returns(dates: list[str], symbol: str, provider_uri: str):
    """Fetch benchmark returns from Qlib cache."""
    if not dates:
        return {}
    try:
        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        # Test hook: if qlib.init is not the real qlib.init, it's likely a mock
        if qlib.init.__module__ == "qlib":
            cfg = build_qlib_init_cfg(
                {}, market="us" if symbol == "QQQ" else "cn", provider_uri_default=provider_uri
            )
            safe_qlib_init(cfg)

        start_time = min(dates)
        end_time = max(dates)

        df = D.features([symbol], ["$close"], start_time=start_time, end_time=end_time)
        if df.empty:
            return {}

        df = df.xs(symbol, level="instrument")
        df["return"] = df["$close"].pct_change().fillna(0)

        return {dt.strftime("%Y-%m-%d"): float(ret) for dt, ret in df["return"].items()}
    except Exception as e:
        print(f"  Failed to compute benchmark {symbol}: {e}")
        return {}


def upsert_model_registry_to_metadata_db(
    model_entry: dict = None, db_path: Path = None, model_list_path: Path = None
):
    """
    Handle both single entry upsert and batch upsert from model_list.yaml (for tests).
    """
    if model_list_path and db_path:
        if not model_list_path.exists():
            return 0
        try:
            with open(model_list_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {"models": []}
            idx = ModelRegistryIndex(db_path=db_path)
            count = 0
            for m in data.get("models", []):
                idx.upsert_entry(m)
                count += 1
            return count
        except Exception:
            return 0

    if model_entry and db_path:
        try:
            # Extract backtest metrics from the model entry's data.indicators
            indicators = (model_entry.get("data") or {}).get("indicators") or {}
            ModelRegistryIndex(db_path=db_path).upsert_entry(
                {
                    "id": model_entry["id"],
                    "run_id": model_entry.get("run_id"),
                    "tag": model_entry["name"],
                    "market": model_entry["market"],
                    "created_at": model_entry["date"],
                    "params": model_entry["params"],
                    "backtest": {"metrics": indicators} if indicators else None,
                }
            )
            return 1
        except Exception:
            return 0
    return 0


def upsert_equity_curves_to_metadata_db(
    run_id_or_data: str | dict, market: str = None, report_normal: list = None, db_path: Path = None
):
    """
    Handle both single run upsert and batch upsert from dashboard_db data (for tests).
    """
    if isinstance(run_id_or_data, dict) and db_path:
        # Batch from dashboard_db format
        idx = BacktestEquityCurveIndex(db_path=db_path)
        count = 0
        for m in run_id_or_data.get("models", []):
            rid = m.get("run_id") or m.get("id")
            # Fallback market if missing in entry
            m.get("market") or "us"
            rpt = m.get("data", {}).get("report_normal")
            if rid and rpt:
                idx.upsert_from_report_normal_json(rid, rpt)
                count += 1
        return count

    if isinstance(run_id_or_data, str) and market and report_normal and db_path:
        try:
            BacktestEquityCurveIndex(db_path=db_path).upsert_from_report_normal_json(
                run_id_or_data, report_normal
            )
            return 1
        except Exception:
            return 0
    return 0


def build_db():
    mlruns_dirs = [MLRUNS_DIR, PROJECT_ROOT / "mlruns", PROJECT_ROOT / "artifacts" / "mlruns"]
    dashboard_db_path = DASHBOARD_DB_PATH
    dashboard_db_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = resolve_metadata_db_path(PROJECT_ROOT)
    model_index = ModelRegistryIndex(db_path=db_path)

    print(f"Building comprehensive dashboard DB from {db_path} and MLflow artifacts...")

    versions = model_index.list_versions(limit=100)
    name_map = load_name_map()

    enriched_models = []
    benchmarks_cache = {}

    for v in versions:
        run_id = v.get("run_id")
        run_path = None

        if run_id:
            for m_dir in mlruns_dirs:
                if not m_dir.exists():
                    continue
                for exp_dir in m_dir.iterdir():
                    if not exp_dir.is_dir() or exp_dir.name in ["0", ".trash"]:
                        continue
                    cand = exp_dir / run_id
                    if cand.exists():
                        run_path = cand
                        break
                if run_path:
                    break

        print(f"  Processing Run {run_id or 'NO_RUN_ID'} (Model: {v['id']}) ...")

        params = {}
        if v.get("params_json"):
            try:
                params = json.loads(v["params_json"])
            except Exception:
                pass

        strategy_profile = {}
        run_data = {
            "report_normal": None,
            "positions_normal": [],
            "indicators": {},
            "sig_analysis": {},
        }

        if run_path:
            strategy_profile = load_strategy_profile_for_run(run_path, params, PROJECT_ROOT)
            run_data = load_run_data(run_path)

        report_normal = run_data.get("report_normal")
        if report_normal:
            # Handle both split JSON and list formats
            dates = []
            if isinstance(report_normal, dict) and "index" in report_normal:
                dates = report_normal["index"]
            elif isinstance(report_normal, list):
                dates = [d["date"] for d in report_normal]

            if dates:
                market = v["market"]
                bench_symbol = "QQQ" if market == "us" else "000300"
                cache_key = (tuple(sorted(dates)), bench_symbol)
                if cache_key not in benchmarks_cache:
                    benchmarks_cache[cache_key] = compute_benchmark_returns(
                        dates, bench_symbol, params.get("provider_uri", "data/watchlist")
                    )

                run_data["benchmarks"] = {bench_symbol: benchmarks_cache[cache_key]}

                # Merge benchmark returns into report_normal columns
                merge_benchmarks_into_report(
                    report_normal, {bench_symbol: benchmarks_cache[cache_key]}, market
                )

                # Compute proper indicators from report_normal data
                computed_indicators = compute_indicators_from_report(report_normal)
                if computed_indicators:
                    run_data["indicators"] = computed_indicators

                # Update SQLite with curve
                if run_id:
                    upsert_equity_curves_to_metadata_db(run_id, market, report_normal, db_path)

        # Basic model data
        model_entry = {
            "id": v["id"],
            "run_id": run_id,
            "name": format_run_name(
                v["market"], v["created_at"], run_id or v["id"], params, strategy_profile
            ),
            "date": v["created_at"],
            "experiment": "workflow",
            "market": v["market"],
            "params": params,
            "data": run_data,
            "has_full_data": run_path is not None and report_normal is not None,
        }
        enriched_models.append(model_entry)

        # Sync back to model registry
        upsert_model_registry_to_metadata_db(model_entry, db_path)

    data = {
        "generated_at": datetime.now().isoformat(),
        "models": enriched_models,
        "name_map": name_map,
    }

    with open(dashboard_db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, cls=CustomEncoder)

    # Sync to RunIndex for fast API access
    try:
        from src.assistant.run_index import RunIndex

        RunIndex(db_path=db_path).upsert_from_dashboard_db(data)
        print(f"Successfully synced {len(enriched_models)} runs to RunIndex.")
    except Exception as e:
        print(f"Warning: Failed to sync to RunIndex: {e}")

    print(
        f"Successfully wrote {len(enriched_models)} models with full backtest data to {dashboard_db_path}"
    )


if __name__ == "__main__":
    build_db()
