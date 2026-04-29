from pathlib import Path

import fire

from src.research.registry import register_model
from src.workflows.hooks import run_rebacktest_pipeline, run_training_pipeline


def build_compile_cmd(python_exe: str, market: str, profile: str = "") -> list[str]:
    """
    Compatibility function for constructing strategy compilation command.
    """
    cmd = [python_exe, "scripts/strategy_to_workflow.py", "--market", market]
    if profile:
        cmd += ["--profile", profile]
    return cmd


class Orchestrator:
    """
    CLI wrapper for the AlphaEngine orchestration pipeline.
    Most logic has been migrated to src.workflows.hooks for API/service reuse.
    """

    def run(
        self,
        market: str = "all",
        model_type: str = "lgbm",
        profile: str = "",
        tag: str = "",
        strategy_template: str = "",
        cost_params: str = "",
        max_retries: int = 1,
    ):
        """
        Run the trading pipeline (Data -> Train -> Backtest -> Register).
        """
        return run_training_pipeline(
            market=market,
            model_type=model_type,
            profile=profile,
            tag=tag,
            strategy_template=strategy_template,
            cost_params=cost_params,
            max_retries=max_retries,
        )

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
        Re-run portfolio backtest using an existing trained model.
        """
        return run_rebacktest_pipeline(
            market=market,
            model_path=model_path,
            model_type=model_type,
            profile=profile,
            tag=tag,
            start=start,
            end=end,
            update_data=update_data,
            refresh_dashboard_db=refresh_dashboard_db,
            strategy_template=strategy_template,
            cost_params=cost_params,
        )

    def _update_model_list(self, market, model_path, config, metrics=None, run_id=None, tag=""):
        """
        Private compatibility method for model registration.
        """
        return register_model(
            market=market,
            model_path=Path(model_path),
            config=config,
            metrics=metrics,
            run_id=run_id,
            model_tag=tag,
        )


if __name__ == "__main__":
    fire.Fire(Orchestrator)
