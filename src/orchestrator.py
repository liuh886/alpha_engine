import fire
from src.workflows.hooks import run_training_pipeline, run_rebacktest_pipeline

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
            max_retries=max_retries
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
            cost_params=cost_params
        )

if __name__ == "__main__":
    import qlib # Ensure qlib is available for some imports
    fire.Fire(Orchestrator)
