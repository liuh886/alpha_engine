from pathlib import Path
import json
import yaml
import pickle
import pandas as pd
from qlib.data import D
from qlib.workflow import R
from src.common.paths import MODELS_DIR, PROJECT_ROOT, CONFIG_DIR
from src.common.market import resolve_start_date
from src.common.workflow_config import apply_backtest_and_test_window
from src.data.universe import clean_universe, apply_liquidity_filter
from src.research.training import train_model
from src.research.backtest import run_backtest
from src.research.inference import perform_inference, apply_inference_guardrails

class ResearchService:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root

    def load_config(self, market: str, model_type: str) -> dict:
        config_name = f"{market}_workflow.yaml" if model_type == "linear" else f"{market}_{model_type}_workflow.yaml"
        config_file = CONFIG_DIR / config_name
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        with open(config_file) as f:
            return yaml.safe_load(f)

    def prepare_experiment(self, market: str, config: dict, start_time: str, end_time: str = "latest", profile_data: dict = None) -> dict:
        calendar = D.calendar()
        start_resolved, _ = resolve_start_date(start_time, calendar)
        
        valid_tickers = clean_universe(market, self.project_root, start_resolved)
        if profile_data:
            valid_tickers = apply_liquidity_filter(valid_tickers, profile_data, start_resolved)
            
        if not valid_tickers:
            raise RuntimeError("No valid tickers found in universe after cleaning and filtering!")

        config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"] = valid_tickers
        config = apply_backtest_and_test_window(config, calendar, start_time=start_resolved, end_time=end_time)
        return config

    def run_training_pipeline(self, market: str, config: dict, tag: str = ""):
        exp_name = f"workflow_{market}"
        with R.start(experiment_name=exp_name):
            model, reducer, model_path = train_model(market, config["task"]["model"], config["task"]["dataset"], tag)
            
            # Re-init dataset for inference
            from qlib.utils import init_instance_by_config
            dataset = init_instance_by_config(config["task"]["dataset"])
            
            recorder = R.get_recorder()
            pred_score, labels = run_backtest(model, dataset, config["port_analysis_config"], recorder)
            
            return {
                "model_path": model_path,
                "run_id": recorder.id,
                "model": model,
                "dataset": dataset
            }

    def run_backtest_only(self, market: str, config: dict, model_path: Path):
        with open(model_path, "rb") as f:
            model = pickle.load(f)
            
        exp_name = f"workflow_{market}"
        with R.start(experiment_name=exp_name):
            from qlib.utils import init_instance_by_config
            dataset = init_instance_by_config(config["task"]["dataset"])
            
            recorder = R.get_recorder()
            pred_score, labels = run_backtest(model, dataset, config["port_analysis_config"], recorder)
            
            return {
                "run_id": recorder.id,
                "pred": pred_score,
                "label": labels,
                "recorder": recorder
            }

    def perform_rebacktest(
        self,
        market: str,
        model_path: Path,
        config: dict,
        profile_data: dict = None,
        tag: str = ""
    ):
        """
        Unified rebacktest logic.
        """
        results = self.run_backtest_only(market, config, model_path)
        
        # Persist strategy profile if provided
        if profile_data:
            try:
                from qlib.workflow import R
                import json
                import urllib.parse
                from urllib.request import url2pathname
                
                recorder = results["recorder"]
                art_uri = recorder.client.get_run(recorder.id).info.artifact_uri
                artifact_path = Path(url2pathname(urllib.parse.urlparse(art_uri).path))
                artifact_path.mkdir(exist_ok=True, parents=True)
                
                (artifact_path / "strategy_profile.json").write_text(
                    json.dumps(profile_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
                
        return results

    def run_inference(
        self,
        market: str,
        model_path: Path,
        tickers: list[str],
        inference_date: pd.Timestamp = None,
        profile_path: Path = None
    ):
        """
        Full inference pipeline including guardrails.
        """
        if inference_date is None:
            # Auto-detect latest available date
            recent_cal = D.calendar(start_time=pd.Timestamp.now() - pd.Timedelta(days=10))
            check_df = D.features(tickers, ["$close"], start_time=recent_cal[0], end_time=recent_cal[-1])
            if check_df.empty:
                raise RuntimeError(f"No data found for {market} in recent days.")
            inference_date = check_df.index.get_level_values("datetime").max()

        pred_df = perform_inference(market, model_path, tickers, inference_date, profile_path)
        combined_df = apply_inference_guardrails(pred_df, tickers, inference_date)
        
        return {
            "date": inference_date,
            "results": combined_df
        }
