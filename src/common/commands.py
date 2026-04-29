from dataclasses import dataclass


@dataclass
class Command:
    id: str
    name: str
    command: str
    description: str
    role: str  # 'supported' or 'utility'
    priority: str = "P1"
    task_id: str | None = None


PROJECT_COMMANDS = [
    Command(
        id="e2e_smoke",
        name="E2E Smoke Test",
        command="python scripts/e2e_smoke.py --market {market} [--dry-run]",
        description="Single-command P0 validation of the entire pipeline.",
        role="supported",
        priority="P0",
        task_id="project.trading.e2e_smoke",
    ),
    Command(
        id="train",
        name="Training + Backtest",
        command="python -m src.orchestrator run --market {market} --model_type lgbm --tag <MODEL_TAG> [--strategy_template <STRAT>]",
        description="Full training and backtest pipeline. Generates MLflow runs and updates dashboard.",
        role="supported",
        priority="P0",
    ),
    Command(
        id="rebacktest",
        name="Re-backtest",
        command="python -m src.orchestrator rebacktest --market {market} --start 2025-01-01 --end latest",
        description="Recompute drawdown or extend backtest to latest data without retraining.",
        role="supported",
        priority="P1",
    ),
    Command(
        id="dashboard_serve",
        name="Dashboard Server",
        command="python scripts/dashboard_server.py",
        description="Serves the analytical UI and local APIs.",
        role="supported",
        priority="P0",
    ),
    Command(
        id="build_dashboard_db",
        name="Build Dashboard DB",
        command="python scripts/build_dashboard_db.py",
        description="Regenerate dashboard JSON from MLflow artifacts.",
        role="supported",
        priority="P0",
        task_id="project.trading.dashboard_db_build",
    ),
    Command(
        id="daily_run",
        name="Daily Routine",
        command="python scripts/daily_run.py",
        description="E2E sequence: data sync -> inference -> dashboard update.",
        role="supported",
        priority="P0",
        task_id="project.trading.daily_run",
    ),
    Command(
        id="arena_settle",
        name="Arena Settle",
        command='python scripts/arena_settle.py --market {market} --arena-name "{arena}" --date latest',
        description="Calculate leaderboard and rankings from backtest equity curves.",
        role="supported",
        priority="P1",
    ),
    Command(
        id="doctor",
        name="System Doctor",
        command="python scripts/doctor.py",
        description="Check environment health and metadata consistency.",
        role="supported",
        priority="P0",
    ),
    # Utilities
    Command(
        id="update_data",
        name="Update Data",
        command="python scripts/update_data.py --market {market}",
        description="Sync market data for the target market.",
        role="utility",
    ),
    Command(
        id="export_static",
        name="Static Site Export",
        command="python scripts/export_static_site_data.py --market all --output site/data",
        description="Prepares the site/ directory for GitHub Pages.",
        role="utility",
    ),
]


def get_supported_commands() -> list[Command]:
    return [c for c in PROJECT_COMMANDS if c.role == "supported"]


def get_utility_commands() -> list[Command]:
    return [c for c in PROJECT_COMMANDS if c.role == "utility"]
