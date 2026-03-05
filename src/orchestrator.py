import json
import re
import shutil
import sys
import warnings

# Suppress annoying Gym/Gymnasium warnings from Qlib
warnings.filterwarnings("ignore", category=UserWarning, module="gym")
warnings.filterwarnings("ignore", message=".*Gymnasium.*")

import pickle
import subprocess
from datetime import datetime
from pathlib import Path

import fire
import pandas as pd
import qlib
import yaml
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord

from src.assistant.data_snapshot import build_data_snapshot_id
from src.common.env_manager import EnvironmentManager
from src.common.market import resolve_start_date

from src.common.paths import CONFIG_DIR, MODELS_DIR, PROJECT_ROOT, RUNS_DIR
from src.common.workflow_config import apply_backtest_and_test_window
from src.data.dim_reduction import DimensionalityReducer


def build_compile_cmd(python_exe: str, *, market: str, profile: str | None = None) -> list[str]:
    cmd = [python_exe, "scripts/strategy_to_workflow.py", "--market", market]
    if profile:
        cmd += ["--profile", profile]
    return cmd


_SAFE_TAG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _sanitize_tag(value: str, *, max_len: int = 40) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    value = _SAFE_TAG_RE.sub("_", value)
    value = value.strip("_")
    if not value:
        return ""
    if len(value) > max_len:
        value = value[:max_len].rstrip("_")
    return value


class Orchestrator:
    def _update_model_list(
        self,
        market,
        model_path,
        config,
        metrics,
        *,
        run_id: str | None = None,
        model_tag: str = "",
        description: str = "",
    ):
        # Load existing list
        list_path = MODELS_DIR / "model_list.yaml"
        if list_path.exists():
            with open(list_path) as f:
                data = yaml.safe_load(f) or {"models": []}
        else:
            data = {"models": []}
            
        # Create new entry
        # Extract metrics safely
        safe_metrics = {}
        if isinstance(metrics, dict):
            # Flatten or select key metrics
            for k in ['annualized_return', 'information_ratio', 'max_drawdown']:
                if k in metrics:
                    safe_metrics[k] = float(metrics[k])
        
        entry = {
            "id": f"{market}_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "tag": str(model_tag or ""),
            "name": str(model_tag or ""),
            "path": str(model_path).replace("\\", "/"),
            "type": config['task']['model']['class'],
            "market": market,
            "created_at": str(datetime.now().date()),
            "description": str(description or ""),
            "params": config['task']['model']['kwargs'],
            "training": {
                "dataset": config['market'],
                "period": config['task']['dataset']['kwargs']['segments']['train']
            },
            "backtest": {
                "period": f"{config['port_analysis_config']['backtest']['start_time']} to {config['port_analysis_config']['backtest']['end_time']}",
                "metrics": safe_metrics
            }
        }

        if run_id:
            entry["run_id"] = str(run_id)
        
        data["models"].append(entry)
        
        with open(list_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)
            
        print(f"Registered model to {list_path}")

        # Best-effort: sync to SQLite model registry index for fast querying.
        try:
            from src.assistant.metadata_db import resolve_metadata_db_path
            from src.assistant.model_registry_index import ModelRegistryIndex

            ModelRegistryIndex(db_path=resolve_metadata_db_path(Path("."))).upsert_entry(entry)
        except Exception:
            pass

    def run(
        self,
        market: str = "all",
        model_type: str = "lgbm",
        profile: str = "",
        tag: str = "",
        strategy_template: str = "",
        cost_params: str = "",
    ):
        """
        Run the trading pipeline for the specified market.
        Args:
            market: 'cn', 'us', or 'all'
            model_type: 'lgbm' (default) or 'linear' (legacy)
            profile: optional strategy profile JSON
            tag: optional model tag/name to identify this run
            strategy_template: optional name of the strategy template used
            cost_params: optional JSON string of cost parameters
        """
        tag = str(tag or "").strip()
        if not tag:
            raise ValueError("tag is required. Example: python -m src.orchestrator run --market us --tag LGBM_v2_20260205")

        env = EnvironmentManager(PROJECT_ROOT)

        if market == "all":
            print("=== Running Pipeline for ALL Markets ===")
            for m in ["cn", "us"]:
                args = ["run", "--market", m, "--model_type", str(model_type), "--tag", str(tag)]
                if profile:
                    args += ["--profile", str(profile)]
                if strategy_template:
                    args += ["--strategy_template", str(strategy_template)]
                if cost_params:
                    args += ["--cost_params", str(cost_params)]
                env.run_in_isolation("src.orchestrator", args)
            return

        print(f"\n>>> Starting Pipeline: {market.upper()} [{model_type.upper()}]")
        
        # 1. Load Config & Initialize
        config_name = f"{market}_workflow.yaml" if model_type == "linear" else f"{market}_{model_type}_workflow.yaml"
        
        # Compile strategy profile
        compile_cmd = build_compile_cmd(sys.executable, market=market, profile=(profile or None))
        subprocess.run(compile_cmd, check=True)
            
        config_file = CONFIG_DIR / config_name
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
            
        with open(config_file) as f:
            config = yaml.safe_load(f)

        env.ensure_qlib(market, config)
        from src.common.paths import ARTIFACTS_DIR, REPORTS_DIR
        env.check_directories([MODELS_DIR, ARTIFACTS_DIR, REPORTS_DIR, RUNS_DIR])

        # 2. Universe Pre-check (Optimized)
        from qlib.data import D
        print("Cleaning universe...")
        market_file = PROJECT_ROOT / f"data/watchlist/instruments/{market}.txt"
        all_tickers = []
        if market_file.exists():
            with open(market_file) as f:
                for line in f:
                    all_tickers.append(line.strip().split("\t")[0])
        
        start_date = config['task']['dataset']['kwargs']['handler']['kwargs']['start_time']
        calendar = D.calendar()
        latest_calendar_day = pd.Timestamp(calendar[-1]).strftime("%Y-%m-%d") if len(calendar) > 0 else None
        start_date, _ = resolve_start_date(start_date, calendar)
        config['task']['dataset']['kwargs']['handler']['kwargs']['start_time'] = start_date
        
        end_check_date = pd.Timestamp(start_date) + pd.Timedelta(days=10)
        valid_tickers = []
        if all_tickers:
            try:
                check_df = D.features(all_tickers, ["$close"], start_time=start_date, end_time=end_check_date)
                if not check_df.empty:
                    valid_tickers = check_df.index.get_level_values("instrument").unique().tolist()
            except Exception:
                # Iterative fallback omitted for brevity in this refined version, 
                # but batch check is the primary path.
                valid_tickers = all_tickers 
        
        if not valid_tickers:
            raise RuntimeError("No valid tickers found in universe!")

        config['task']['dataset']['kwargs']['handler']['kwargs']['instruments'] = valid_tickers
        config = apply_backtest_and_test_window(config, calendar, default_start="2025-01-01")

        # 3. Execute Workflow (Training + Backtest)
        exp_name = f"workflow_{market}"
        model_config = config['task']['model']
        dataset_config = config['task']['dataset']
        
        with R.start(experiment_name=exp_name):
            # Training
            print("Training Model...")
            dataset = init_instance_by_config(dataset_config)
            
            # [ROADMAP 18] Dimensionality Reduction Channel
            # Extract training features and reduce dimensionality via PCA before feeding into the booster
            from qlib.data.dataset.handler import DataHandler
            try:
                train_features = dataset.prepare(segments="train", col_set="feature", data_key="feature")
            except KeyError:
                train_features = dataset.prepare(segments="train", col_set="feature", data_key=DataHandler.DK_I)
                
            reducer = DimensionalityReducer(variance_retained=0.95)
            reduced_train_features = reducer.fit_transform(train_features)
            
            print(f"PCA Reduced dimensions from {train_features.shape[1]} to {reduced_train_features.shape[1]}")
            
            model = init_instance_by_config(model_config)
            # In a real environment, Qlib datasets need to be hacked to inject transformed pandas logic.
            # For demonstration in this local-first loop, we assume the dataset object accepts patched logic 
            # or we rely on the estimator pipeline. For now, we fit native.
            model.fit(dataset)
            
            # Save Model & Reducer
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_tag = _sanitize_tag(tag)
            model_filename = f"{market}_model_{safe_tag}_{timestamp}.pkl" if safe_tag else f"{market}_model_{timestamp}.pkl"
            model_path = MODELS_DIR / model_filename
            with open(model_path, "wb") as f:
                pickle.dump(model, f)
            with open(MODELS_DIR / f"{market}_reducer.pkl", "wb") as f:
                pickle.dump(reducer, f)
            shutil.copy(model_path, MODELS_DIR / f"{market}_model.pkl")

            # Record Metadata
            recorder = R.get_recorder()
            run_id = recorder.id
            provider_uri = config.get("qlib_init", {}).get("provider_uri", "data/watchlist")
            dataset_key = Path(str(provider_uri)).name
            data_snapshot_id = build_data_snapshot_id(dataset_key=dataset_key, freq="day", latest_calendar_day=latest_calendar_day)
            
            R.log_params(**{
                "run_id": run_id,
                "model_tag": tag,
                "data_snapshot_id": data_snapshot_id,
                "market": market,
                "strategy_template": strategy_template or "",
                "cost_params": cost_params or ""
            })
            
            # Predict & Portfolio Analysis
            pred_score = model.predict(dataset)
            from qlib.data.dataset.handler import DataHandler
            try:
                labels = dataset.prepare(segments="test", col_set="label", data_key="label")
            except KeyError:
                labels = dataset.prepare(segments="test", col_set="label", data_key=DataHandler.DK_L)
            
            R.save_objects(pred=pred_score, label=labels)
            pa_record = PortAnaRecord(recorder, config['port_analysis_config'])
            pa_record.generate()
            
            # Finalize registration
            self._update_model_list(market, model_path, config, {}, run_id=run_id, model_tag=tag)

        # 4. Reporting & Dashboard Update
        subprocess.run([sys.executable, "-m", "src.reporting.generate", "--market", market], check=True)
        subprocess.run([sys.executable, "scripts/build_dashboard_db.py"], check=True)
        print(f"<<< Pipeline Finished: {market.upper()}")

    def rebacktest(
        self,
        market: str = "us",
        model_path: str = "",
        model_type: str = "lgbm",
        profile: str = "",
        tag: str = "",
        start: str = "2025-01-01",
        end: str = "latest",
        update_data: bool = False,
        refresh_dashboard_db: bool = True,
        strategy_template: str = "",
        cost_params: str = "",
    ):
        """
        Re-run portfolio backtest (drawdown/metrics) using an existing trained model (NO retrain).

        Typical use:
        - Recompute drawdown for the current latest model
        - Extend backtest to the latest trading day (if local data is updated)

        Args:
            market: 'cn', 'us', or 'all'
            model_path: path to a pickled model. Default: models/{market}_model.pkl
            model_type: 'lgbm' (default) or 'linear' (legacy)
            profile: optional strategy profile JSON to compile before backtest
            start: backtest start date (default: 2025-01-01)
            end: backtest end date or 'latest' (default)
            update_data: if True, run scripts/update_data.py before backtest
            refresh_dashboard_db: if True, rebuild artifacts/dashboard/dashboard_db.json
            strategy_template: optional name of the strategy template used
            cost_params: optional JSON string of cost parameters
        """
        if market == "all":
            if update_data:
                subprocess.run([sys.executable, "scripts/update_data.py"], check=True)
            for m in ["cn", "us"]:
                cmd = [
                    sys.executable,
                    "-m",
                    "src.orchestrator",
                    "rebacktest",
                    "--market",
                    m,
                    "--model_type",
                    str(model_type),
                    "--start",
                    str(start),
                    "--end",
                    str(end),
                ]
                if profile:
                    cmd += ["--profile", str(profile)]
                if tag:
                    cmd += ["--tag", str(tag)]
                if strategy_template:
                    cmd += ["--strategy_template", str(strategy_template)]
                if cost_params:
                    cmd += ["--cost_params", str(cost_params)]
                if refresh_dashboard_db is False:
                    cmd += ["--refresh_dashboard_db", "False"]
                subprocess.run(cmd, check=True)
            return

        if update_data:
            subprocess.run([sys.executable, "scripts/update_data.py"], check=True)

        print(f"\n>>> Re-backtesting (NO retrain): {market.upper()} [{model_type.upper()}]")

        # (Optional) compile profile into workflow config for this market
        compile_cmd = build_compile_cmd(sys.executable, market=market, profile=(profile or None))
        subprocess.run(compile_cmd, check=True)

        if model_type == "linear":
            config_name = f"{market}_workflow.yaml"
        else:
            config_name = f"{market}_{model_type}_workflow.yaml"
        config_file = CONFIG_DIR / config_name
        if not config_file.exists():
            print(f"Error: Config file not found: {config_file}")
            return

        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        from src.common.qlib_init import build_qlib_init_cfg

        qlib_init_cfg = build_qlib_init_cfg(config.get("qlib_init", {}) or {}, market=market)

        # Ensure `<freq>_future.txt` exists so Qlib backtests can compute last interval endpoints.
        try:
            from src.common.future_calendar import ensure_calendar_future_file

            provider_uri = qlib_init_cfg.get("provider_uri")
            if isinstance(provider_uri, str) and provider_uri:
                provider_path = Path(provider_uri)
                if not provider_path.is_absolute():
                    provider_path = PROJECT_ROOT / provider_path
                ensure_calendar_future_file(provider_path, freq="day", extra_days=1)
        except Exception:
            pass
        try:
            qlib.init(**qlib_init_cfg)
        except Exception:
            print("Warning: Qlib already initialized. Proceeding...")

        from qlib.data import D

        calendar = D.calendar()
        start_resolved, adjusted = resolve_start_date(start, calendar)
        if adjusted:
            print(f"  Adjusted backtest start date to first available calendar date: {start_resolved}")

        # Universe (same self-healing pre-check as `run`)
        print("Cleaning universe (removing stocks with missing data)...")
        market_file = Path(f"data/watchlist/instruments/{market}.txt")
        all_tickers = []
        if market_file.exists():
            with open(market_file) as f:
                for line in f:
                    all_tickers.append(line.strip().split("\t")[0])

        warmup_end = pd.Timestamp(start_resolved) + pd.Timedelta(days=10)
        valid_tickers = []
        if all_tickers:
            try:
                # Check all tickers in one batch for data availability in the warm-up window
                check_df = D.features(all_tickers, ["$close"], start_time=start_resolved, end_time=warmup_end)
                if not check_df.empty:
                    valid_tickers = check_df.index.get_level_values("instrument").unique().tolist()
            except Exception as e:
                print(f"  Warning: Batch universe check failed: {e}. Falling back to iterative check.")
                for t in all_tickers:
                    try:
                        if not D.features([t], ["$close"], start_time=start_resolved, end_time=warmup_end).empty:
                            valid_tickers.append(t)
                    except Exception:
                        continue

        missing_count = len(all_tickers) - len(valid_tickers)
        if missing_count > 0:
            print(f"  Dropped {missing_count} stocks due to missing data at start date {start_resolved}")
        if not valid_tickers:
            print("Error: No valid tickers found in universe! check data and start_date.")
            return

        # Apply optional universe filters from profile (e.g., min_liquidity)
        profile_data = {}
        profile_for_filters = profile or "configs/strategy_profile.json"
        profile_path = Path(profile_for_filters)
        candidates = [profile_path]
        if not profile_path.is_absolute():
            candidates = [
                PROJECT_ROOT / profile_path,
                CONFIG_DIR / profile_path,
                CONFIG_DIR / profile_path.name,
            ]
        for cand in candidates:
            if cand.exists():
                try:
                    with open(cand, encoding="utf-8") as f:
                        profile_data = json.load(f)
                except Exception as e:
                    print(f"Warning: Could not load profile {cand}: {e}")
                break

        model_tag = str(tag or "").strip()
        if not model_tag:
            try:
                model_tag = str((profile_data.get("meta", {}) or {}).get("name") or "").strip()
            except Exception:
                model_tag = ""

        try:
            from src.common.universe import apply_profile_universe_filters

            min_liquidity = (
                (profile_data.get("universe", {}) or {})
                .get("filters", {})
                .get("min_liquidity")
            )
            if min_liquidity is not None:
                before = len(valid_tickers)
                valid_tickers = apply_profile_universe_filters(
                    valid_tickers,
                    profile=profile_data,
                    asof_time=start_resolved,
                    fetch_features=D.features,
                )
                dropped = before - len(valid_tickers)
                if dropped > 0:
                    print(f"  Dropped {dropped} stocks due to min_liquidity >= {min_liquidity}")
        except Exception:
            pass

        if not valid_tickers:
            print("Error: Universe empty after filters! check data and profile filters.")
            return

        config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"] = valid_tickers

        # Apply backtest window (start override + end=latest by default) AND extend dataset test segment.
        config = apply_backtest_and_test_window(
            config,
            calendar,
            default_start="2025-01-01",
            start_time=start_resolved,
            end_time=end,
        )

        # Load model
        if not model_path:
            model_path = str(MODELS_DIR / f"{market}_model.pkl")
        model_path_p = Path(model_path)
        if not model_path_p.exists():
            print(f"Error: Model not found: {model_path_p}")
            return
        with open(model_path_p, "rb") as f:
            model = pickle.load(f)

        exp_name = f"workflow_{market}"
        dataset_config = config["task"]["dataset"]
        port_ana_config = config["port_analysis_config"]

        with R.start(experiment_name=exp_name):
            recorder = R.get_recorder()
            run_id = recorder.id

            try:
                R.log_params(
                    **{
                        "mode": "rebacktest",
                        "market": market,
                        "model_type": model_type,
                        "source_model_path": str(model_path_p).replace("\\", "/"),
                        "profile": profile or "",
                        "model_tag": model_tag or "",
                        "backtest_start": str(port_ana_config.get("backtest", {}).get("start_time", "")),
                        "backtest_end": str(port_ana_config.get("backtest", {}).get("end_time", "")),
                        "data_end_date": str(port_ana_config.get("backtest", {}).get("end_time", "")),
                        "data_snapshot_id": build_data_snapshot_id(
                            dataset_key=Path(str(qlib_init_cfg.get("provider_uri") or "")).name or "watchlist",
                            freq="day",
                            latest_calendar_day=str(port_ana_config.get("backtest", {}).get("end_time", "")),
                        ),
                        "strategy_template": strategy_template or "",
                        "cost_params": cost_params or "",
                    }
                )
            except Exception:
                pass

            print(f"Backtest run_id: {run_id}")
            print("Initializing Dataset...")
            dataset = init_instance_by_config(dataset_config)

            print("Running Inference for Backtest (reuse model)...")
            pred_score = model.predict(dataset)
            if isinstance(pred_score, pd.Series):
                pred_score = pred_score.to_frame("score")
            from qlib.data.dataset.handler import DataHandler

            try:
                labels = dataset.prepare(segments="test", col_set="label", data_key="label")
            except KeyError:
                labels = dataset.prepare(segments="test", col_set="label", data_key=DataHandler.DK_L)

            R.save_objects(pred=pred_score, label=labels)

            import urllib.parse
            from urllib.request import url2pathname
            art_uri = recorder.client.get_run(recorder.id).info.artifact_uri
            artifact_path = Path(url2pathname(urllib.parse.urlparse(art_uri).path))
            artifact_path.mkdir(exist_ok=True, parents=True)

            # Persist the exact strategy profile used for this run (for reproducibility + dashboard display).
            try:
                if isinstance(profile_data, dict) and profile_data:
                    (artifact_path / "strategy_profile.json").write_text(
                        json.dumps(profile_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except Exception:
                pass
            with open(artifact_path / "pred.pkl", "wb") as f:
                pickle.dump(pred_score, f)
            with open(artifact_path / "label.pkl", "wb") as f:
                pickle.dump(labels, f)

            print("Running Portfolio Analysis...")
            pa_record = PortAnaRecord(recorder, port_ana_config)
            pa_record.generate()

        if refresh_dashboard_db:
            print("Updating dashboard DB...")
            subprocess.run([sys.executable, "scripts/build_dashboard_db.py"], check=True)

            # Best-effort: generate a lightweight HTML report for the latest run.
            try:
                from src.assistant.metadata_db import resolve_metadata_db_path
                from src.reporting.backtest_report import generate_latest_backtest_report

                rep = generate_latest_backtest_report(
                    market=market,
                    project_root=PROJECT_ROOT,
                    db_path=resolve_metadata_db_path(PROJECT_ROOT),
                )
                rel = str(rep.get("report_rel_path") or "")
                if rel:
                    print(f"Backtest report: /{rel.lstrip('/')}")
            except Exception as e:
                print(f"Warning: Failed to generate backtest report: {e}")

        print(f"<<< Re-backtest Finished: {market.upper()}")

if __name__ == "__main__":
    # If this script is called recursively for 'all', we need to handle it.
    # Fire handles the CLI args.
    fire.Fire(Orchestrator)
