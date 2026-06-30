import pickle
from copy import deepcopy
from pathlib import Path

import pandas as pd
import yaml
from qlib.data import D
from qlib.workflow import R

from src.common.logging import get_logger
from src.common.market import resolve_start_date
from src.common.paths import CONFIG_DIR, PROJECT_ROOT

logger = get_logger(__name__)
from src.common.workflow_config import apply_backtest_and_test_window, apply_label_horizon_purge
from src.data.universe import apply_liquidity_filter, clean_universe
from src.models.artifact import create_artifact
from src.models.reconstruction import validate_inference
from src.research.backtest import run_backtest
from src.research.inference import apply_inference_guardrails, perform_inference
from src.research.training import train_model


class ResearchService:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root

    def load_config(self, market: str, model_type: str) -> dict:
        config_name = (
            f"{market}_workflow.yaml"
            if model_type == "linear"
            else f"{market}_{model_type}_workflow.yaml"
        )
        config_file = CONFIG_DIR / config_name
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        with open(config_file) as f:
            return yaml.safe_load(f)

    def resolve_snapshot_binding(self, snapshot_id: str = "") -> dict[str, str]:
        """Resolve an immutable snapshot ID to the exact staged provider path."""
        from src.common.paths import SNAPSHOT_STORE
        from src.data.snapshot import DataSnapshot

        store = SNAPSHOT_STORE
        snapshot = (
            DataSnapshot.resolve_snapshot(snapshot_id, store=store)
            if snapshot_id
            else DataSnapshot.get_latest_snapshot(store=store)
        )
        if snapshot is None:
            raise FileNotFoundError("No published DataSnapshot is available for training")
        if snapshot_id and snapshot.snapshot_id != snapshot_id:
            raise RuntimeError(
                f"Resolved snapshot identity mismatch: requested={snapshot_id}, "
                f"resolved={snapshot.snapshot_id}"
            )
        provider_uri = Path(snapshot.manifest.storage_uri).resolve()
        if not provider_uri.is_dir():
            raise FileNotFoundError(
                f"Resolved DataSnapshot provider path does not exist: {provider_uri}"
            )
        return {
            "snapshot_id": snapshot.snapshot_id,
            "provider_uri": str(provider_uri),
        }

    @staticmethod
    def bind_config_to_snapshot(config: dict, binding: dict[str, str]) -> dict:
        """Return a detached config pinned to the resolved snapshot provider."""
        resolved = deepcopy(config)
        resolved.setdefault("qlib_init", {})["provider_uri"] = binding["provider_uri"]
        resolved["data_snapshot_id"] = binding["snapshot_id"]
        return resolved

    def prepare_experiment(
        self,
        market: str,
        config: dict,
        start_time: str,
        end_time: str = "latest",
        profile_data: dict = None,
    ) -> dict:
        calendar = D.calendar()
        start_resolved, _ = resolve_start_date(start_time, calendar)

        valid_tickers = clean_universe(market, self.project_root, start_resolved)
        if profile_data:
            valid_tickers = apply_liquidity_filter(valid_tickers, profile_data, start_resolved)

        if not valid_tickers:
            raise RuntimeError("No valid tickers found in universe after cleaning and filtering!")

        # apply_backtest_and_test_window deep-copies the config; mutate the
        # copy so the caller's dict is never touched.
        config = apply_backtest_and_test_window(
            config, calendar, start_time=start_resolved, end_time=end_time
        )
        config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"] = valid_tickers

        # Purge label-bearing segment ends to prevent forward-label leakage.
        config = apply_label_horizon_purge(config, calendar)

        return config

    def run_training_pipeline(
        self,
        market: str,
        config: dict,
        tag: str = "",
        snapshot_id: str = "",
        snapshot_binding: dict[str, str] | None = None,
    ):
        binding = snapshot_binding or self.resolve_snapshot_binding(snapshot_id)
        if snapshot_id and binding.get("snapshot_id") != snapshot_id:
            raise RuntimeError(
                f"Training snapshot mismatch: requested={snapshot_id}, "
                f"resolved={binding.get('snapshot_id')}"
            )
        resolved_config = self.bind_config_to_snapshot(config, binding)
        exp_name = f"workflow_{market}"
        with R.start(experiment_name=exp_name):
            model, model_path = train_model(
                market,
                resolved_config["task"]["model"],
                resolved_config["task"]["dataset"],
                tag,
                snapshot_id=binding["snapshot_id"],
            )

            # Re-init dataset for inference
            from qlib.utils import init_instance_by_config

            dataset = init_instance_by_config(resolved_config["task"]["dataset"])

            recorder = R.get_recorder()
            pred_score, labels = run_backtest(
                model, dataset, resolved_config["port_analysis_config"], recorder
            )

            raw_metrics = recorder.list_metrics() or {}
            metrics = self._extract_standard_metrics(raw_metrics)
            model_kwargs = resolved_config["task"]["model"].get("kwargs", {}) or {}
            seed = int(model_kwargs.get("seed", model_kwargs.get("random_state", 0)))
            costs = (
                resolved_config.get("port_analysis_config", {})
                .get("backtest", {})
                .get("exchange_kwargs", {})
            )
            manifest = create_artifact(
                model_dir=model_path,
                config=resolved_config,
                predictions=pred_score,
                labels=labels,
                snapshot_id=binding["snapshot_id"],
                provider_uri=binding["provider_uri"],
                benchmark=resolved_config.get("benchmark", ""),
                costs=costs,
                seeds={"python": seed, "numpy": seed, "model": seed},
                logs=[
                    f"run_id={recorder.id}",
                    f"market={market}",
                    f"snapshot_id={binding['snapshot_id']}",
                    "training=complete",
                ],
                metrics=metrics,
            )

            # Validate that the stored model binary can reproduce predictions
            inference_result = validate_inference(manifest.id, n_samples=50)

            return {
                "model_path": model_path,
                "run_id": recorder.id,
                "model": model,
                "dataset": dataset,
                "pred": pred_score,
                "label": labels,
                "metrics": metrics,
                "artifact_id": manifest.id,
                "artifact": manifest,
                "inference_result": inference_result,
                "snapshot_id": binding["snapshot_id"],
                "provider_uri": binding["provider_uri"],
            }

    @staticmethod
    def _extract_standard_metrics(raw_metrics: dict) -> dict:
        """Collapse Qlib-prefixed recorder metrics to the standard names."""
        metrics = dict(raw_metrics)
        for raw_key, value in raw_metrics.items():
            key = str(raw_key).lower()
            if "excess_return_with_cost" in key and key.endswith("annualized_return"):
                metrics.setdefault("excess_return_with_cost", value)
            elif "excess_return_without_cost" in key and key.endswith("annualized_return"):
                metrics.setdefault("excess_return", value)
            elif "excess_return_without_cost" in key and key.endswith("max_drawdown"):
                metrics.setdefault("max_drawdown", value)
            elif "bench" in key and key.endswith("max_drawdown"):
                metrics.setdefault("bench_max_drawdown", value)

            if key.endswith("information_ratio"):
                metrics.setdefault("information_ratio", value)
            if key.endswith("annualized_return"):
                metrics.setdefault("annualized_return", value)
            if key.endswith("max_drawdown"):
                metrics.setdefault("max_drawdown", value)
        return metrics

    def run_backtest_only(self, market: str, config: dict, model_path: Path):
        with open(model_path, "rb") as f:
            model = pickle.load(f)

        exp_name = f"workflow_{market}"
        with R.start(experiment_name=exp_name):
            from src.assistant.data_snapshot import build_data_snapshot_id

            try:
                latest_day = D.calendar()[-1]
                cal_day = str(latest_day.date() if hasattr(latest_day, "date") else latest_day)[:10]
                snapshot_id = build_data_snapshot_id(
                    dataset_key="watchlist", freq="day", latest_calendar_day=cal_day
                )
                R.log_params(data_snapshot_id=snapshot_id, data_end_date=cal_day)
            except Exception as e:
                logger.warning("Failed to log data_snapshot_id", error=str(e))

            from qlib.utils import init_instance_by_config

            dataset = init_instance_by_config(config["task"]["dataset"])

            recorder = R.get_recorder()
            pred_score, labels = run_backtest(
                model, dataset, config["port_analysis_config"], recorder
            )

            return {
                "run_id": recorder.id,
                "pred": pred_score,
                "label": labels,
                "recorder": recorder,
            }

    def perform_rebacktest(
        self, market: str, model_path: Path, config: dict, profile_data: dict = None, tag: str = ""
    ):
        """
        Unified rebacktest logic.
        """
        results = self.run_backtest_only(market, config, model_path)

        # Persist strategy profile if provided
        if profile_data:
            try:
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
                logger.debug("Failed to persist strategy profile artifact", exc_info=True)

        return results

    def run_inference(
        self,
        market: str,
        model_path: Path,
        tickers: list[str],
        inference_date: pd.Timestamp = None,
        profile_path: Path = None,
    ):
        """
        Full inference pipeline including guardrails.
        """
        if inference_date is None:
            # Auto-detect latest available date
            recent_cal = D.calendar(start_time=pd.Timestamp.now() - pd.Timedelta(days=10))
            check_df = D.features(
                tickers, ["$close"], start_time=recent_cal[0], end_time=recent_cal[-1]
            )
            if check_df.empty:
                raise RuntimeError(f"No data found for {market} in recent days.")
            inference_date = check_df.index.get_level_values("datetime").max()

        pred_df = perform_inference(market, model_path, tickers, inference_date, profile_path)
        combined_df = apply_inference_guardrails(pred_df, tickers, inference_date)

        return {"date": inference_date, "results": combined_df}
